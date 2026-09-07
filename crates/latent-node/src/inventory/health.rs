use std::time::{Duration, Instant};

use latent_admission::NodeAdmissionPolicy;

use super::{
    HealthStatus, NodeHealthObservation, NodePressureObservation, StandaloneInventorySources,
};

impl NodeHealthObservation {
    pub(super) fn new(observed_at_unix_millis: u64) -> Self {
        Self {
            status: HealthStatus::Healthy,
            ready: true,
            healthy: true,
            reasons: Vec::new(),
            observed_at_unix_millis,
        }
    }

    pub(super) fn degrade(&mut self, reason: &'static str, ready: bool, healthy: bool) {
        self.ready &= ready;
        self.healthy &= healthy;
        self.status = if self.healthy {
            HealthStatus::Degraded
        } else {
            HealthStatus::Unhealthy
        };
        if !self.reasons.iter().any(|existing| existing == reason) {
            debug_assert!(self.reasons.len() < 16);
            self.reasons.push(reason.to_owned());
        }
    }
}

pub(super) fn load(
    sources: &StandaloneInventorySources,
    now: Instant,
    maximum_age: Duration,
    health: &mut NodeHealthObservation,
) -> NodePressureObservation {
    let mut pressure = NodePressureObservation::default();
    let Ok(load) = sources.load.snapshot() else {
        health.degrade("load-unavailable", false, false);
        return pressure;
    };
    let policy = sources.quotas.policy();
    let age = now.checked_duration_since(load.observed_at);
    pressure.load_sample_age_millis =
        age.map(|age| u64::try_from(age.as_millis()).unwrap_or(u64::MAX));
    let maximum_age = maximum_age.min(Duration::from_millis(
        policy.overload.maximum_sample_age_millis,
    ));
    if age.is_none_or(|age| age > maximum_age) {
        health.degrade("load-not-current", false, false);
    } else if load.cpu_pressure_milli > 1000 || load.memory_pressure_milli > 1000 {
        health.degrade("load-invalid", false, false);
    } else {
        pressure.load_available = true;
        pressure.cpu_pressure_milli = u32::from(load.cpu_pressure_milli);
        pressure.memory_pressure_milli = u32::from(load.memory_pressure_milli);
        if !load.accepting {
            health.degrade("node-not-accepting", false, true);
        }
        overloaded(policy, &pressure, health);
    }
    pressure
}

fn overloaded(
    policy: &NodeAdmissionPolicy,
    pressure: &NodePressureObservation,
    health: &mut NodeHealthObservation,
) {
    if pressure.cpu_pressure_milli >= u32::from(policy.overload.maximum_cpu_pressure_milli)
        || pressure.memory_pressure_milli
            >= u32::from(policy.overload.maximum_memory_pressure_milli)
    {
        health.degrade("node-overloaded", false, true);
    }
}

pub(super) fn ratio(used: u64, maximum: u64) -> u32 {
    if maximum == 0 {
        return u32::from(used != 0) * 1000;
    }
    u32::try_from((u128::from(used) * 1000 / u128::from(maximum)).min(1000))
        .expect("clamped milli ratio")
}
