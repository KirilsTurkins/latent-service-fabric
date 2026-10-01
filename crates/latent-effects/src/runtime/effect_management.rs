//! Approved management jobs on the installed dispatcher and shared engine.
//! The authenticated adapter owns policy/audit; this port owns real native
//! submission, original effect rules and physical provider retirement.
use std::{sync::Arc, time::Instant};
mod reconciliation;
mod support;
use support::MutationInputs;
use support::{
    check, evidence, expiration, fenced, live, load_authority, namespace, persist, qualify,
    role_fence, submit, submit_kind,
};

use latent_state::embedded::StoreError;
use latent_state::namespace::catalog::NamespaceRead;
use latent_state::protected_store::ProtectedStoreError;
use latent_state::store_io::{StoreIoJob, StoreIoKind};

use super::management::DispatcherManagementPort;
use crate::dispatch_store::effect_management::{
    EffectManagementAction, EffectManagementCatalog, EffectManagementError as Error,
    EffectManagementPlan, EffectManagementReceipt, EffectManagementRequest,
};

pub const EFFECT_MANAGEMENT_WORK_BYTES: u64 = 3 * 1024 * 1024;
const MAXIMUM_RETAINED_BYTES: u64 = 512 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EffectManagementPhase {
    Plan,
    Mutate,
    Read,
}

/// Trusted host implementation retains the actual original node/operator,
/// publication, state/data-read and native request owners. These callbacks are
/// short bookkeeping fences; no I/O, audit flush, guest execution or await.
/// The final order is dispatcher role -> policy -> namespace -> effects -> native.
pub trait EffectManagementAuthorization: Send + Sync {
    fn before_lookup(&self) -> Result<(), Error>;
    fn original_deadline(&self) -> Instant;
    fn with_current(
        &self,
        namespace: &NamespaceRead,
        phase: EffectManagementPhase,
        action: EffectManagementAction,
        accept: &mut dyn FnMut() -> Result<(), Error>,
    ) -> Result<(), Error>;
    fn with_live(&self, accept: &mut dyn FnMut() -> Result<(), Error>) -> Result<(), Error>;
}

pub enum EffectManagementOutcome {
    Plan {
        plan: EffectManagementPlan,
        replayed: bool,
    },
    Mutation {
        receipt: EffectManagementReceipt,
        replayed: bool,
    },
    Receipt(Option<EffectManagementReceipt>),
}
/// Unclaimed completion values and typed audit finish retire before the same
/// original request reservation. Dropping the waiter does not cancel a worker.
pub struct RetainedEffectManagement<R> {
    pub outcome: Result<EffectManagementOutcome, Error>,
    pub namespace: Option<NamespaceRead>,
    pub retained: R,
    _authorization: Arc<dyn EffectManagementAuthorization>,
}
pub type RetainedEffectManagementJob<R> =
    StoreIoJob<Result<RetainedEffectManagement<R>, ProtectedStoreError>>;

impl DispatcherManagementPort {
    pub fn plan_effect_retained<R: Send + 'static>(
        &self,
        request: EffectManagementRequest,
        authorization: Arc<dyn EffectManagementAuthorization>,
        retained: R,
        retained_bytes: u64,
        complete: impl FnOnce(&Result<EffectManagementOutcome, Error>, &mut R) -> Result<(), StoreError>
            + Send
            + 'static,
    ) -> Result<RetainedEffectManagementJob<R>, Error> {
        submit(
            &self.services,
            Arc::clone(&authorization),
            retained_bytes,
            retained,
            complete,
            move |services, store| {
                authorization.before_lookup()?;
                let view = store.snapshot()?;
                let namespace = namespace(&view, &request)?;
                check(
                    &authorization,
                    &namespace,
                    EffectManagementPhase::Plan,
                    request.input().action,
                )?;
                let time = services.time.observe();
                let original = EffectManagementCatalog::plan_for_actor(
                    &view,
                    &request.input().actor_tenant,
                    &request.input().actor_subject,
                    &request.input().operation_id,
                )?;
                let qualification = if let Some(original) = original {
                    if original.request() != &request {
                        return Err(Error::Conflict);
                    }
                    None
                } else {
                    qualify(services, &view, &request, time)?
                };
                let prepared = EffectManagementCatalog::prepare_plan(
                    &view,
                    services.epoch,
                    request,
                    time,
                    qualification,
                )?;
                let (mut batch, plan, replayed) = prepared.into_parts();
                batch.expectations.push(namespace.expectation());
                let authority = load_authority(&view, &plan)?;
                store
                    .apply_fenced(batch, || {
                        let current = services.time.observe();
                        let deadline = expiration(&plan, current, replayed)?;
                        role_fence(services, &plan, None, replayed, || {
                            let mut calls = 0;
                            authorization.with_current(
                                &namespace,
                                EffectManagementPhase::Plan,
                                plan.request().input().action,
                                &mut || {
                                    calls += 1;
                                    let _rules = if plan.request().input().action
                                        == EffectManagementAction::Redrive
                                        && !replayed
                                    {
                                        Some(
                                            services.authority.retry_fence(
                                                &authority,
                                                plan.original_attempt()
                                                    .ok_or(Error::Invalid)?
                                                    .attempt()
                                                    .checked_add(1)
                                                    .ok_or(Error::Capacity)?,
                                                current
                                                    .unix_millis
                                                    .checked_add(
                                                        plan.request().input().retry_delay_millis,
                                                    )
                                                    .ok_or(Error::Capacity)?,
                                                current,
                                            )?,
                                        )
                                    } else {
                                        None
                                    };
                                    live(&authorization, deadline)
                                },
                            )?;
                            if calls != 1 {
                                return Err(Error::InvalidAuthorizationFence);
                            }
                            Ok(())
                        })
                    })
                    .map_err(|error| fenced(&error))?;
                Ok((EffectManagementOutcome::Plan { plan, replayed }, namespace))
            },
        )
    }

    /// Applies administrative stop or safe redrive. Provider reconciliation is
    /// admitted separately through the same existing fixed provider workers.
    pub fn mutate_effect_retained<R: Send + 'static>(
        &self,
        plan: EffectManagementPlan,
        authorization: Arc<dyn EffectManagementAuthorization>,
        retained: R,
        retained_bytes: u64,
        complete: impl FnOnce(&Result<EffectManagementOutcome, Error>, &mut R) -> Result<(), StoreError>
            + Send
            + 'static,
    ) -> Result<RetainedEffectManagementJob<R>, Error> {
        if plan.request().input().action == EffectManagementAction::Reconcile {
            return reconciliation::submit(
                self,
                plan,
                authorization,
                retained,
                retained_bytes,
                complete,
            );
        }
        submit(
            &self.services,
            Arc::clone(&authorization),
            retained_bytes,
            retained,
            complete,
            move |services, store| {
                authorization.before_lookup()?;
                let view = store.snapshot()?;
                let namespace = namespace(&view, plan.request())?;
                check(
                    &authorization,
                    &namespace,
                    EffectManagementPhase::Read,
                    plan.request().input().action,
                )?;
                if let Some(receipt) = EffectManagementCatalog::lookup(&view, &plan)? {
                    return Ok((
                        EffectManagementOutcome::Mutation {
                            receipt,
                            replayed: true,
                        },
                        namespace,
                    ));
                }
                check(
                    &authorization,
                    &namespace,
                    EffectManagementPhase::Mutate,
                    plan.request().input().action,
                )?;
                let evidence = evidence(services, &view, &plan)?;
                persist(
                    services,
                    store,
                    &view,
                    MutationInputs {
                        namespace,
                        plan,
                        evidence,
                    },
                    &authorization,
                    None,
                )
            },
        )
    }

    pub fn lookup_effect_receipt_retained<R: Send + 'static>(
        &self,
        plan: EffectManagementPlan,
        authorization: Arc<dyn EffectManagementAuthorization>,
        retained: R,
        retained_bytes: u64,
        complete: impl FnOnce(&Result<EffectManagementOutcome, Error>, &mut R) -> Result<(), StoreError>
            + Send
            + 'static,
    ) -> Result<RetainedEffectManagementJob<R>, Error> {
        submit_kind(
            &self.services,
            Arc::clone(&authorization),
            StoreIoKind::RecoveryRead,
            retained_bytes,
            retained,
            complete,
            move |_, store| {
                authorization.before_lookup()?;
                let view = store.snapshot()?;
                let namespace = namespace(&view, plan.request())?;
                check(
                    &authorization,
                    &namespace,
                    EffectManagementPhase::Read,
                    plan.request().input().action,
                )?;
                let receipt = EffectManagementCatalog::lookup(&view, &plan)?;
                check(
                    &authorization,
                    &namespace,
                    EffectManagementPhase::Read,
                    plan.request().input().action,
                )?;
                Ok((EffectManagementOutcome::Receipt(receipt), namespace))
            },
        )
    }
}
