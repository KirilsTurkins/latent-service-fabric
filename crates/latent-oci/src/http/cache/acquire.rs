use super::{
    owned_job, BlobBuffer, Operation, RawArtifactCache, RawArtifactKey, RawArtifactPin, Result,
};
use latent_artifacts::RawArtifactWrite;
use latent_core::PlatformErrorCode;
use std::sync::Arc;

const RECLAIM_ENTRIES: usize = 16;

pub(super) enum Destination {
    Write(RawArtifactWrite),
    Read(RawArtifactPin),
}

pub(super) async fn destination(
    cache: &Arc<RawArtifactCache>,
    key: RawArtifactKey,
    size: u64,
    operation: Arc<Operation>,
    mut buffer: BlobBuffer,
) -> Result<(BlobBuffer, Destination)> {
    let limits = cache.limits();
    if size > limits.maximum_object_bytes
        || size > limits.maximum_disk_bytes
        || size > limits.maximum_staging_bytes
    {
        return Err(super::exhausted("oci-cache-object-limit"));
    }
    let mut reservation = cache.reserve_write(key.clone(), size);
    if reservation.as_ref().is_err_and(|error| {
        error.code == PlatformErrorCode::ResourceExhausted
            && error.message == "raw-cache-reclaimable-pressure"
    }) {
        let reclaim =
            cache.reserve_reclaim(RECLAIM_ENTRIES.min(limits.maximum_recovery_entries))?;
        let (returned, outcome) = owned_job(operation, buffer, move |_| reclaim.run()).await?;
        buffer = returned;
        outcome?;
        reservation = cache.reserve_write(key.clone(), size);
    }
    let target = match reservation {
        Ok(write) => Destination::Write(write),
        Err(error) if error.code == PlatformErrorCode::AlreadyExists => {
            let pin = cache.try_pin(&key)?.ok_or_else(|| {
                crate::error(PlatformErrorCode::Unavailable, "oci-cache-fill-raced")
            })?;
            Destination::Read(pin)
        }
        Err(error) => return Err(error),
    };
    Ok((buffer, target))
}
