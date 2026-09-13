use super::super::{Operation, Result};
use latent_core::PlatformErrorCode;
use std::sync::Arc;
use tokio::{
    sync::OwnedSemaphorePermit,
    time::{timeout_at, Instant},
};

// Field order drops the actual Vec before refunding its independent byte lease.
#[derive(Debug)]
pub(super) struct BlobBuffer {
    pub(super) bytes: Vec<u8>,
    pub(super) permit: OwnedSemaphorePermit,
}

impl BlobBuffer {
    pub(super) fn new(permit: OwnedSemaphorePermit) -> Self {
        Self {
            bytes: Vec::new(),
            permit,
        }
    }
}

/// All cache jobs/reservations are acquired before reaching this bridge. The
/// closure owns the root/work/pin plus split byte and operation permits even if
/// timeout/caller cancellation drops its `JoinHandle` while disk work continues.
pub(super) async fn owned_job<T: Send + 'static>(
    operation: Arc<Operation>,
    mut buffer: BlobBuffer,
    job: impl FnOnce(&mut BlobBuffer) -> Result<T> + Send + 'static,
) -> Result<(BlobBuffer, Result<T>)> {
    let deadline = operation.deadline;
    if Instant::now() >= deadline {
        return Err(deadline_error());
    }
    let work = tokio::task::spawn_blocking(move || {
        let _operation = operation;
        let result = if Instant::now() >= deadline {
            Err(deadline_error())
        } else {
            job(&mut buffer)
        };
        (buffer, result)
    });
    let completed = timeout_at(deadline, work)
        .await
        .map_err(|_| deadline_error())?
        .map_err(|_| crate::error(PlatformErrorCode::Unavailable, "oci-cache-job-failed"))?;
    // A timeout polls its inner future first. A ready disk result can therefore
    // win after the deadline if this waiter was not polled in the meantime.
    if Instant::now() >= deadline {
        drop(completed); // Drop the actual bytes before their retained permit.
        return Err(deadline_error());
    }
    Ok(completed)
}

fn deadline_error() -> latent_core::PlatformError {
    crate::error(
        PlatformErrorCode::DeadlineExceeded,
        "oci-cache-operation-deadline",
    )
}
