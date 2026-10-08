use std::sync::{Arc, Mutex};

use crate::authority::{AuthorityError, EffectAuthorityOwner};
use crate::dispatch::{AttemptReceipt, Disposition, RetryProof};
use crate::dispatch_store::{DispatchCatalog, DispatchEpoch, DispatchStoreError};
use latent_state::protected_store::ProtectedStoreOwner;
use latent_state::store_io::StoreIoKind;

<<<<<<< HEAD
=======
use super::capacity::AttemptCapacity;
>>>>>>> 53bf0f45de3696e8ad4e2efd884d63d7ec917a5a
use super::state::{ActiveGuard, Shared};
use super::store::{self, Candidate};
use super::{AdapterOutcome, DeferredEffectAdapter, DispatcherError, EffectTimeSource};

pub(super) struct Services {
    pub store: Arc<ProtectedStoreOwner>,
    pub authority: EffectAuthorityOwner,
    pub adapters: Arc<[Arc<dyn DeferredEffectAdapter>]>,
    pub time: Arc<dyn EffectTimeSource>,
    pub epoch: DispatchEpoch,
    pub runtime: tokio::runtime::Handle,
    pub shared: Arc<Shared>,
<<<<<<< HEAD
=======
    pub native_capacity: Mutex<super::admission::NativeCapacityBinding>,
>>>>>>> 53bf0f45de3696e8ad4e2efd884d63d7ec917a5a
    pub receipts: tokio::sync::mpsc::Sender<ReceiptWork>,
}

pub(super) struct ReceiptWork {
    pub attempt: crate::dispatch::AttemptIdentity,
    pub outcome: AdapterOutcome,
    pub completed: tokio::sync::oneshot::Sender<Result<(), DispatcherError>>,
<<<<<<< HEAD
=======
    pub capacity: Arc<AttemptCapacity>,
>>>>>>> 53bf0f45de3696e8ad4e2efd884d63d7ec917a5a
}

struct Prepared {
    attempt: crate::dispatch::AttemptIdentity,
    accepted: Result<latent_core::BoxFuture<'static, AdapterOutcome>, AdapterOutcome>,
}

<<<<<<< HEAD
pub(super) fn run(services: &Services, candidate: Candidate, mut guard: ActiveGuard) {
    guard.start();
    let result = services.runtime.block_on(execute(services, candidate));
=======
pub(super) fn run(
    services: &Services,
    candidate: Candidate,
    mut guard: ActiveGuard,
    capacity: Arc<AttemptCapacity>,
) {
    guard.start();
    let result = services
        .runtime
        .block_on(execute(services, candidate, capacity));
>>>>>>> 53bf0f45de3696e8ad4e2efd884d63d7ec917a5a
    if let Err(error) = result {
        services.shared.fail(error);
    }
    // Every ordinary path completed actual provider cleanup and pin retirement.
    // Panic instead drops this unretired guard and quarantines bounded ownership.
    guard.retire();
}

<<<<<<< HEAD
async fn execute(services: &Services, candidate: Candidate) -> Result<(), DispatcherError> {
    if !services.shared.available() {
=======
async fn execute(
    services: &Services,
    candidate: Candidate,
    capacity: Arc<AttemptCapacity>,
) -> Result<(), DispatcherError> {
    if !services.shared.available() || capacity.check().is_err() {
>>>>>>> 53bf0f45de3696e8ad4e2efd884d63d7ec917a5a
        return Ok(());
    }
    let time = services.time.observe();
    let Some(adapter) = services
        .adapters
        .iter()
        .find(|adapter| adapter.profile() == candidate.authority.profile())
    else {
<<<<<<< HEAD
        return block(services, candidate, time).await;
    };
    let pin = match services.store.reserve_operation() {
        Err(error) if super::driver::backpressure(error.into()) => return Ok(()),
        result => result?,
    };
    let context = match services
=======
        return block(services, candidate, time, capacity).await;
    };
    let pin = match services.store.reserve_operation_retaining(capacity.clone()) {
        Err(error) if super::driver::backpressure(error.into()) => return Ok(()),
        result => result?,
    };
    let mut context = match services
>>>>>>> 53bf0f45de3696e8ad4e2efd884d63d7ec917a5a
        .authority
        .accept(&candidate.authority, candidate.attempt, time)
    {
        Ok(context) => context,
        Err(
            AuthorityError::PolicyBlocked
            | AuthorityError::UnsupportedFormat
            | AuthorityError::Expired,
        ) => {
<<<<<<< HEAD
            let result = block(services, candidate, time).await;
=======
            let result = block(services, candidate, time, Arc::clone(&capacity)).await;
>>>>>>> 53bf0f45de3696e8ad4e2efd884d63d7ec917a5a
            pin.retire().await;
            return result;
        }
        Err(AuthorityError::Capacity) => {
            pin.retire().await;
            return Ok(());
        }
        Err(error) => {
            pin.retire().await;
            return Err(error.into());
        }
    };
<<<<<<< HEAD
=======
    if context.restrict_deadline(capacity.deadline()).is_err() {
        context.retire()?;
        pin.retire().await;
        return Ok(());
    }
    context
        .retain_owner(capacity.clone())
        .map_err(|_| DispatcherError::InvalidConfiguration)?;
>>>>>>> 53bf0f45de3696e8ad4e2efd884d63d7ec917a5a
    let context = Arc::new(Mutex::new(Some(context)));
    let prepared = prepare(
        services,
        candidate,
        Arc::clone(adapter),
        Arc::clone(&context),
        time,
<<<<<<< HEAD
    )
    .await;
    let outcome = match prepared {
=======
        Arc::clone(&capacity),
    )
    .await;
    let outcome = run_prepared(services, prepared).await;
    let retired = context
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
        .take()
        .expect("owned physical context")
        .retire()
        .map_err(DispatcherError::from);
    let result = match outcome {
        Ok(Some((attempt, outcome))) => record(services, attempt, outcome, capacity).await,
        Ok(None) => Ok(()),
        Err(error) => Err(error),
    };
    pin.retire().await;
    retired?;
    result
}

async fn run_prepared(
    services: &Services,
    prepared: Result<Prepared, DispatcherError>,
) -> Result<Option<(crate::dispatch::AttemptIdentity, AdapterOutcome)>, DispatcherError> {
    match prepared {
>>>>>>> 53bf0f45de3696e8ad4e2efd884d63d7ec917a5a
        Ok(prepared) => {
            {
                let mut state = services
                    .shared
                    .state
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                state.claims = state
                    .claims
                    .checked_add(1)
                    .ok_or(DispatcherError::InvalidConfiguration)?;
            }
            let outcome = match prepared.accepted {
                Ok(future) => future.await,
                Err(outcome) => outcome,
            };
            Ok(Some((prepared.attempt, outcome)))
        }
        Err(
            DispatcherError::Store(DispatchStoreError::Authority(
                AuthorityError::Stale
                | AuthorityError::Capacity
                | AuthorityError::Expired
                | AuthorityError::PolicyBlocked,
            ))
            | DispatcherError::ProtectedStore(
                latent_state::protected_store::ProtectedStoreError::Store(
                    latent_state::embedded::StoreError::Capacity
                    | latent_state::embedded::StoreError::Conflict,
                ),
            ),
        ) => Ok(None),
        Err(error) if super::driver::backpressure(error) => Ok(None),
        Err(error) => Err(error),
<<<<<<< HEAD
    };
    let retired = context
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
        .take()
        .expect("owned physical context")
        .retire()
        .map_err(DispatcherError::from);
    let result = match outcome {
        Ok(Some((attempt, outcome))) => record(services, attempt, outcome).await,
        Ok(None) => Ok(()),
        Err(error) => Err(error),
    };
    pin.retire().await;
    retired?;
    result
=======
    }
>>>>>>> 53bf0f45de3696e8ad4e2efd884d63d7ec917a5a
}

async fn prepare(
    services: &Services,
    candidate: Candidate,
    adapter: Arc<dyn DeferredEffectAdapter>,
    worker_context: Arc<Mutex<Option<crate::authority::DispatchContext>>>,
    time: crate::authority::EffectTime,
<<<<<<< HEAD
) -> Result<Prepared, DispatcherError> {
    let clock = Arc::clone(&services.time);
    let epoch = services.epoch;
    store::call(
        &services.store,
        StoreIoKind::Write,
        8 * 1024 * 1024,
        move |store| {
            let claim = DispatchCatalog::claim(store, epoch, &candidate.due, time)?;
=======
    capacity: Arc<AttemptCapacity>,
) -> Result<Prepared, DispatcherError> {
    let clock = Arc::clone(&services.time);
    let epoch = services.epoch;
    let shared = Arc::clone(&services.shared);
    let original = Arc::clone(&capacity);
    store::call_retaining(
        &services.store,
        StoreIoKind::Write,
        super::capacity::PREPARATION_BYTES,
        capacity,
        move |store| {
            let accept = || {
                let state = shared
                    .state
                    .lock()
                    .map_err(|_| AuthorityError::Unavailable)?;
                if state.closed || state.paused || state.failure.is_some() {
                    return Err(AuthorityError::PolicyBlocked);
                }
                original.check()
            };
            let claim = DispatchCatalog::claim_fenced(store, epoch, &candidate.due, time, accept)?;
>>>>>>> 53bf0f45de3696e8ad4e2efd884d63d7ec917a5a
            let crate::dispatch_store::ClaimedEffect {
                authority,
                attempt,
                payload,
            } = claim;
            let time = clock.observe();
<<<<<<< HEAD
            let deadline = worker_context
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .as_ref()
                .expect("owned physical context")
                .deadline();
            let mut payload = Some(payload);
            let mut adapter_refusal = false;
            let mut accept = || {
                let payload = payload.take().ok_or(AuthorityError::Invalid)?;
                let admitted = worker_context
                    .lock()
                    .map_err(|_| AuthorityError::Unavailable)?
                    .as_mut()
                    .ok_or(AuthorityError::Unavailable)?
                    .accept_with(&authority, attempt.attempt(), time, |grant| {
                        adapter.accept(grant, payload, attempt.clone())
                    })?;
                adapter_refusal = admitted.is_err();
                admitted
            };
            let accepted = adapter.with_current_dispatch(&authority, deadline, &mut accept);
            let accepted = match accepted {
                Ok(future) => {
                    // Same accepted storage job owns claim/admission/send-marker:
                    // queue pressure cannot strand an admitted unpolled operation.
                    DispatchCatalog::begin_send(store, epoch, &attempt, time)?;
                    Ok(future)
                }
                Err(error) => Err(AdapterOutcome {
                    receipt: negative(error, time.unix_millis, !adapter_refusal),
                    retry: (adapter_refusal
                        && matches!(
                            error,
                            AuthorityError::Capacity | AuthorityError::Unavailable
                        ))
                    .then_some((RetryProof::KnownNonexecution, 100)),
                }),
=======
            let accepted = worker_context
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .as_mut()
                .expect("owned physical context")
                .accept_with(&authority, attempt.attempt(), time, |grant| {
                    original.accept_provider(|| adapter.accept(grant, payload, attempt.clone()))
                });
            let accepted = match accepted {
                Ok(Ok(Ok(future))) => {
                    // Same accepted storage job owns claim/admission/send-marker:
                    // queue pressure cannot strand an admitted unpolled operation.
                    match DispatchCatalog::begin_send_fenced(store, epoch, &attempt, time, accept) {
                        Ok(()) => Ok(future),
                        Err(DispatchStoreError::Authority(error)) => {
                            drop(future); // Proven unpolled: provider buffers retire before receipt.
                            Err(AdapterOutcome {
                                receipt: negative(error, time.unix_millis, true),
                                retry: None,
                            })
                        }
                        Err(error) => return Err(error),
                    }
                }
                Ok(Ok(Err(error))) => Err(AdapterOutcome {
                    receipt: negative(error, time.unix_millis, false),
                    retry: matches!(
                        error,
                        AuthorityError::Capacity | AuthorityError::Unavailable
                    )
                    .then_some((RetryProof::KnownNonexecution, 100)),
                }),
                Ok(Err(error)) | Err(error) => Err(AdapterOutcome {
                    receipt: negative(error, time.unix_millis, true),
                    retry: None,
                }),
>>>>>>> 53bf0f45de3696e8ad4e2efd884d63d7ec917a5a
            };
            Ok(Prepared { attempt, accepted })
        },
    )
    .await
}

async fn record(
    services: &Services,
    attempt: crate::dispatch::AttemptIdentity,
    outcome: AdapterOutcome,
<<<<<<< HEAD
=======
    capacity: Arc<AttemptCapacity>,
>>>>>>> 53bf0f45de3696e8ad4e2efd884d63d7ec917a5a
) -> Result<(), DispatcherError> {
    let time = services.time.observe();
    let mut receipt = outcome.receipt;
    let retry = if receipt.valid() { outcome.retry } else { None };
    if !receipt.valid() {
        receipt = AttemptReceipt {
            disposition: Disposition::Uncertain,
            reason: "invalid-adapter-receipt".into(),
            provider_receipt: None,
            observed_at_millis: time.unix_millis,
        };
    }
    receipt.observed_at_millis = time.unix_millis;
    let (completed, completion) = tokio::sync::oneshot::channel();
    services
        .receipts
        .send(ReceiptWork {
            attempt,
            outcome: AdapterOutcome { receipt, retry },
            completed,
<<<<<<< HEAD
=======
            capacity,
>>>>>>> 53bf0f45de3696e8ad4e2efd884d63d7ec917a5a
        })
        .await
        .map_err(|_| DispatcherError::AdmissionClosed)?;
    services.shared.notify.notify_one();
    completion
        .await
        .map_err(|_| DispatcherError::AdmissionClosed)?
}

fn negative(error: AuthorityError, millis: u64, final_authority: bool) -> AttemptReceipt {
    AttemptReceipt {
        disposition: if error == AuthorityError::Expired {
            Disposition::Expired
        } else if final_authority
            || matches!(
                error,
                AuthorityError::PolicyBlocked
                    | AuthorityError::UnsupportedFormat
                    | AuthorityError::Invalid
            )
        {
            Disposition::PolicyBlocked
        } else {
            Disposition::KnownFailed
        },
        reason: match error {
            AuthorityError::Expired => "expired",
            AuthorityError::UnsupportedFormat => "decoder-unavailable",
            AuthorityError::PolicyBlocked => "current-policy-denied",
            AuthorityError::Capacity => "adapter-capacity",
            AuthorityError::Unavailable => "adapter-unavailable",
            AuthorityError::ClockDiscontinuity => "clock-discontinuity",
            AuthorityError::Stale => "stale-authority",
            AuthorityError::Invalid => "invalid-adapter-request",
        }
        .into(),
        provider_receipt: None,
        observed_at_millis: millis,
    }
}

async fn block(
    services: &Services,
    candidate: Candidate,
    time: crate::authority::EffectTime,
<<<<<<< HEAD
) -> Result<(), DispatcherError> {
    let epoch = services.epoch;
    match store::call(
        &services.store,
        StoreIoKind::Write,
        1024 * 1024,
=======
    capacity: Arc<AttemptCapacity>,
) -> Result<(), DispatcherError> {
    let epoch = services.epoch;
    match store::call_retaining(
        &services.store,
        StoreIoKind::Write,
        1024 * 1024,
        capacity,
>>>>>>> 53bf0f45de3696e8ad4e2efd884d63d7ec917a5a
        move |store| DispatchCatalog::block_eligible(store, epoch, &candidate.due, time),
    )
    .await
    {
        Err(DispatcherError::Store(DispatchStoreError::Authority(AuthorityError::Stale))) => Ok(()),
        Err(error) if super::driver::backpressure(error) => Ok(()),
        result => result,
    }
}
