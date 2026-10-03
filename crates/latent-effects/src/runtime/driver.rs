use std::sync::Arc;

use crate::dispatch_store::DispatchCatalog;
use latent_state::embedded::StoreError;
use latent_state::protected_store::{ProtectedStoreDispatcher, ProtectedStoreError};
use latent_state::store_io::{StoreIoError, StoreIoKind, StoreIoOwner};

use super::store;
use super::worker::{ReceiptWork, Services};
use super::{DispatcherConfig, DispatcherError};

pub(super) async fn drive(
    services: Arc<Services>,
    jobs: StoreIoOwner<Arc<Services>>,
    config: DispatcherConfig,
    role: ProtectedStoreDispatcher,
    mut receipts: tokio::sync::mpsc::Receiver<ReceiptWork>,
) {
    let mut cursor = None;
    let mut pending_receipt = None;
    loop {
        if pending_receipt.is_none() {
            pending_receipt = receipts.try_recv().ok();
        }
        if let Some(receipt) = pending_receipt.take() {
            if let Some(pending) = record(&services, receipt).await {
                pending_receipt = Some(pending);
            }
        }
        let closed = services
            .shared
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .closed;
        match jobs.snapshot() {
            Ok(snapshot)
                if closed
                    && snapshot.physically_retired()
                    && pending_receipt.is_none()
                    && receipts.is_empty() =>
            {
                break
            }
            Err(error) => services.shared.fail(error.into()),
            _ => {}
        }
        if pending_receipt.is_none() && services.shared.available() {
            for _ in 0..config.scan_pages_per_tick {
                match scan(&services, &jobs, &config, cursor.take()).await {
                    Ok(next) => {
                        cursor = next;
                        if cursor.is_none() {
                            break;
                        }
                    }
                    Err(error) if backpressure(error) => break,
                    Err(error) => {
                        services.shared.fail(error);
                        break;
                    }
                }
            }
        }
        match store::counts(&services.store).await {
            Ok(counts) => {
                let mut state = services
                    .shared
                    .state
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                state.counts = counts;
                state.counts_time = services.time.observe().unix_millis;
            }
            Err(error) if backpressure(error) => {}
            Err(error) => services.shared.fail(error),
        }
        // Exactly one scheduling owner and timer; receipt persistence is served
        // first. Fixed workers wait on bounded receipt slots, never own timers.
        tokio::select! {
            () = services.shared.notify.notified() => {},
            () = tokio::time::sleep(config.poll_interval) => {},
        }
    }
    let safe = services
        .authority
        .owners()
        .is_ok_and(|owners| owners.physical == 0)
        && services
            .shared
            .state
            .lock()
            .is_ok_and(|state| state.effects_empty());
    if safe {
        role.retire().await;
    } else {
        drop(role);
    }
    services
        .shared
        .state
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
        .scheduling_retired = true;
}

async fn scan(
    services: &Services,
    jobs: &StoreIoOwner<Arc<Services>>,
    config: &DispatcherConfig,
    cursor: Option<Vec<u8>>,
) -> Result<Option<Vec<u8>>, DispatcherError> {
    let page = store::candidates(
        &services.store,
        services.time.observe(),
        cursor,
        config.page_rows,
        config.page_bytes,
    )
    .await?;
    for candidate in page.rows {
        let Some(guard) = services.shared.admit(
            &candidate.authority.scope().tenant,
            &candidate.due.effect,
            config,
        ) else {
            continue;
        };
        match jobs.submit(
            StoreIoKind::Read,
            DispatcherConfig::ATTEMPT_BYTES,
            move |services| {
                super::worker::run(services, candidate, guard);
            },
        ) {
            Ok(job) => drop(job), // Detach result observation; accepted work still runs once.
            Err(error) => {
                let reason = error.reason;
                drop(error.operation); // Never started: its guard releases bounded admission.
                if !matches!(
                    reason,
                    StoreIoError::QueueFull
                        | StoreIoError::AcceptedFull
                        | StoreIoError::ByteBudget
                        | StoreIoError::AdmissionClosed
                ) {
                    return Err(reason.into());
                }
            }
        }
    }
    Ok(page.resume)
}

async fn record(services: &Services, receipt: ReceiptWork) -> Option<ReceiptWork> {
    let epoch = services.epoch;
    let time = services.time.observe();
    let attempt = receipt.attempt.clone();
    let mut durable = receipt.outcome.receipt.clone();
    durable.observed_at_millis = time.unix_millis;
    let retry = receipt.outcome.retry;
    let result = store::call(
        &services.store,
        StoreIoKind::Write,
        2 * 1024 * 1024,
        move |store| {
            DispatchCatalog::complete(store, epoch, &attempt, durable, retry, time).map(|_| ())
        },
    )
    .await;
    if result
        .as_ref()
        .is_err_and(|error| admission_backpressure(*error))
    {
        return Some(receipt);
    }
    if let Err(error) = &result {
        services.shared.fail(*error);
    }
    let _ = receipt.completed.send(result);
    None
}

pub(super) fn backpressure(error: DispatcherError) -> bool {
    admission_backpressure(error)
        || matches!(
            error,
            DispatcherError::ProtectedStore(ProtectedStoreError::Store(StoreError::Capacity))
        )
}

fn admission_backpressure(error: DispatcherError) -> bool {
    matches!(
        error,
        DispatcherError::ProtectedStore(ProtectedStoreError::Io(
            StoreIoError::QueueFull | StoreIoError::AcceptedFull | StoreIoError::ByteBudget
        ))
    )
}
