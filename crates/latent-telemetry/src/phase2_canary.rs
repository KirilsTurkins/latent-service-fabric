use std::collections::BTreeMap;
use std::sync::{Mutex, MutexGuard};

use latent_core::{
    PlatformError, PlatformErrorCode, RevisionId, RouteGeneration, ServiceId, TenantId,
};

const MAX_PHASE2_CANARY_SERIES: usize = 4_096;
const MAX_PHASE2_CANARY_SAMPLES_PER_SERIES: usize = 1_000_000;
const MAX_PHASE2_CANARY_TOTAL_SAMPLES: usize = 16_000_000;
const MAX_PHASE2_CANARY_IDENTITY_BYTES: usize = 1_024;
const MAX_PHASE2_CANARY_RETAINED_IDENTITY_BYTES: usize = 8 * 1024 * 1024;
const CANARY_IDENTITY_STRING_FIELDS: usize = 4;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Phase2CanaryOutcomeClass {
    Success,
    DomainError,
    PlatformError,
    DeadlineExceeded,
    Cancelled,
}

impl Phase2CanaryOutcomeClass {
    #[must_use]
    pub const fn metric_label(self) -> &'static str {
        match self {
            Self::Success => "success",
            Self::DomainError => "domain_error",
            Self::PlatformError => "platform_error",
            Self::DeadlineExceeded => "deadline_exceeded",
            Self::Cancelled => "cancelled",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Phase2CanaryOutcomeIdentity {
    pub tenant: TenantId,
    pub service: ServiceId,
    pub rollout_id: String,
    pub revision: RevisionId,
    pub generation: RouteGeneration,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Phase2CanaryOutcomeObservation {
    pub identity: Phase2CanaryOutcomeIdentity,
    pub outcome: Phase2CanaryOutcomeClass,
    pub observed_at_unix_millis: u64,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Phase2CanaryOutcomeCounters {
    pub success: u64,
    pub domain_error: u64,
    pub platform_error: u64,
    pub deadline_exceeded: u64,
    pub cancelled: u64,
}

impl Phase2CanaryOutcomeCounters {
    #[must_use]
    pub const fn total(self) -> u64 {
        self.success
            + self.domain_error
            + self.platform_error
            + self.deadline_exceeded
            + self.cancelled
    }

    fn record(&mut self, outcome: Phase2CanaryOutcomeClass) -> Result<(), PlatformError> {
        let counter = match outcome {
            Phase2CanaryOutcomeClass::Success => &mut self.success,
            Phase2CanaryOutcomeClass::DomainError => &mut self.domain_error,
            Phase2CanaryOutcomeClass::PlatformError => &mut self.platform_error,
            Phase2CanaryOutcomeClass::DeadlineExceeded => &mut self.deadline_exceeded,
            Phase2CanaryOutcomeClass::Cancelled => &mut self.cancelled,
        };
        *counter = counter.checked_add(1).ok_or_else(|| {
            error(
                PlatformErrorCode::ResourceExhausted,
                "phase2-canary-counter-exhausted",
            )
        })?;
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Phase2CanaryCoverage {
    NoSamples,
    Insufficient { observed: usize, required: usize },
    Ready { observed: usize, required: usize },
}

impl Phase2CanaryCoverage {
    #[must_use]
    pub const fn metric_label(self) -> &'static str {
        match self {
            Self::NoSamples => "no_samples",
            Self::Insufficient { .. } => "insufficient",
            Self::Ready { .. } => "ready",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Phase2CanaryOutcomeSnapshot {
    pub identity: Phase2CanaryOutcomeIdentity,
    pub counters: Phase2CanaryOutcomeCounters,
    pub first_observed_at_unix_millis: Option<u64>,
    pub last_observed_at_unix_millis: Option<u64>,
    pub coverage: Phase2CanaryCoverage,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Phase2CanaryOutcomeWindowConfig {
    pub maximum_series: usize,
    pub maximum_samples_per_series: usize,
    pub maximum_total_samples: usize,
    pub maximum_identity_bytes: usize,
}

impl Default for Phase2CanaryOutcomeWindowConfig {
    fn default() -> Self {
        Self {
            maximum_series: 256,
            maximum_samples_per_series: 10_000,
            maximum_total_samples: 100_000,
            maximum_identity_bytes: 256,
        }
    }
}

impl Phase2CanaryOutcomeWindowConfig {
    fn validate(self) -> Result<(), PlatformError> {
        if self.maximum_series == 0
            || self.maximum_series > MAX_PHASE2_CANARY_SERIES
            || self.maximum_samples_per_series == 0
            || self.maximum_samples_per_series > MAX_PHASE2_CANARY_SAMPLES_PER_SERIES
            || self.maximum_total_samples == 0
            || self.maximum_total_samples > MAX_PHASE2_CANARY_TOTAL_SAMPLES
            || self.maximum_identity_bytes == 0
            || self.maximum_identity_bytes > MAX_PHASE2_CANARY_IDENTITY_BYTES
        {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid-phase2-canary-window-limits",
            ));
        }
        let retained_identity_budget = self
            .maximum_series
            .checked_mul(CANARY_IDENTITY_STRING_FIELDS)
            .and_then(|fields| fields.checked_mul(self.maximum_identity_bytes))
            .ok_or_else(|| {
                error(
                    PlatformErrorCode::InvalidArgument,
                    "invalid-phase2-canary-window-limits",
                )
            })?;
        if retained_identity_budget > MAX_PHASE2_CANARY_RETAINED_IDENTITY_BYTES {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid-phase2-canary-window-limits",
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Phase2CanaryWindowSnapshot {
    pub tracked_series: usize,
    pub total_samples: usize,
    pub maximum_series: usize,
    pub maximum_total_samples: usize,
}

#[derive(Debug)]
pub struct BoundedPhase2CanaryOutcomeWindow {
    config: Phase2CanaryOutcomeWindowConfig,
    state: Mutex<WindowState>,
}

#[derive(Debug, Default)]
struct WindowState {
    series: BTreeMap<SeriesKey, SeriesState>,
    total_samples: usize,
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
struct SeriesKey {
    tenant: TenantId,
    service: ServiceId,
    rollout_id: String,
    revision: RevisionId,
    generation: RouteGeneration,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
struct SeriesState {
    counters: Phase2CanaryOutcomeCounters,
    samples: usize,
    first_observed_at_unix_millis: Option<u64>,
    last_observed_at_unix_millis: Option<u64>,
}

impl BoundedPhase2CanaryOutcomeWindow {
    pub fn new(config: Phase2CanaryOutcomeWindowConfig) -> Result<Self, PlatformError> {
        config.validate()?;
        Ok(Self {
            config,
            state: Mutex::new(WindowState::default()),
        })
    }

    pub fn record(
        &self,
        observation: &Phase2CanaryOutcomeObservation,
    ) -> Result<(), PlatformError> {
        let key = bounded_key(&observation.identity, self.config.maximum_identity_bytes)?;
        let mut state = self.lock_state()?;
        if state.total_samples >= self.config.maximum_total_samples {
            return Err(error(
                PlatformErrorCode::ResourceExhausted,
                "phase2-canary-total-sample-capacity-exhausted",
            ));
        }
        if !state.series.contains_key(&key) && state.series.len() >= self.config.maximum_series {
            return Err(error(
                PlatformErrorCode::ResourceExhausted,
                "phase2-canary-series-capacity-exhausted",
            ));
        }

        let series = state.series.entry(key).or_default();
        if series.samples >= self.config.maximum_samples_per_series {
            return Err(error(
                PlatformErrorCode::ResourceExhausted,
                "phase2-canary-series-sample-capacity-exhausted",
            ));
        }
        series.counters.record(observation.outcome)?;
        series.samples = series.samples.checked_add(1).ok_or_else(|| {
            error(
                PlatformErrorCode::ResourceExhausted,
                "phase2-canary-series-sample-capacity-exhausted",
            )
        })?;
        series.first_observed_at_unix_millis = Some(
            series
                .first_observed_at_unix_millis
                .map_or(observation.observed_at_unix_millis, |value| {
                    value.min(observation.observed_at_unix_millis)
                }),
        );
        series.last_observed_at_unix_millis = Some(
            series
                .last_observed_at_unix_millis
                .map_or(observation.observed_at_unix_millis, |value| {
                    value.max(observation.observed_at_unix_millis)
                }),
        );
        state.total_samples = state.total_samples.checked_add(1).ok_or_else(|| {
            error(
                PlatformErrorCode::ResourceExhausted,
                "phase2-canary-total-sample-capacity-exhausted",
            )
        })?;
        Ok(())
    }

    /// Returns outcomes only for a caller-authorized tenant. The identity is an
    /// attribution key, not an authorization capability. Missing observations
    /// return `NoSamples` rather than being interpreted as success.
    pub fn snapshot_tenant(
        &self,
        tenant: &TenantId,
        identity: &Phase2CanaryOutcomeIdentity,
        required_samples: usize,
    ) -> Result<Phase2CanaryOutcomeSnapshot, PlatformError> {
        if required_samples == 0 || required_samples > self.config.maximum_samples_per_series {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid-phase2-canary-required-samples",
            ));
        }
        if tenant != &identity.tenant {
            return Err(error(
                PlatformErrorCode::PermissionDenied,
                "phase2-canary-tenant-mismatch",
            ));
        }
        let key = bounded_key(identity, self.config.maximum_identity_bytes)?;
        let state = self.lock_state()?;
        let series = state.series.get(&key).copied().unwrap_or_default();
        let coverage = if series.samples == 0 {
            Phase2CanaryCoverage::NoSamples
        } else if series.samples < required_samples {
            Phase2CanaryCoverage::Insufficient {
                observed: series.samples,
                required: required_samples,
            }
        } else {
            Phase2CanaryCoverage::Ready {
                observed: series.samples,
                required: required_samples,
            }
        };
        Ok(Phase2CanaryOutcomeSnapshot {
            identity: identity_from_key(&key),
            counters: series.counters,
            first_observed_at_unix_millis: series.first_observed_at_unix_millis,
            last_observed_at_unix_millis: series.last_observed_at_unix_millis,
            coverage,
        })
    }

    pub fn snapshot(&self) -> Result<Phase2CanaryWindowSnapshot, PlatformError> {
        let state = self.lock_state()?;
        Ok(Phase2CanaryWindowSnapshot {
            tracked_series: state.series.len(),
            total_samples: state.total_samples,
            maximum_series: self.config.maximum_series,
            maximum_total_samples: self.config.maximum_total_samples,
        })
    }

    fn lock_state(&self) -> Result<MutexGuard<'_, WindowState>, PlatformError> {
        self.state.lock().map_err(|_| {
            error(
                PlatformErrorCode::Internal,
                "phase2-canary-outcome-window-poisoned",
            )
        })
    }
}

fn bounded_key(
    identity: &Phase2CanaryOutcomeIdentity,
    maximum_identity_bytes: usize,
) -> Result<SeriesKey, PlatformError> {
    validate_identity(
        &identity.tenant.0,
        maximum_identity_bytes,
        "invalid-phase2-canary-tenant",
    )?;
    validate_identity(
        &identity.service.0,
        maximum_identity_bytes,
        "invalid-phase2-canary-service",
    )?;
    validate_identity(
        &identity.rollout_id,
        maximum_identity_bytes,
        "invalid-phase2-canary-rollout",
    )?;
    validate_identity(
        &identity.revision.0,
        maximum_identity_bytes,
        "invalid-phase2-canary-revision",
    )?;
    Ok(SeriesKey {
        tenant: TenantId(fresh_string(&identity.tenant.0)),
        service: ServiceId(fresh_string(&identity.service.0)),
        rollout_id: fresh_string(&identity.rollout_id),
        revision: RevisionId(fresh_string(&identity.revision.0)),
        generation: identity.generation,
    })
}

fn identity_from_key(key: &SeriesKey) -> Phase2CanaryOutcomeIdentity {
    Phase2CanaryOutcomeIdentity {
        tenant: TenantId(fresh_string(&key.tenant.0)),
        service: ServiceId(fresh_string(&key.service.0)),
        rollout_id: fresh_string(&key.rollout_id),
        revision: RevisionId(fresh_string(&key.revision.0)),
        generation: key.generation,
    }
}

fn validate_identity(
    value: &str,
    maximum_identity_bytes: usize,
    message: &'static str,
) -> Result<(), PlatformError> {
    if value.is_empty() || value.len() > maximum_identity_bytes {
        return Err(error(PlatformErrorCode::InvalidArgument, message));
    }
    Ok(())
}

fn fresh_string(value: &str) -> String {
    Box::<str>::from(value).into_string()
}

fn error(code: PlatformErrorCode, message: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}

#[cfg(test)]
mod tests {
    use latent_core::{PlatformErrorCode, RevisionId, RouteGeneration, ServiceId, TenantId};

    use super::{
        BoundedPhase2CanaryOutcomeWindow, Phase2CanaryCoverage, Phase2CanaryOutcomeClass,
        Phase2CanaryOutcomeIdentity, Phase2CanaryOutcomeObservation,
        Phase2CanaryOutcomeWindowConfig,
    };

    fn identity(rollout: &str) -> Phase2CanaryOutcomeIdentity {
        Phase2CanaryOutcomeIdentity {
            tenant: TenantId("tenant-a".to_owned()),
            service: ServiceId("service-a".to_owned()),
            rollout_id: rollout.to_owned(),
            revision: RevisionId("revision-a".to_owned()),
            generation: RouteGeneration(17),
        }
    }

    fn observation(
        rollout: &str,
        outcome: Phase2CanaryOutcomeClass,
        observed_at_unix_millis: u64,
    ) -> Phase2CanaryOutcomeObservation {
        Phase2CanaryOutcomeObservation {
            identity: identity(rollout),
            outcome,
            observed_at_unix_millis,
        }
    }

    #[test]
    fn missing_samples_are_explicit_and_never_ready() {
        let window =
            BoundedPhase2CanaryOutcomeWindow::new(Phase2CanaryOutcomeWindowConfig::default())
                .unwrap();
        let identity = identity("rollout-a");
        let snapshot = window
            .snapshot_tenant(&identity.tenant, &identity, 3)
            .unwrap();
        assert_eq!(snapshot.coverage, Phase2CanaryCoverage::NoSamples);
        assert_eq!(snapshot.counters.total(), 0);
    }

    #[test]
    fn attributed_outcomes_require_the_configured_sample_count() {
        let window =
            BoundedPhase2CanaryOutcomeWindow::new(Phase2CanaryOutcomeWindowConfig::default())
                .unwrap();
        window
            .record(&observation(
                "rollout-a",
                Phase2CanaryOutcomeClass::Success,
                30,
            ))
            .unwrap();
        window
            .record(&observation(
                "rollout-a",
                Phase2CanaryOutcomeClass::DeadlineExceeded,
                10,
            ))
            .unwrap();
        let identity = identity("rollout-a");
        let partial = window
            .snapshot_tenant(&identity.tenant, &identity, 3)
            .unwrap();
        assert_eq!(
            partial.coverage,
            Phase2CanaryCoverage::Insufficient {
                observed: 2,
                required: 3
            }
        );
        window
            .record(&observation(
                "rollout-a",
                Phase2CanaryOutcomeClass::DomainError,
                20,
            ))
            .unwrap();
        let ready = window
            .snapshot_tenant(&identity.tenant, &identity, 3)
            .unwrap();
        assert_eq!(
            ready.coverage,
            Phase2CanaryCoverage::Ready {
                observed: 3,
                required: 3
            }
        );
        assert_eq!(ready.counters.success, 1);
        assert_eq!(ready.counters.deadline_exceeded, 1);
        assert_eq!(ready.counters.domain_error, 1);
        assert_eq!(ready.first_observed_at_unix_millis, Some(10));
        assert_eq!(ready.last_observed_at_unix_millis, Some(30));
    }

    #[test]
    fn tenant_scope_is_required_for_queries() {
        let window =
            BoundedPhase2CanaryOutcomeWindow::new(Phase2CanaryOutcomeWindowConfig::default())
                .unwrap();
        let identity = identity("rollout-a");
        let error = window
            .snapshot_tenant(&TenantId("tenant-b".to_owned()), &identity, 1)
            .unwrap_err();
        assert_eq!(error.code, PlatformErrorCode::PermissionDenied);
    }

    #[test]
    fn every_retained_identity_is_bounded_and_freshly_owned() {
        let config = Phase2CanaryOutcomeWindowConfig {
            maximum_identity_bytes: 16,
            ..Phase2CanaryOutcomeWindowConfig::default()
        };
        let window = BoundedPhase2CanaryOutcomeWindow::new(config).unwrap();
        for field in ["tenant", "service", "rollout", "revision"] {
            let mut identity = identity("rollout-a");
            let oversized = "x".repeat(17);
            match field {
                "tenant" => identity.tenant = TenantId(oversized),
                "service" => identity.service = ServiceId(oversized),
                "rollout" => identity.rollout_id = oversized,
                "revision" => identity.revision = RevisionId(oversized),
                _ => unreachable!(),
            }
            let error = window
                .record(&Phase2CanaryOutcomeObservation {
                    identity,
                    outcome: Phase2CanaryOutcomeClass::Success,
                    observed_at_unix_millis: 1,
                })
                .unwrap_err();
            assert_eq!(error.code, PlatformErrorCode::InvalidArgument);
        }

        let mut rollout = String::with_capacity(16_384);
        rollout.push_str("rollout-b");
        let mut identity = identity("rollout-b");
        identity.rollout_id = rollout;
        window
            .record(&Phase2CanaryOutcomeObservation {
                identity: identity.clone(),
                outcome: Phase2CanaryOutcomeClass::Success,
                observed_at_unix_millis: 1,
            })
            .unwrap();
        let snapshot = window
            .snapshot_tenant(&identity.tenant, &identity, 1)
            .unwrap();
        assert!(snapshot.identity.rollout_id.capacity() <= 16);
    }

    #[test]
    fn series_and_sample_capacity_fail_closed() {
        let config = Phase2CanaryOutcomeWindowConfig {
            maximum_series: 2,
            maximum_samples_per_series: 2,
            maximum_total_samples: 3,
            maximum_identity_bytes: 64,
        };
        let window = BoundedPhase2CanaryOutcomeWindow::new(config).unwrap();
        window
            .record(&observation(
                "rollout-a",
                Phase2CanaryOutcomeClass::Success,
                1,
            ))
            .unwrap();
        window
            .record(&observation(
                "rollout-a",
                Phase2CanaryOutcomeClass::Success,
                2,
            ))
            .unwrap();
        let error = window
            .record(&observation(
                "rollout-a",
                Phase2CanaryOutcomeClass::Success,
                3,
            ))
            .unwrap_err();
        assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);

        window
            .record(&observation(
                "rollout-b",
                Phase2CanaryOutcomeClass::Success,
                3,
            ))
            .unwrap();
        let error = window
            .record(&observation(
                "rollout-c",
                Phase2CanaryOutcomeClass::Success,
                4,
            ))
            .unwrap_err();
        assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
        let snapshot = window.snapshot().unwrap();
        assert_eq!(snapshot.tracked_series, 2);
        assert_eq!(snapshot.total_samples, 3);
    }

    #[test]
    fn excessive_configuration_is_rejected_without_allocation() {
        let error = BoundedPhase2CanaryOutcomeWindow::new(Phase2CanaryOutcomeWindowConfig {
            maximum_series: usize::MAX,
            ..Phase2CanaryOutcomeWindowConfig::default()
        })
        .unwrap_err();
        assert_eq!(error.code, PlatformErrorCode::InvalidArgument);

        let error = BoundedPhase2CanaryOutcomeWindow::new(Phase2CanaryOutcomeWindowConfig {
            maximum_identity_bytes: 1_024,
            maximum_series: 4_096,
            ..Phase2CanaryOutcomeWindowConfig::default()
        })
        .unwrap_err();
        assert_eq!(error.code, PlatformErrorCode::InvalidArgument);
    }

    #[test]
    fn zero_or_unreachable_required_sample_counts_are_rejected() {
        let config = Phase2CanaryOutcomeWindowConfig {
            maximum_samples_per_series: 2,
            ..Phase2CanaryOutcomeWindowConfig::default()
        };
        let window = BoundedPhase2CanaryOutcomeWindow::new(config).unwrap();
        let identity = identity("rollout-a");
        for required in [0, 3] {
            let error = window
                .snapshot_tenant(&identity.tenant, &identity, required)
                .unwrap_err();
            assert_eq!(error.code, PlatformErrorCode::InvalidArgument);
        }
    }

    #[test]
    fn exported_dimension_labels_are_fixed_enumerations() {
        assert_eq!(Phase2CanaryOutcomeClass::Success.metric_label(), "success");
        assert_eq!(
            Phase2CanaryOutcomeClass::PlatformError.metric_label(),
            "platform_error"
        );
        assert_eq!(Phase2CanaryCoverage::NoSamples.metric_label(), "no_samples");
        assert_eq!(
            Phase2CanaryCoverage::Ready {
                observed: 1,
                required: 1
            }
            .metric_label(),
            "ready"
        );
    }
}
