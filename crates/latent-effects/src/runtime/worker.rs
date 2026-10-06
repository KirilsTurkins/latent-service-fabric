use std::sync::{Arc, Mutex};

use crate::authority::{AuthorityError, EffectAuthorityOwner};
use crate::dispatch::{AttemptReceipt, Disposition, RetryProof};
use crate::dispatch_store::{DispatchCatalog, DispatchEpoch, DispatchStoreError};
use latent_state::protected_store::ProtectedStoreOwner;
use latent_state::store_io::StoreIoKind;

use super::capacity::AttemptCapacity;
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
    pub native_capacity: Mutex<super::admission::NativeCapacityBinding>,
    pub receipts: tokio::sync::mpsc::Sender<ReceiptWork>,
}

pub(super) struct ReceiptWork {
    pub attempt: crate::dispatch::AttemptIdentity,
    pub outcome: AdapterOutcome,
    pub completed: tokio::sync::oneshot::Sender<Result<(), DispatcherError>>,
    pub capacity: Arc<AttemptCapacity>,
}

struct Prepared {
    attempt: crate::dispatch::AttemptIdentity,
    accepted: Result<latent_core::BoxFuture<'static, AdapterOutcome>, AdapterOutcome>,
}

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
    if let Err(error) = result {
        services.shared.fail(error);
    }
    // Every ordinary path completed actual provider cleanup and pin retirement.
    // Panic instead drops this unretired guard and quarantines bounded ownership.
    guard.retire();
}

async fn execute(
    services: &Services,
    candidate: Candidate,
    capacity: Arc<AttemptCapacity>,
) -> Result<(), DispatcherError> {
    if !services.shared.available() || capacity.check().is_err() {
        return Ok(());
    }
    let time = services.time.observe();
    let Some(adapter) = services
        .adapters
        .iter()
        .find(|adapter| adapter.profile() == candidate.authority.profile())
    else {
        return block(services, candidate, time, capacity).await;
    };
    let pin = match services.store.reserve_operation_retaining(capacity.clone()) {
        Err(error) if super::driver::backpressure(error.into()) => return Ok(()),
        result => result?,
    };
    let mut context = match services
        .authority
        .accept(&candidate.authority, candidate.attempt, time)
    {
        Ok(context) => context,
        Err(
            AuthorityError::PolicyBlocked
            | AuthorityError::UnsupportedFormat
            | AuthorityError::Expired,
        ) => {
            let result = block(services, candidate, time, Arc::clone(&capacity)).await;
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
    if context.restrict_deadline(capacity.deadline()).is_err() {
        context.retire()?;
        pin.retire().await;
        return Ok(());
    }
    context
        .retain_owner(capacity.clone())
        .map_err(|_| DispatcherError::InvalidConfiguration)?;
    let context = Arc::new(Mutex::new(Some(context)));
    let prepared = prepare(
        services,
        candidate,
        Arc::clone(adapter),
        Arc::clone(&context),
        time,
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
    }
}

async fn prepare(
    services: &Services,
    candidate: Candidate,
    adapter: Arc<dyn DeferredEffectAdapter>,
    worker_context: Arc<Mutex<Option<crate::authority::DispatchContext>>>,
    time: crate::authority::EffectTime,
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
            let crate::dispatch_store::ClaimedEffect {
                authority,
                attempt,
                payload,
            } = claim;
            let time = clock.observe();
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
    capacity: Arc<AttemptCapacity>,
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
            capacity,
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
    capacity: Arc<AttemptCapacity>,
) -> Result<(), DispatcherError> {
    let epoch = services.epoch;
    match store::call_retaining(
        &services.store,
        StoreIoKind::Write,
        1024 * 1024,
        capacity,
        move |store| DispatchCatalog::block_eligible(store, epoch, &candidate.due, time),
    )
    .await
    {
        Err(DispatcherError::Store(DispatchStoreError::Authority(AuthorityError::Stale))) => Ok(()),
        Err(error) if super::driver::backpressure(error) => Ok(()),
        result => result,
    }
}
