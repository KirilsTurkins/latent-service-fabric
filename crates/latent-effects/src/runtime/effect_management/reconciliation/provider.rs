use super::super::super::{state::ActiveGuard, worker::Services};
use super::super::support::{expiration, protected, role_fence};
use super::super::{EffectManagementAuthorization, EffectManagementPhase as Phase};
use crate::authority::{AuthorityError, ProviderLookupAuthorization};
use crate::dispatch_store::effect_management::{
    EffectManagementAction, EffectManagementError as Error, EffectManagementPlan,
};
use crate::runtime::{ProviderReconciliationOutcome, ProviderReconciliationRequest};
use latent_state::namespace::catalog::NamespaceRead;
use std::sync::Arc;

struct LookupAuthorization {
    authorization: Arc<dyn EffectManagementAuthorization>,
    namespace: Arc<NamespaceRead>,
}
impl ProviderLookupAuthorization for LookupAuthorization {
    fn with_current(
        &self,
        accept: &mut dyn FnMut() -> Result<(), AuthorityError>,
    ) -> Result<(), AuthorityError> {
        let mut failure = None;
        self.authorization
            .with_current(
                &self.namespace,
                Phase::Mutate,
                EffectManagementAction::Reconcile,
                &mut || match accept() {
                    Ok(()) => Ok(()),
                    Err(error) => {
                        failure = Some(error);
                        Err(Error::Authority(error))
                    }
                },
            )
            .map_err(|error| failure.unwrap_or_else(|| authority(error)))
    }
    fn with_live(
        &self,
        accept: &mut dyn FnMut() -> Result<(), AuthorityError>,
    ) -> Result<(), AuthorityError> {
        let mut failure = None;
        self.authorization
            .with_live(&mut || match accept() {
                Ok(()) => Ok(()),
                Err(error) => {
                    failure = Some(error);
                    Err(Error::Authority(error))
                }
            })
            .map_err(|error| failure.unwrap_or_else(|| authority(error)))
    }
}
fn authority(error: Error) -> AuthorityError {
    match error {
        Error::Authority(error) => error,
        Error::Capacity => AuthorityError::Capacity,
        Error::Invalid | Error::InvalidAuthorizationFence => AuthorityError::Invalid,
        _ => AuthorityError::PolicyBlocked,
    }
}

pub(super) async fn lookup(
    services: &Services,
    plan: &EffectManagementPlan,
    authorization: &Arc<dyn EffectManagementAuthorization>,
    guard: &ActiveGuard,
    request: ProviderReconciliationRequest,
    namespace: Arc<NamespaceRead>,
) -> Result<ProviderReconciliationOutcome, Error> {
    authorization.before_lookup()?;
    let time = services.time.observe();
    let deadline = expiration(plan, time, false)?
        .ok_or(Error::Invalid)?
        .min(authorization.original_deadline());
    let adapter = services
        .adapters
        .iter()
        .find(|adapter| adapter.profile() == request.authority().profile())
        .ok_or(Error::Authority(AuthorityError::UnsupportedFormat))?;
    let pin = services
        .store
        .reserve_recovery_operation_retaining(Arc::new(Arc::clone(authorization)))
        .map_err(protected)?;
    let gate = Arc::new(LookupAuthorization {
        authorization: Arc::clone(authorization),
        namespace,
    });
    let mut context = match services.authority.accept_lookup(
        request.authority(),
        request.attempt().attempt(),
        time,
        deadline,
        gate,
    ) {
        Ok(context) => context,
        Err(error) => {
            pin.retire().await;
            return Err(error.into());
        }
    };
    if context
        .retain_owner(Arc::new(Arc::clone(authorization)))
        .is_err()
    {
        context.retire()?;
        pin.retire().await;
        return Err(Error::Invalid);
    }
    let original = request.authority().clone();
    let attempt = request.attempt().attempt();
    let mut accepted = None;
    let time = services.time.observe();
    let admission = role_fence(services, plan, Some(guard), false, || {
        accepted = Some(context.accept_with(&original, attempt, time, |grant| {
            adapter.accept_reconciliation(grant, request)
        })?);
        Ok(())
    });
    let result = match admission {
        Ok(()) => match accepted {
            Some(Ok(operation)) => Ok(operation.await),
            Some(Err(error)) => Err(error.into()),
            None => Err(Error::Invalid),
        },
        Err(error) => Err(error),
    };
    // The adapter returned only after native buffers/socket/provider cleanup.
    // Never release these owners at deadline expiry or management waiter drop.
    let retired = context.retire();
    pin.retire().await;
    retired?;
    result
}
