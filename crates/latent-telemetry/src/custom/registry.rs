use super::{
    config, model::Sample, CustomAggregation, CustomMetricDescriptor, CustomMetricError as E,
    CustomMetricInput, CustomMetricPoint, CustomMetricSource, CustomMetricsConfig,
};
use crate::{MetricKind, MetricPoint, TelemetryHandle};
use latent_core::{ActivationClock, Metadata};
use sha2::{Digest, Sha256};
use std::sync::{
    atomic::{AtomicBool, AtomicU64, Ordering},
    Arc, Mutex,
};
use std::time::{Duration, Instant};
mod queue;
mod series;
#[cfg(test)]
mod tests;
pub(crate) use queue::QueueCharge;
use queue::QueueCounters;
use series::{Series, Values};

/// Conservative maximum for one fully materialized custom record, before copying.
pub(crate) const RECORD_BYTES: usize = 32 * 1024;
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct CustomMetricSnapshot {
    pub active_series: usize,
    pub tenant_series: [usize; 8],
    pub queued_bytes: usize,
    pub tenant_queued_bytes: [usize; 8],
    pub accepted: u64,
    pub invalid: u64,
    pub exhausted: u64,
    pub unavailable: u64,
    pub retired: bool,
}
struct State {
    series: Vec<Series>,
    tenant_series: [usize; 8],
    window: Instant,
    observations: usize,
    tenant_observations: [usize; 8],
    sequence: u64,
}
/// No per-service registry, exporter, task or timer. One installation is allowed
/// during a pipeline lifetime; reconfiguration requires a new node composition.
pub struct CustomMetricRegistry {
    config: CustomMetricsConfig,
    identity: Arc<()>,
    digest: String,
    handle: TelemetryHandle,
    clock: Arc<dyn ActivationClock>,
    state: Mutex<State>,
    queued: Arc<QueueCounters>,
    retired: AtomicBool,
    accepted: AtomicU64,
    invalid: AtomicU64,
    exhausted: AtomicU64,
    unavailable: AtomicU64,
}
/// A bounded inspection result, not an admission or permission token.
#[derive(Clone)]
pub struct MetricSelection {
    tenant: usize,
    descriptor: usize,
    labels: [u8; 8],
    digest: [u8; 32],
    value: f64,
    owner: Arc<()>,
}
impl MetricSelection {
    #[must_use]
    pub fn series_digest(&self) -> [u8; 32] {
        self.digest
    }
    #[must_use]
    pub const fn record_bytes(&self) -> usize {
        RECORD_BYTES
    }
}
impl CustomMetricRegistry {
    pub fn install(
        handle: TelemetryHandle,
        config: CustomMetricsConfig,
        clock: Arc<dyn ActivationClock>,
    ) -> Result<Arc<Self>, E> {
        config.validate()?;
        let mut hash = HashWriter(Sha256::new());
        serde_json::to_writer(&mut hash, &config).map_err(|_| E::InvalidName)?;
        let digest = format!("sha256:{:x}", hash.0.finalize());
        let mut series = Vec::new();
        series
            .try_reserve_exact(config.limits.maximum_series)
            .map_err(|_| E::BudgetExhausted)?;
        let window = clock.monotonic_now();
        handle.install_custom()?;
        Ok(Arc::new(Self {
            config,
            identity: Arc::new(()),
            digest,
            handle,
            clock,
            state: Mutex::new(State {
                series,
                tenant_series: [0; 8],
                window,
                observations: 0,
                tenant_observations: [0; 8],
                sequence: 0,
            }),
            queued: Arc::new(QueueCounters::default()),
            retired: AtomicBool::new(false),
            accepted: AtomicU64::new(0),
            invalid: AtomicU64::new(0),
            exhausted: AtomicU64::new(0),
            unavailable: AtomicU64::new(0),
        }))
    }
    #[must_use]
    pub fn configuration_digest(&self) -> &str {
        &self.digest
    }
    pub fn retire(&self) {
        self.retired.store(true, Ordering::Release);
    }
    fn live(&self) -> Result<(), E> {
        if self.retired.load(Ordering::Acquire) || self.handle.is_closed() {
            Err(E::Unavailable)
        } else {
            Ok(())
        }
    }
    pub fn inspect(
        &self,
        source: CustomMetricSource<'_>,
        input: CustomMetricInput<'_>,
    ) -> Result<MetricSelection, E> {
        self.live()?;
        if !config::token(source.tenant, 128)
            || !config::token(source.service, 128)
            || !config::token(source.revision, 128)
            || !config::name(input.name)
            || !config::token(input.unit, 16)
            || !input.value.is_finite()
            || input.attributes.len() > 8
            || (input.kind == MetricKind::Counter && input.value < 0.0)
        {
            return Err(E::InvalidName);
        }
        let tenant = self
            .config
            .tenants
            .iter()
            .position(|t| t.tenant == source.tenant)
            .ok_or(E::Unavailable)?;
        let descriptor = self.config.tenants[tenant]
            .metrics
            .iter()
            .position(|d| d.name == input.name)
            .ok_or(E::InvalidName)?;
        let d = &self.config.tenants[tenant].metrics[descriptor];
        if d.kind != input.kind || d.unit != input.unit {
            return Err(E::InvalidName);
        }
        let mut labels = [u8::MAX; 8];
        let mut bytes = 0usize;
        for (key, value) in input.attributes {
            if !config::name(key) || key.len() > 32 || value.len() > 64 {
                return Err(E::InvalidName);
            }
            bytes += key.len() + value.len();
            if bytes > self.config.limits.maximum_label_bytes {
                return Err(E::BudgetExhausted);
            }
            let key_index = d
                .labels
                .iter()
                .position(|l| l.key == *key)
                .ok_or(E::InvalidName)?;
            if labels[key_index] != u8::MAX {
                return Err(E::InvalidName);
            }
            labels[key_index] = u8::try_from(
                d.labels[key_index]
                    .values
                    .iter()
                    .position(|v| v == value)
                    .ok_or(E::InvalidName)?,
            )
            .map_err(|_| E::InvalidName)?;
        }
        let hash = selection_digest(&self.digest, source, input.name, &labels);
        Ok(MetricSelection {
            tenant,
            descriptor,
            labels,
            digest: hash,
            value: input.value,
            owner: self.identity.clone(),
        })
    }
    pub fn try_emit(
        &self,
        source: CustomMetricSource<'_>,
        input: CustomMetricInput<'_>,
    ) -> Result<bool, E> {
        match self.inspect(source, input) {
            Ok(selected) => self.try_emit_selected(source, selected),
            Err(error) => {
                self.record_failure(error);
                Err(error)
            }
        }
    }
    pub fn try_emit_selected(
        &self,
        source: CustomMetricSource<'_>,
        selected: MetricSelection,
    ) -> Result<bool, E> {
        let result = self.emit_selected(source, &selected);
        if let Err(error) = &result {
            self.record_failure(*error);
        }
        result
    }
    fn emit_selected(
        &self,
        source: CustomMetricSource<'_>,
        selected: &MetricSelection,
    ) -> Result<bool, E> {
        self.live()?;
        if !Arc::ptr_eq(&self.identity, &selected.owner) {
            return Err(E::Unavailable);
        }
        let descriptor = &self.config.tenants[selected.tenant].metrics[selected.descriptor];
        if ![source.tenant, source.service, source.revision]
            .iter()
            .all(|s| config::token(s, 128))
            || selection_digest(&self.digest, source, &descriptor.name, &selected.labels)
                != selected.digest
        {
            return Err(E::Unavailable);
        }
        let mut state = self.state.try_lock().map_err(|_| E::BudgetExhausted)?;
        self.live()?;
        let now = self.clock.monotonic_now();
        if now.saturating_duration_since(state.window) >= Duration::from_secs(1) {
            state.window = now;
            state.observations = 0;
            state.tenant_observations = [0; 8];
        }
        let limits = self.config.limits;
        if state.observations >= limits.observations_per_second
            || state.tenant_observations[selected.tenant]
                >= limits.observations_per_tenant_per_second
        {
            return Err(E::BudgetExhausted);
        }
        let existing = state.series.iter().position(|s| s.key == selected.digest);
        if existing.is_none()
            && (state.series.len() >= limits.maximum_series
                || state.tenant_series[selected.tenant] >= limits.maximum_series_per_tenant)
        {
            return Err(E::BudgetExhausted);
        }
        let sequence = state.sequence.checked_add(1).ok_or(E::BudgetExhausted)?;
        let descriptor = &self.config.tenants[selected.tenant].metrics[selected.descriptor];
        let values = existing
            .map_or_else(Values::default, |index| state.series[index].values)
            .updated(descriptor, selected.value)?;
        // Slot and node/tenant bytes are reserved before any record allocation.
        let permit = self.handle.reserve_custom()?;
        let charge = self.queued.reserve(selected.tenant, limits)?;
        let point = sample(
            source,
            selected.value,
            descriptor,
            selected.labels,
            sequence,
            values,
            self.clock.sample().unix_millis(),
        );
        if point.retained_bytes() + size_of::<crate::TelemetryRecord>() > RECORD_BYTES {
            return Err(E::BudgetExhausted);
        }
        self.live()?;
        if let Some(index) = existing {
            state.series[index].values = values;
        } else {
            state.series.push(Series {
                key: selected.digest,
                values,
            });
            state.tenant_series[selected.tenant] += 1;
        }
        state.sequence = sequence;
        state.observations += 1;
        state.tenant_observations[selected.tenant] += 1;
        permit.send(crate::pipeline::PipelineCommand::CustomMetric(
            point, charge,
        ));
        self.handle.accepted_custom();
        increment(&self.accepted);
        Ok(true)
    }
    pub fn snapshot(&self) -> Result<CustomMetricSnapshot, E> {
        let state = self.state.try_lock().map_err(|_| E::Unavailable)?;
        Ok(CustomMetricSnapshot {
            active_series: state.series.len(),
            tenant_series: state.tenant_series,
            queued_bytes: self.queued.node.load(Ordering::Acquire),
            tenant_queued_bytes: std::array::from_fn(|i| {
                self.queued.tenants[i].load(Ordering::Acquire)
            }),
            accepted: self.accepted.load(Ordering::Relaxed),
            invalid: self.invalid.load(Ordering::Relaxed),
            exhausted: self.exhausted.load(Ordering::Relaxed),
            unavailable: self.unavailable.load(Ordering::Relaxed),
            retired: self.retired.load(Ordering::Acquire),
        })
    }
    fn record_failure(&self, error: E) {
        increment(match error {
            E::InvalidName => &self.invalid,
            E::BudgetExhausted => &self.exhausted,
            E::Unavailable => &self.unavailable,
        });
    }
}
fn increment(value: &AtomicU64) {
    let _ = value.fetch_update(Ordering::Relaxed, Ordering::Relaxed, |old| {
        Some(old.saturating_add(1))
    });
}
struct HashWriter(Sha256);
impl std::io::Write for HashWriter {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        self.0.update(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

fn sample(
    source: CustomMetricSource<'_>,
    value: f64,
    descriptor: &CustomMetricDescriptor,
    labels: [u8; 8],
    sequence: u64,
    values: Values,
    observed_at_unix_millis: u64,
) -> CustomMetricPoint {
    let mut attributes = Metadata::new();
    for (key, value) in [
        ("latent.tenant", source.tenant),
        ("latent.service", source.service),
        ("latent.revision", source.revision),
    ] {
        attributes.insert(key.into(), value.into());
    }
    for (index, label) in descriptor.labels.iter().enumerate() {
        if labels[index] != u8::MAX {
            attributes.insert(
                format!("guest.{}", label.key),
                label.values[usize::from(labels[index])].clone(),
            );
        }
    }
    CustomMetricPoint(Arc::new(Sample {
        point: MetricPoint {
            name: format!("latent.application.{}", descriptor.name),
            kind: descriptor.kind,
            value,
            unit: descriptor.unit.clone(),
            attributes,
            observed_at_unix_millis,
        },
        sequence,
        aggregation: values.export(descriptor),
    }))
}

fn selection_digest(
    config: &str,
    source: CustomMetricSource<'_>,
    name: &str,
    labels: &[u8; 8],
) -> [u8; 32] {
    let mut hash = Sha256::new();
    for part in [
        config.as_bytes(),
        source.tenant.as_bytes(),
        source.service.as_bytes(),
        source.revision.as_bytes(),
        name.as_bytes(),
        labels,
    ] {
        hash.update((part.len() as u64).to_le_bytes());
        hash.update(part);
    }
    hash.finalize().into()
}
