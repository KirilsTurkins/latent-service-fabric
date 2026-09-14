//! Shared identifiers, budgets, lifecycle values, identities, errors, and async types.

#![forbid(unsafe_code)]

pub mod budget;
pub mod clock;
pub mod deadline_diagnostic_observer;
pub mod deadline_wait_observer;
pub mod digest;
pub mod error;
pub mod host_profile;
pub mod identity;
pub mod ids;
pub mod lifecycle;
pub mod publication;

pub use budget::{
    ActivationBudget, BudgetCancellationProbe, BudgetConsumption, BudgetDimension, BudgetError,
    BudgetFinalization, BudgetProfile, BudgetReservation, BudgetReservationGroup,
    ChildBudgetDelegation, ChildBudgetOwner, ClockSample, DelegationLimits,
    DescendantBudgetSnapshot, EffectiveActivationBudget, EffectiveDeadline, IncomingDeadline,
    ResourceBudget, RuntimeMemoryReservation,
};
pub use clock::{ActivationClock, SystemActivationClock};
pub use deadline_diagnostic_observer::{
    DeadlineDiagnosticDecision, DeadlineDiagnosticIdentity, DeadlineDiagnosticObservation,
    DeadlineDiagnosticObserver, DeadlineDiagnosticRecord, DeadlineDiagnosticSnapshot,
    DeadlineDiagnosticToken,
};
pub use deadline_wait_observer::{DeadlineWaitGuard, DeadlineWaitObserver, DeadlineWaitSnapshot};
pub use digest::{ArtifactBlobDigest, DigestParseError, PackageDigest};
pub use error::{DeclaredError, ErrorDetail, PlatformError, PlatformErrorCode};
pub use host_profile::{
    HostAbiProfile, HostInterfaceBinding, HostInterfaceSpec, PHASE3_HOST_ABI_V1,
    PHASE3_HOST_ABI_V2, PHASE3_HOST_ABI_V3,
};
pub use identity::{InvocationPrincipal, PrincipalKind};
pub use ids::*;
pub use lifecycle::{ActivationPhase, ActivationTerminalState, CancelDisposition};
pub use publication::{PublicationId, PublicationIdParseError};

use std::future::Future;
use std::pin::Pin;

/// Heap-allocated asynchronous result used by object-safe architectural traits.
pub type BoxFuture<'a, T> = Pin<Box<dyn Future<Output = T> + Send + 'a>>;

/// Opaque binary payload crossing an architectural boundary.
pub type Payload = Vec<u8>;

/// Extensible key/value metadata carried across subsystem boundaries.
pub type Metadata = std::collections::BTreeMap<String, String>;
