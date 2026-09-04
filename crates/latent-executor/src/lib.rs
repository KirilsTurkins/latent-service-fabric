//! Execution backend, preparation, cell, cancellation, and guest-outcome interfaces.

#![forbid(unsafe_code)]

use std::sync::Arc;

use latent_activation::ActivationEnvelope;
use latent_artifacts::CapsuleArtifact;
use latent_core::{
    ActivationId, BoxFuture, BudgetConsumption, BudgetDimension, CapabilityId, CellId,
    DeclaredError, Metadata, Payload, PlatformError, ReleaseDigest, ResourceBudget,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PreparationKey {
    pub release: ReleaseDigest,
    pub engine_version: String,
    pub engine_configuration_digest: String,
    pub target_triple: String,
    pub cpu_feature_set: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PreparedComponent {
    pub key: PreparationKey,
    pub backend: String,
    pub opaque_handle: String,
    pub metadata: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BoundImport {
    pub capability: CapabilityId,
    pub contract: String,
    pub opaque_handle: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExecutionCell {
    pub id: CellId,
    pub class: String,
    pub maximum_memory_bytes: u64,
    pub metadata: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExecutionRequest {
    pub activation: ActivationEnvelope,
    pub prepared: PreparedComponent,
    pub cell: ExecutionCell,
    pub imports: Vec<BoundImport>,
    pub budget: ResourceBudget,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GuestTrap {
    pub code: String,
    pub message: String,
    pub guest_backtrace: Vec<String>,
    pub metadata: Metadata,
}

/// Stable reason why non-cooperative guest execution was stopped.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GuestInterruptionKind {
    Cancelled,
    DeadlineExceeded,
    FuelExhausted,
    MemoryExhausted,
}

impl GuestInterruptionKind {
    /// Maps execution-enforced budget dimensions to their canonical guest
    /// interruption. Cooperative capability limits such as log bytes return
    /// `None` because the host call reports a typed budget-exhausted result
    /// without interrupting the guest.
    #[must_use]
    pub const fn for_budget_dimension(dimension: BudgetDimension) -> Option<Self> {
        match dimension {
            BudgetDimension::CpuFuel => Some(Self::FuelExhausted),
            BudgetDimension::MemoryBytes => Some(Self::MemoryExhausted),
            BudgetDimension::WallTime => Some(Self::DeadlineExceeded),
            BudgetDimension::ChildCalls
            | BudgetDimension::OutboundRequests
            | BudgetDimension::StateReadBytes
            | BudgetDimension::StateWriteBytes
            | BudgetDimension::BlobReadBytes
            | BudgetDimension::BlobWriteBytes
            | BudgetDimension::LogBytes
            | BudgetDimension::EffectCount => None,
            _ => None,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum GuestOutcome {
    Returned {
        output: Payload,
        output_media_type: String,
        consumption: BudgetConsumption,
    },
    /// A component-declared/domain failure returned through its typed contract
    /// result. It is intentionally distinct from successful output and from a
    /// platform failure, so an activation runner never has to infer it from a
    /// service-specific payload or media type.
    DeclaredError {
        error: DeclaredError,
        consumption: BudgetConsumption,
    },
    Trapped {
        trap: GuestTrap,
        consumption: BudgetConsumption,
    },
    Interrupted {
        kind: GuestInterruptionKind,
        reason: String,
        consumption: BudgetConsumption,
    },
}

/// Cloneable, `'static` cancellation view that a runtime may retain in a store.
///
/// The probe deliberately exposes no mutation. The activation runner owns the
/// cancellation state and the execution backend can only observe it from an
/// epoch callback or another non-cooperative interruption checkpoint.
pub trait ExecutionCancellationProbe: Send + Sync {
    fn is_cancelled(&self) -> bool;
    fn reason(&self) -> Option<String>;
}

pub trait ExecutionCancellation: Send + Sync {
    fn activation_id(&self) -> &ActivationId;
    fn is_cancelled(&self) -> bool;
    fn reason(&self) -> Option<String>;

    /// Returns a live cancellation view suitable for a runtime-owned callback.
    ///
    /// Legacy handles remain source-compatible. They are still checked before
    /// invocation, but cannot interrupt a running guest unless they expose a
    /// probe.
    fn probe(&self) -> Option<Arc<dyn ExecutionCancellationProbe>> {
        None
    }
}

/// Backend proof describing whether the generic cell can be reused.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ExecutionCleanup {
    Reusable,
    Quarantine { reason: String },
}

/// Invocation result plus the backend's cleanup proof.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExecutionReport {
    pub outcome: Result<GuestOutcome, PlatformError>,
    pub cleanup: ExecutionCleanup,
}

impl ExecutionReport {
    #[must_use]
    pub fn reusable(outcome: Result<GuestOutcome, PlatformError>) -> Self {
        Self {
            outcome,
            cleanup: ExecutionCleanup::Reusable,
        }
    }

    #[must_use]
    pub fn quarantine(
        outcome: Result<GuestOutcome, PlatformError>,
        reason: impl Into<String>,
    ) -> Self {
        Self {
            outcome,
            cleanup: ExecutionCleanup::Quarantine {
                reason: reason.into(),
            },
        }
    }
}

pub trait ExecutionBackend: Send + Sync {
    fn backend_id(&self) -> &str;

    fn prepare<'a>(
        &'a self,
        artifact: &'a CapsuleArtifact,
        key: &'a PreparationKey,
    ) -> BoxFuture<'a, Result<PreparedComponent, PlatformError>>;

    fn invoke<'a>(
        &'a self,
        request: ExecutionRequest,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, Result<GuestOutcome, PlatformError>>;

    /// Invokes the guest and returns explicit cell-reuse evidence.
    ///
    /// Backends that do not override this method are conservatively treated as
    /// unable to prove safe reuse. This prevents a new orchestrator from silently
    /// returning a potentially contaminated cell merely because it is wrapping a
    /// legacy backend.
    fn invoke_contained<'a>(
        &'a self,
        request: ExecutionRequest,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, ExecutionReport> {
        Box::pin(async move {
            ExecutionReport::quarantine(
                self.invoke(request, cancellation).await,
                "execution backend did not provide a cleanup proof",
            )
        })
    }

    fn release<'a>(
        &'a self,
        prepared: PreparedComponent,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;
}

pub trait ExecutionBackendRegistry: Send + Sync {
    fn get(&self, backend_id: &str) -> Option<&dyn ExecutionBackend>;
    fn list(&self) -> Vec<String>;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn budget_dimensions_have_deterministic_interruption_mappings() {
        assert_eq!(
            GuestInterruptionKind::for_budget_dimension(BudgetDimension::CpuFuel),
            Some(GuestInterruptionKind::FuelExhausted)
        );
        assert_eq!(
            GuestInterruptionKind::for_budget_dimension(BudgetDimension::MemoryBytes),
            Some(GuestInterruptionKind::MemoryExhausted)
        );
        assert_eq!(
            GuestInterruptionKind::for_budget_dimension(BudgetDimension::WallTime),
            Some(GuestInterruptionKind::DeadlineExceeded)
        );
        assert_eq!(
            GuestInterruptionKind::for_budget_dimension(BudgetDimension::LogBytes),
            None
        );
    }
}
