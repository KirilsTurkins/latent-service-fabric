//! Guest metrics enter the shared telemetry owner through exact current grants.
use super::{
    ActivationCapabilityBroker, CapabilityCallCost, CapabilityDispatch, CapabilityRequestDigest,
    CapabilitySession, ProviderBudgetRequirement, ProviderCall, ProviderConfiguration,
    ProviderReference, ProviderRegistration,
};
use latent_core::{BoxFuture, BudgetDimension, PlatformError};
use latent_policy::capability::ResourceTarget;
pub use latent_telemetry::custom::CustomMetricError as MetricError;
use latent_telemetry::{
    custom::{
        CustomMetricInput, CustomMetricRegistry, CustomMetricSource, CustomMetricsConfig,
        MetricSelection,
    },
    MetricKind, TelemetryHandle,
};
use sha2::{Digest, Sha256};
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc,
};
mod ownership;
use ownership::Reservation;
pub(super) use ownership::SessionUsage;

pub const METRICS_CAPABILITY: &str = "latent:telemetry/custom@0.1.0";
pub const METRICS_PROFILE: &str = "custom-metrics-v1";
const FUEL: u64 = 100;
pub struct Metric {
    pub name: String,
    pub kind: MetricKind,
    pub value: f64,
    pub unit: String,
    pub attributes: Vec<(String, String)>,
}
impl Metric {
    fn borrowed(&self) -> CustomMetricInput<'_> {
        CustomMetricInput {
            name: &self.name,
            kind: self.kind,
            value: self.value,
            unit: &self.unit,
            attributes: &self.attributes,
        }
    }
    fn retained_bytes(&self) -> Result<usize, MetricError> {
        if self.name.capacity() > 64 || self.unit.capacity() > 16 || self.attributes.capacity() > 8
        {
            return Err(MetricError::BudgetExhausted);
        }
        let mut bytes = size_of::<Self>()
            + self.name.capacity()
            + self.unit.capacity()
            + self.attributes.capacity() * size_of::<(String, String)>();
        for (key, value) in &self.attributes {
            if key.capacity() > 32 || value.capacity() > 64 {
                return Err(MetricError::BudgetExhausted);
            }
            bytes += key.capacity() + value.capacity();
        }
        Ok(bytes)
    }
    fn digest(&self) -> Result<CapabilityRequestDigest, PlatformError> {
        let kind = [match self.kind {
            MetricKind::Counter => 0,
            MetricKind::UpDownCounter => 1,
            MetricKind::Gauge => 2,
            MetricKind::Histogram => 3,
        }];
        let mut digest = CapabilityRequestDigest::from_parts(&[
            self.name.as_bytes(),
            &kind,
            &self.value.to_bits().to_le_bytes(),
            self.unit.as_bytes(),
        ])?;
        for (key, value) in &self.attributes {
            digest = digest
                .with_context(key.as_bytes())?
                .with_context(value.as_bytes())?;
        }
        Ok(digest)
    }
}
#[derive(Clone, Copy, Debug)]
pub struct MetricActivationLimits {
    pub maximum_observations: usize,
    pub maximum_series: usize,
    pub maximum_record_bytes: usize,
}
impl Default for MetricActivationLimits {
    fn default() -> Self {
        Self {
            maximum_observations: 128,
            maximum_series: 16,
            maximum_record_bytes: 1024 * 1024,
        }
    }
}
impl MetricActivationLimits {
    fn validate(self) -> Result<(), PlatformError> {
        if !(1..=1024).contains(&self.maximum_observations)
            || !(1..=32).contains(&self.maximum_series)
            || !(32 * 1024..=4 * 1024 * 1024).contains(&self.maximum_record_bytes)
        {
            return Err(super::invalid());
        }
        Ok(())
    }
}
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct MetricProviderSnapshot {
    pub attempted: u64,
    pub accepted: u64,
    pub invalid: u64,
    pub exhausted: u64,
    pub unavailable: u64,
}
pub struct MetricCompletion {
    pub accepted: bool,
    pub owner: ProviderCall,
}
pub type PendingMetric = BoxFuture<'static, Result<MetricCompletion, MetricError>>;
pub struct MetricProvider {
    registration: ProviderRegistration,
    registry: Arc<CustomMetricRegistry>,
    limits: MetricActivationLimits,
    attempted: AtomicU64,
    accepted: AtomicU64,
    invalid: AtomicU64,
    exhausted: AtomicU64,
    unavailable: AtomicU64,
}
impl MetricProvider {
    pub fn install(
        broker: &ActivationCapabilityBroker,
        handle: TelemetryHandle,
        epoch: u64,
        config: CustomMetricsConfig,
        limits: MetricActivationLimits,
    ) -> Result<Arc<Self>, PlatformError> {
        limits.validate()?;
        if epoch == 0 {
            return Err(super::invalid());
        }
        let registry = CustomMetricRegistry::install(handle, config, broker.inner.clock.clone())?;
        let mut hash = Sha256::new();
        hash.update(METRICS_PROFILE);
        hash.update(registry.configuration_digest());
        for value in [
            limits.maximum_observations,
            limits.maximum_series,
            limits.maximum_record_bytes,
        ] {
            hash.update((value as u64).to_le_bytes());
        }
        let digest = format!("sha256:{:x}", hash.finalize());
        let registration = broker.register_provider(ProviderConfiguration {
            capability: METRICS_CAPABILITY,
            profile: METRICS_PROFILE,
            configuration_digest: &digest,
            configuration_epoch: epoch,
            restriction_json: br#"{"operations":["emit-metric"]}"#,
            minimum_call_charges: &[ProviderBudgetRequirement {
                operation: "emit-metric",
                dimension: BudgetDimension::CpuFuel,
                minimum: FUEL,
            }],
        })?;
        Ok(Arc::new(Self {
            registration,
            registry,
            limits,
            attempted: AtomicU64::new(0),
            accepted: AtomicU64::new(0),
            invalid: AtomicU64::new(0),
            exhausted: AtomicU64::new(0),
            unavailable: AtomicU64::new(0),
        }))
    }
    #[must_use]
    pub fn reference(&self) -> ProviderReference {
        self.registration.reference()
    }
    #[must_use]
    pub fn registry(&self) -> &Arc<CustomMetricRegistry> {
        &self.registry
    }
    pub fn retire(&self) {
        self.registration.retire();
        self.registry.retire();
    }
    #[must_use]
    pub fn snapshot(&self) -> MetricProviderSnapshot {
        MetricProviderSnapshot {
            attempted: self.attempted.load(Ordering::Relaxed),
            accepted: self.accepted.load(Ordering::Relaxed),
            invalid: self.invalid.load(Ordering::Relaxed),
            exhausted: self.exhausted.load(Ordering::Relaxed),
            unavailable: self.unavailable.load(Ordering::Relaxed),
        }
    }
    pub fn emit(
        self: &Arc<Self>,
        session: &CapabilitySession,
        metric: Metric,
    ) -> Result<PendingMetric, MetricError> {
        add(&self.attempted);
        let prepared = (|| {
            let bytes = metric.retained_bytes()?;
            if !session.uses_provider(&self.reference())? {
                return Err(MetricError::Unavailable);
            }
            let selected = self
                .registry
                .inspect(source(&session.core), metric.borrowed())?;
            let reservation = Reservation::new(
                session,
                selected.series_digest(),
                selected.record_bytes(),
                self.limits,
            )?;
            // Only a compact validated selection survives the call boundary.
            // No guest String/Vec is retained across audit or exporter waits.
            let cost = CapabilityCallCost::new(1)
                .with_typed_input_bytes(bytes)
                .with_typed_request_digest(metric.digest()?)
                .with_charge(BudgetDimension::CpuFuel, FUEL + bytes as u64)?;
            let dispatch = session.prepare_owned_dispatch(
                METRICS_CAPABILITY,
                "emit-metric",
                ResourceTarget::Telemetry { name: &metric.name },
                &[],
                cost,
            )?;
            Ok((dispatch, reservation, selected))
        })();
        drop(metric);
        let (dispatch, reservation, selected) =
            prepared.inspect_err(|error| self.failed(*error))?;
        let provider = self.clone();
        Ok(Box::pin(async move {
            provider
                .execute(dispatch, reservation, selected)
                .await
                .inspect_err(|error| provider.failed(*error))
        }))
    }
    async fn execute(
        &self,
        dispatch: CapabilityDispatch,
        mut reservation: Reservation,
        selected: MetricSelection,
    ) -> Result<MetricCompletion, MetricError> {
        let mut call = dispatch.dispatch(|call| call).await?;
        call.require_host_mode()?;
        if !call.provider_matches(&self.reference()) {
            return Err(MetricError::Unavailable);
        }
        let core = call.session_core();
        call.check()?;
        let result = self.registry.try_emit_selected(source(&core), selected);
        if result == Ok(true) {
            reservation.commit();
            add(&self.accepted);
        }
        call.record_provider_outcome(if result == Ok(true) {
            latent_audit::AuditProviderOutcome::HostCompleted
        } else {
            latent_audit::AuditProviderOutcome::Rejected
        })?;
        call.finish_audit().await;
        call.check()?;
        Ok(MetricCompletion {
            accepted: result?,
            owner: call,
        })
    }
    fn failed(&self, error: MetricError) {
        add(match error {
            MetricError::InvalidName => &self.invalid,
            MetricError::BudgetExhausted => &self.exhausted,
            MetricError::Unavailable => &self.unavailable,
        });
    }
}
impl Drop for MetricProvider {
    fn drop(&mut self) {
        self.retire();
    }
}
fn source(core: &super::session::SessionCore) -> CustomMetricSource<'_> {
    let target = &core.plan.target;
    CustomMetricSource {
        tenant: &target.tenant.0,
        service: &target.service.0,
        revision: &target.revision.0,
    }
}
fn add(counter: &AtomicU64) {
    let _ = counter.fetch_update(Ordering::Relaxed, Ordering::Relaxed, |v| {
        Some(v.saturating_add(1))
    });
}
