use std::time::Duration;

use latent_core::{
    ArtifactBlobDigest, PackageDigest, PlatformError, PlatformErrorCode, ReleaseDigest, RevisionId,
    RouteGeneration, ServiceId, TenantId,
};

use super::error;

pub(super) const MAX_REVISIONS: usize = 8;
/// Fixed inclusive upper bounds; the ninth bucket contains larger durations.
pub const CANARY_LATENCY_UPPER_MICROS: [u64; 8] = [
    100, 1_000, 5_000, 10_000, 50_000, 100_000, 1_000_000, 10_000_000,
];

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CanaryWindowIdentity {
    pub tenant: TenantId,
    pub service: ServiceId,
    pub deployment: String,
    pub rollout_id: String,
    pub step: u64,
    pub generation: RouteGeneration,
}

/// Association supplied by the trusted control owner, never inferred from labels.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CanaryRevisionBinding {
    pub revision: RevisionId,
    pub component: ReleaseDigest,
    pub package: Option<PackageDigest>,
}

#[derive(Debug, Clone)]
pub struct CanaryWindowSpec {
    pub identity: CanaryWindowIdentity,
    /// Opaque exact catalog/rollout/policy binding supplied by the trusted owner.
    /// Absent for diagnostic windows that cannot authorize a catalog promotion.
    pub control_digest: Option<ArtifactBlobDigest>,
    pub revisions: Vec<CanaryRevisionBinding>,
    /// Membership starts when registration succeeds and lasts at most one hour.
    pub duration: Duration,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Phase2CanaryOutcomeWindowConfig {
    /// Includes retired windows still retained by samples or snapshots.
    pub maximum_series: usize,
    pub maximum_samples_per_series: usize,
    pub maximum_total_samples: usize,
    pub maximum_identity_bytes: usize,
    pub maximum_live_samples: usize,
    pub maximum_snapshot_owners: usize,
}

impl Default for Phase2CanaryOutcomeWindowConfig {
    fn default() -> Self {
        Self {
            maximum_series: 16,
            maximum_samples_per_series: 10_000,
            maximum_total_samples: 100_000,
            maximum_identity_bytes: 256,
            maximum_live_samples: 4_096,
            maximum_snapshot_owners: 4,
        }
    }
}

impl Phase2CanaryOutcomeWindowConfig {
    pub(super) fn validate(self) -> Result<(), PlatformError> {
        if self.maximum_series == 0
            || self.maximum_series > 64
            || self.maximum_samples_per_series == 0
            || self.maximum_samples_per_series > 1_000_000
            || self.maximum_total_samples == 0
            || self.maximum_total_samples > 16_000_000
            || self.maximum_identity_bytes == 0
            || self.maximum_identity_bytes > 1_024
            || self.maximum_live_samples == 0
            || self.maximum_live_samples > 65_536
            || self.maximum_snapshot_owners == 0
            || self.maximum_snapshot_owners > 16
        {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid-phase2-canary-window-limits",
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CanaryCoverage {
    Open,
    Draining,
    NoSamples,
    Insufficient,
    Incomplete,
    /// Complete observations only; never an authorization to promote.
    CompleteData,
}

impl CanaryCoverage {
    #[must_use]
    pub const fn metric_label(self) -> &'static str {
        match self {
            Self::Open => "open",
            Self::Draining => "draining",
            Self::NoSamples => "no_samples",
            Self::Insufficient => "insufficient",
            Self::Incomplete => "incomplete",
            Self::CompleteData => "complete_data",
        }
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Phase2CanaryWindowSnapshot {
    pub tracked_series: usize,
    pub total_samples: usize,
    pub live_samples: usize,
    pub snapshot_owners: usize,
    pub unattributed_loss_epoch: u64,
    pub loss_epoch_exhausted: bool,
}

pub(super) fn bounded_spec(
    spec: &CanaryWindowSpec,
    max: usize,
) -> Result<CanaryWindowSpec, PlatformError> {
    let id = &spec.identity;
    for value in [&id.tenant.0, &id.service.0, &id.deployment, &id.rollout_id] {
        identifier(value, max)?;
    }
    if spec.revisions.is_empty()
        || spec.revisions.len() > MAX_REVISIONS
        || spec.duration.is_zero()
        || spec.duration > Duration::from_hours(1)
    {
        return Err(error(
            PlatformErrorCode::InvalidArgument,
            "invalid-phase2-canary-window",
        ));
    }
    for (index, binding) in spec.revisions.iter().enumerate() {
        identifier(&binding.revision.0, max)?;
        let digest = binding.component.0.strip_prefix("sha256:").unwrap_or("");
        if digest.len() != 64
            || !digest
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
            || spec.revisions[..index]
                .iter()
                .any(|other| other.revision == binding.revision)
        {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid-phase2-canary-revision",
            ));
        }
    }
    Ok(CanaryWindowSpec {
        control_digest: spec.control_digest.clone(),
        identity: CanaryWindowIdentity {
            tenant: TenantId(fresh(&id.tenant.0)),
            service: ServiceId(fresh(&id.service.0)),
            deployment: fresh(&id.deployment),
            rollout_id: fresh(&id.rollout_id),
            step: id.step,
            generation: id.generation,
        },
        revisions: spec
            .revisions
            .iter()
            .map(|binding| CanaryRevisionBinding {
                revision: RevisionId(fresh(&binding.revision.0)),
                component: ReleaseDigest(fresh(&binding.component.0)),
                package: binding.package.clone(),
            })
            .collect(),
        duration: spec.duration,
    })
}

fn identifier(value: &str, max: usize) -> Result<(), PlatformError> {
    if value.is_empty() || value.len() > max || value.chars().any(char::is_control) {
        return Err(error(
            PlatformErrorCode::InvalidArgument,
            "invalid-phase2-canary-identity",
        ));
    }
    Ok(())
}

fn fresh(value: &str) -> String {
    Box::<str>::from(value).into_string()
}
