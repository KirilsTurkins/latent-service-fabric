use super::super::worker::Services;
use super::{
    EffectManagementAuthorization, EffectManagementOutcome, EffectManagementPhase,
    RetainedEffectManagement, RetainedEffectManagementJob, EFFECT_MANAGEMENT_WORK_BYTES,
    MAXIMUM_RETAINED_BYTES,
};
use crate::dispatch::{EffectRecord, RetryProof};
use crate::dispatch_store::{
    effect_management::{
        EffectManagementAction, EffectManagementCatalog, EffectManagementError as Error,
        EffectManagementEvidence, EffectManagementPlan, EffectManagementRequest,
    },
    effect_row_key,
};
use latent_core::{StateNamespaceId, TenantId};
use latent_state::embedded::{EmbeddedStore, FencedStoreError, ReadView, StoreError};
use latent_state::namespace::catalog::{NamespaceCatalog, NamespaceRead};
use latent_state::protected_store::ProtectedStoreError;
use latent_state::store_io::StoreIoKind;
use std::{
    sync::Arc,
    time::{Duration, Instant},
};

pub(super) fn submit<R: Send + 'static>(
    services: &Arc<Services>,
    authorization: Arc<dyn EffectManagementAuthorization>,
    bytes: u64,
    retained: R,
    complete: impl FnOnce(&Result<EffectManagementOutcome, Error>, &mut R) -> Result<(), StoreError>
        + Send
        + 'static,
    operation: impl FnOnce(&Services, &EmbeddedStore) -> Result<(EffectManagementOutcome, NamespaceRead), Error>
        + Send
        + 'static,
) -> Result<RetainedEffectManagementJob<R>, Error> {
    submit_kind(
        services,
        authorization,
        StoreIoKind::RecoveryWrite,
        bytes,
        retained,
        complete,
        operation,
    )
}
pub(super) fn submit_kind<R: Send + 'static>(
    services: &Arc<Services>,
    authorization: Arc<dyn EffectManagementAuthorization>,
    kind: StoreIoKind,
    bytes: u64,
    retained: R,
    complete: impl FnOnce(&Result<EffectManagementOutcome, Error>, &mut R) -> Result<(), StoreError>
        + Send
        + 'static,
    operation: impl FnOnce(&Services, &EmbeddedStore) -> Result<(EffectManagementOutcome, NamespaceRead), Error>
        + Send
        + 'static,
) -> Result<RetainedEffectManagementJob<R>, Error> {
    if bytes > MAXIMUM_RETAINED_BYTES {
        return Err(Error::Capacity);
    }
    let worker = Arc::clone(services);
    services
        .store
        .with_store_retaining(
            kind,
            bytes
                .checked_add(EFFECT_MANAGEMENT_WORK_BYTES)
                .ok_or(Error::Capacity)?,
            Arc::new(Arc::clone(&authorization)),
            move |store| {
                let mut retained = retained;
                let (outcome, namespace) = match operation(&worker, store) {
                    Ok((value, namespace)) => (Ok(value), Some(namespace)),
                    Err(error) => (Err(error), None),
                };
                complete(&outcome, &mut retained)?;
                match outcome {
                    Err(Error::Store(error)) => Err(error),
                    outcome => Ok(RetainedEffectManagement {
                        outcome,
                        namespace,
                        retained,
                        _authorization: authorization,
                    }),
                }
            },
        )
        .map_err(protected)
}

pub(super) fn check(
    authorization: &Arc<dyn EffectManagementAuthorization>,
    namespace: &NamespaceRead,
    phase: EffectManagementPhase,
    action: EffectManagementAction,
) -> Result<(), Error> {
    let mut calls = 0;
    authorization.with_current(namespace, phase, action, &mut || {
        calls += 1;
        Ok(())
    })?;
    if calls != 1 {
        return Err(Error::InvalidAuthorizationFence);
    }
    Ok(())
}
pub(super) fn namespace(
    view: &ReadView,
    request: &EffectManagementRequest,
) -> Result<NamespaceRead, Error> {
    let input = request.input();
    let read = NamespaceCatalog::read_in(
        view,
        &TenantId(input.actor_tenant.clone()),
        &StateNamespaceId(input.namespace.clone()),
    )
    .map_err(|error| match error {
        latent_state::namespace::NamespaceError::UnsupportedFormat => {
            Error::Store(StoreError::UnsupportedFormat)
        }
        _ => Error::Store(StoreError::Corrupt),
    })?
    .ok_or(Error::NotFound)?;
    if read.record().version.incarnation != input.incarnation {
        return Err(Error::PermissionDenied);
    }
    Ok(read)
}
pub(super) fn load_authority(
    view: &ReadView,
    plan: &EffectManagementPlan,
) -> Result<crate::authority::DurableEffectAuthority, Error> {
    let row = view
        .get(&effect_row_key(&plan.request().input().effect)?)?
        .ok_or(Error::NotFound)?;
    Ok(EffectRecord::decode(&row)?.authority()?)
}
pub(super) fn qualify(
    services: &Services,
    view: &ReadView,
    request: &EffectManagementRequest,
    time: crate::authority::EffectTime,
) -> Result<Option<RetryProof>, Error> {
    if request.input().action != EffectManagementAction::Redrive {
        return Ok(None);
    }
    let provider = EffectManagementCatalog::provider_request(view, request)?;
    let adapter = services
        .adapters
        .iter()
        .find(|adapter| adapter.profile() == provider.authority().profile());
    Ok(adapter.and_then(|adapter| adapter.qualify_redrive(&provider, time).ok()))
}
pub(super) fn evidence(
    services: &Services,
    view: &ReadView,
    plan: &EffectManagementPlan,
) -> Result<EffectManagementEvidence, Error> {
    match plan.request().input().action {
        EffectManagementAction::Terminate => Ok(EffectManagementEvidence::Administrator),
        EffectManagementAction::Redrive => match plan.safety() {
            crate::dispatch_store::effect_management::EffectManagementSafety::KnownNonexecution => Ok(EffectManagementEvidence::Retry(RetryProof::KnownNonexecution)),
            crate::dispatch_store::effect_management::EffectManagementSafety::QualifiedDeduplication { .. } => Ok(EffectManagementEvidence::Retry(qualify(services, view, plan.request(), services.time.observe())?.ok_or(Error::PermissionDenied)?)),
            _ => Err(Error::Invalid),
        },
        EffectManagementAction::Reconcile => Err(Error::Invalid),
    }
}
pub(super) struct MutationInputs {
    pub namespace: NamespaceRead,
    pub plan: EffectManagementPlan,
    pub evidence: EffectManagementEvidence,
}
pub(super) fn persist(
    services: &Services,
    store: &EmbeddedStore,
    view: &ReadView,
    inputs: MutationInputs,
    authorization: &Arc<dyn EffectManagementAuthorization>,
    owned: Option<&super::super::state::ActiveGuard>,
) -> Result<(EffectManagementOutcome, NamespaceRead), Error> {
    let MutationInputs {
        namespace,
        plan,
        evidence,
    } = inputs;
    let time = services.time.observe();
    let prepared =
        EffectManagementCatalog::prepare_mutation(view, services.epoch, plan, evidence, time)?;
    let authority = prepared.authority().clone();
    let (mut batch, receipt, replayed) = prepared.into_parts();
    batch.expectations.push(namespace.expectation());
    store
        .apply_fenced(batch, || {
            let current = services.time.observe();
            let deadline = expiration(receipt.plan(), current, replayed)?;
            role_fence(services, receipt.plan(), owned, replayed, || {
                let mut calls = 0;
                authorization.with_current(
                    &namespace,
                    EffectManagementPhase::Mutate,
                    receipt.plan().request().input().action,
                    &mut || {
                        calls += 1;
                        let _rules = if receipt.plan().request().input().action
                            == EffectManagementAction::Redrive
                            && !replayed
                        {
                            Some(
                                services.authority.retry_fence(
                                    &authority,
                                    receipt
                                        .plan()
                                        .original_attempt()
                                        .ok_or(Error::Invalid)?
                                        .attempt()
                                        .checked_add(1)
                                        .ok_or(Error::Capacity)?,
                                    receipt
                                        .completed_at_millis()
                                        .checked_add(
                                            receipt.plan().request().input().retry_delay_millis,
                                        )
                                        .ok_or(Error::Capacity)?,
                                    current,
                                )?,
                            )
                        } else {
                            None
                        };
                        live(authorization, deadline)
                    },
                )?;
                if calls != 1 {
                    return Err(Error::InvalidAuthorizationFence);
                }
                Ok(())
            })
        })
        .map_err(|error| fenced(&error))?;
    services.shared.notify.notify_one();
    Ok((
        EffectManagementOutcome::Mutation { receipt, replayed },
        namespace,
    ))
}
pub(super) fn role_fence(
    services: &Services,
    plan: &EffectManagementPlan,
    owned: Option<&super::super::state::ActiveGuard>,
    replayed: bool,
    accept: impl FnOnce() -> Result<(), Error>,
) -> Result<(), Error> {
    let state = services.shared.state.lock().map_err(|_| Error::Closed)?;
    if state.closed || state.failure.is_some() {
        return Err(Error::Closed);
    }
    if state.pending_control.is_some() {
        return Err(Error::RecoveryRequired);
    }
    if !replayed
        && plan.request().input().action == EffectManagementAction::Redrive
        && state.restore_review.is_required()
    {
        return Err(Error::RestoreReviewRequired);
    }
    if !replayed
        && !state.management_retired(&services.shared, &plan.request().input().effect, owned)
    {
        return Err(Error::PhysicalOwnerLive);
    }
    accept()
}
pub(super) fn expiration(
    plan: &EffectManagementPlan,
    time: crate::authority::EffectTime,
    replayed: bool,
) -> Result<Option<Instant>, Error> {
    if replayed {
        return Ok(None);
    }
    if !time.continuity_proven
        || time.unix_millis < plan.prepared_at_millis()
        || time.unix_millis >= plan.expires_at_millis()
    {
        return Err(Error::Authority(crate::authority::AuthorityError::Expired));
    }
    Ok(Some(
        Instant::now()
            .checked_add(Duration::from_millis(
                plan.expires_at_millis() - time.unix_millis,
            ))
            .ok_or(Error::Capacity)?,
    ))
}
pub(super) fn live(
    authorization: &Arc<dyn EffectManagementAuthorization>,
    deadline: Option<Instant>,
) -> Result<(), Error> {
    if Instant::now() >= authorization.original_deadline()
        || deadline.is_some_and(|deadline| Instant::now() >= deadline)
    {
        return Err(Error::Authority(crate::authority::AuthorityError::Expired));
    }
    let mut calls = 0;
    authorization.with_live(&mut || {
        calls += 1;
        Ok(())
    })?;
    if calls != 1 {
        return Err(Error::InvalidAuthorizationFence);
    }
    Ok(())
}
pub(super) fn fenced(error: &FencedStoreError<Error>) -> Error {
    match error {
        FencedStoreError::Store(error) => Error::Store(*error),
        FencedStoreError::Fence(error) => *error,
    }
}
pub(super) fn protected(error: ProtectedStoreError) -> Error {
    match error {
        ProtectedStoreError::Store(error) => Error::Store(error),
        ProtectedStoreError::CommitUncertain => Error::Store(StoreError::CommitUncertain),
        ProtectedStoreError::Io(error) => io(error),
        ProtectedStoreError::UnsafeRoot => Error::Store(StoreError::Unavailable),
        _ => Error::Invalid,
    }
}
pub(super) fn io(error: latent_state::store_io::StoreIoError) -> Error {
    use latent_state::store_io::StoreIoError as Io;
    match error {
        Io::AdmissionClosed | Io::NotStarted => Error::Closed,
        Io::QueueFull
        | Io::AcceptedFull
        | Io::ByteBudget
        | Io::JobTooLarge
        | Io::Exhausted
        | Io::DrainWaiterBusy => Error::Capacity,
        Io::InvalidLimits => Error::Invalid,
        _ => Error::RecoveryRequired,
    }
}
