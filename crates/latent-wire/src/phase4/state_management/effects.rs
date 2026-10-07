//! Authenticated manual effect plans on the installed dispatcher. Selectors,
//! native plans and row hashes carry data; actual retained owners supply access.
mod audit;
mod authorization;
mod execute;
mod input;
mod lookup;
mod projection;
mod response;

use super::{
    audit as state_audit, authorization as state_authorization, c, capacity, contract, denied,
    error, expired, invalid, io_error, missing, protected_error, recovery_bindings, unsupported,
    Arc, AuthenticatedInvocationContext, Inner, Instant, OwnedPhase4Response, PlatformError,
    PlatformErrorCode, StateManagementReservation,
};
use crate::management::ManagementDecision;
use latent_capabilities::namespace::CallerScope;
use latent_effects::dispatch_store::effect_management::{
    EffectManagementAction as Action, EffectManagementCatalog as Catalog,
    EffectManagementError as Error, EffectManagementInput, EffectManagementPlan as Plan,
    EffectManagementReceipt as Receipt, EffectManagementRequest as Request,
    EffectManagementSafety as Safety,
};
use latent_effects::runtime::{
    EffectManagementAuthorization, EffectManagementOutcome as Outcome,
    EffectManagementPhase as Phase,
};
use latent_policy::capability::OwnedPolicyDecision;
use latent_state::namespace::catalog::NamespaceRead;

pub(super) fn handles(request: &contract::Request) -> bool {
    match request {
        contract::Request::PlanEffectMutation(_) => true,
        contract::Request::MutateState(value) => value.effect_plan.is_some(),
        contract::Request::GetStateOperationReceipt(value) => value.original_effect_plan.is_some(),
        _ => false,
    }
}

struct Access {
    inner: Arc<Inner>,
    namespace: state_authorization::Access,
    principal: latent_core::InvocationPrincipal,
    caller: CallerScope,
    entity: Option<String>,
    node: Arc<dyn ManagementDecision>,
    data: OwnedPolicyDecision,
    actions: std::sync::OnceLock<Actions>,
    action: Action,
    deadline: Instant,
    // All target/policy/completion buffers retire before the original permit.
    permit: Arc<dyn StateManagementReservation>,
}
struct Actions {
    planning: Option<OwnedPolicyDecision>,
    mutation: OwnedPolicyDecision,
}

pub(super) async fn execute(
    inner: Arc<Inner>,
    context: AuthenticatedInvocationContext,
    request: contract::Request,
    namespace: state_authorization::Access,
    node: Arc<dyn ManagementDecision>,
    deadline: Instant,
    permit: Arc<dyn StateManagementReservation>,
) -> Result<OwnedPhase4Response, PlatformError> {
    execute::run(inner, context, request, namespace, node, deadline, permit).await
}

fn native(error_value: Error) -> PlatformError {
    use latent_effects::authority::AuthorityError as A;
    match error_value {
        Error::Invalid | Error::InvalidAuthorizationFence | Error::Authority(A::Invalid) => {
            invalid()
        }
        Error::Conflict => error(
            PlatformErrorCode::StateConflict,
            "effect-management-precondition-conflict",
        ),
        Error::Capacity | Error::Authority(A::Capacity) => capacity(),
        Error::NotFound => missing(),
        Error::PermissionDenied | Error::Authority(A::PolicyBlocked | A::Stale) => denied(),
        Error::Authority(A::Expired)
        | Error::Store(latent_state::embedded::StoreError::SnapshotExpired) => expired(),
        Error::Authority(A::UnsupportedFormat) => error(
            PlatformErrorCode::IncompatibleContract,
            "effect-management-format-unsupported",
        ),
        Error::RestoreReviewRequired => error(
            PlatformErrorCode::StateConflict,
            "effect-management-restore-review-required",
        ),
        Error::PhysicalOwnerLive => error(
            PlatformErrorCode::Unavailable,
            "effect-management-physical-owner-live",
        ),
        Error::Store(value) => super::namespace_error(match value {
            latent_state::embedded::StoreError::UnsupportedFormat => {
                latent_state::namespace::NamespaceError::UnsupportedFormat
            }
            latent_state::embedded::StoreError::Conflict => {
                latent_state::namespace::NamespaceError::Conflict
            }
            latent_state::embedded::StoreError::Capacity => {
                latent_state::namespace::NamespaceError::Capacity
            }
            latent_state::embedded::StoreError::SnapshotExpired => unreachable!("handled above"),
            latent_state::embedded::StoreError::Corrupt => {
                latent_state::namespace::NamespaceError::Corrupt
            }
            latent_state::embedded::StoreError::Invalid => {
                latent_state::namespace::NamespaceError::Invalid
            }
            latent_state::embedded::StoreError::CommitUncertain => {
                latent_state::namespace::NamespaceError::RecoveryRequired
            }
            latent_state::embedded::StoreError::Unavailable => {
                latent_state::namespace::NamespaceError::Unavailable
            }
        }),
        Error::Closed
        | Error::RecoveryRequired
        | Error::Authority(A::ClockDiscontinuity | A::Unavailable) => error(
            PlatformErrorCode::Unavailable,
            "effect-management-recovery-required",
        ),
    }
}
fn gate(error: &PlatformError) -> Error {
    match error.code {
        PlatformErrorCode::PermissionDenied | PlatformErrorCode::Unauthenticated => {
            Error::PermissionDenied
        }
        PlatformErrorCode::DeadlineExceeded | PlatformErrorCode::Cancelled => {
            Error::Authority(latent_effects::authority::AuthorityError::Expired)
        }
        PlatformErrorCode::ResourceExhausted => Error::Capacity,
        PlatformErrorCode::StateConflict => Error::Conflict,
        _ => Error::RecoveryRequired,
    }
}
