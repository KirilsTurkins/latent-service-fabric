//! Explicit lookup on the installed fixed recovery provider worker.
mod provider;

use super::super::{state::ActiveGuard, worker::Services};
use super::support::MutationInputs;
use super::support::{check, io, namespace, persist, protected};
use super::{
    EffectManagementAuthorization, EffectManagementOutcome as Outcome,
    EffectManagementPhase as Phase, RetainedEffectManagement, RetainedEffectManagementJob,
    EFFECT_MANAGEMENT_WORK_BYTES, MAXIMUM_RETAINED_BYTES,
};
use crate::dispatch_store::effect_management::{
    EffectManagementCatalog as Catalog, EffectManagementError as Error, EffectManagementEvidence,
    EffectManagementPlan,
};
use crate::runtime::{DispatcherManagementPort, ProviderReconciliationOutcome};
use latent_state::{
    embedded::StoreError, namespace::catalog::NamespaceRead, protected_store::ProtectedStoreError,
    store_io::StoreIoKind,
};
use std::sync::Arc;

enum Prepared {
    Known(Outcome, NamespaceRead),
    Lookup(
        crate::runtime::ProviderReconciliationRequest,
        Arc<NamespaceRead>,
    ),
}

pub(super) fn submit<R: Send + 'static>(
    port: &DispatcherManagementPort,
    plan: EffectManagementPlan,
    authorization: Arc<dyn EffectManagementAuthorization>,
    retained: R,
    bytes: u64,
    complete: impl FnOnce(&Result<Outcome, Error>, &mut R) -> Result<(), StoreError> + Send + 'static,
) -> Result<RetainedEffectManagementJob<R>, Error> {
    if bytes > MAXIMUM_RETAINED_BYTES {
        return Err(Error::Capacity);
    }
    authorization.before_lookup()?;
    let guard = port
        .services
        .shared
        .admit_management(
            &plan.request().input().actor_tenant,
            &plan.request().input().effect,
            &port.services.config,
        )
        .ok_or(Error::Capacity)?;
    let services = Arc::clone(&port.services);
    port.jobs
        .submit_retaining(
            StoreIoKind::RecoveryRead,
            bytes
                .checked_add(EFFECT_MANAGEMENT_WORK_BYTES)
                .ok_or(Error::Capacity)?,
            Arc::new(Arc::clone(&authorization)),
            move |_| {
                let mut guard = guard;
                guard.start();
                let guard = Arc::new(guard);
                let result =
                    services
                        .runtime
                        .block_on(execute(&services, plan, &authorization, &guard));
                let (outcome, namespace) = match result {
                    Ok((outcome, read)) => (Ok(outcome), Some(read)),
                    Err(error) => (Err(error), None),
                };
                // All normal paths awaited actual provider/pin cleanup. Panic leaves the
                // started guard quarantined, retaining any unretired context keeper.
                Arc::try_unwrap(guard)
                    .unwrap_or_else(|_| panic!("physical management guard retained after cleanup"))
                    .retire();
                let mut retained = retained;
                complete(&outcome, &mut retained).map_err(ProtectedStoreError::Store)?;
                match outcome {
                    Err(Error::Store(error)) => Err(ProtectedStoreError::Store(error)),
                    outcome => Ok(RetainedEffectManagement {
                        outcome,
                        namespace,
                        retained,
                        _authorization: authorization,
                    }),
                }
            },
        )
        .map_err(|error| io(error.reason))
}

async fn execute(
    services: &Arc<Services>,
    plan: EffectManagementPlan,
    authorization: &Arc<dyn EffectManagementAuthorization>,
    guard: &Arc<ActiveGuard>,
) -> Result<(Outcome, NamespaceRead), Error> {
    let worker_plan = plan.clone();
    let worker_authorization = Arc::clone(authorization);
    let prepared = native(
        services,
        StoreIoKind::RecoveryRead,
        authorization,
        move |store| {
            worker_authorization.before_lookup()?;
            let view = store.snapshot()?;
            let read = namespace(&view, worker_plan.request())?;
            check(
                &worker_authorization,
                &read,
                Phase::Read,
                worker_plan.request().input().action,
            )?;
            if let Some(receipt) = Catalog::lookup(&view, &worker_plan)? {
                return Ok(Prepared::Known(
                    Outcome::Mutation {
                        receipt,
                        replayed: true,
                    },
                    read,
                ));
            }
            let original = Catalog::plan_for_actor(
                &view,
                &worker_plan.request().input().actor_tenant,
                &worker_plan.request().input().actor_subject,
                &worker_plan.request().input().operation_id,
            )?
            .ok_or(Error::NotFound)?;
            if original != worker_plan {
                return Err(Error::Conflict);
            }
            check(
                &worker_authorization,
                &read,
                Phase::Mutate,
                worker_plan.request().input().action,
            )?;
            Ok(Prepared::Lookup(
                Catalog::provider_request(&view, worker_plan.request())?,
                Arc::new(read),
            ))
        },
    )
    .await?;
    let (request, read) = match prepared {
        Prepared::Known(outcome, read) => return Ok((outcome, read)),
        Prepared::Lookup(request, read) => (request, read),
    };
    let confirmation =
        provider::lookup(services, &plan, authorization, guard, request, read).await?;
    let worker = Arc::clone(services);
    let writer_authorization = Arc::clone(authorization);
    let writer_guard = Arc::clone(guard);
    native(
        services,
        StoreIoKind::RecoveryWrite,
        authorization,
        move |store| {
            writer_authorization.before_lookup()?;
            let view = store.snapshot()?;
            let read = namespace(&view, plan.request())?;
            match confirmation {
                ProviderReconciliationOutcome::Confirmed(confirmation) => persist(
                    &worker,
                    store,
                    &view,
                    MutationInputs {
                        namespace: read,
                        plan,
                        evidence: EffectManagementEvidence::Provider(confirmation),
                    },
                    &writer_authorization,
                    Some(&writer_guard),
                ),
                ProviderReconciliationOutcome::Uncertain(_) => Err(Error::RecoveryRequired),
            }
        },
    )
    .await
}

async fn native<T: Send + 'static>(
    services: &Services,
    kind: StoreIoKind,
    authorization: &Arc<dyn EffectManagementAuthorization>,
    action: impl FnOnce(&latent_state::embedded::EmbeddedStore) -> Result<T, Error> + Send + 'static,
) -> Result<T, Error> {
    let job = services
        .store
        .with_store_retaining(
            kind,
            EFFECT_MANAGEMENT_WORK_BYTES,
            Arc::new(Arc::clone(authorization)),
            move |store| match action(store) {
                Err(Error::Store(error)) => Err(error),
                result => Ok(result),
            },
        )
        .map_err(protected)?;
    job.await.map_err(io)?.map_err(protected)?
}
