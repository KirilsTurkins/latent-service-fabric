//! Raw storage never replaces remote authorization or checked package assembly.
mod acquire;
mod job;
mod protocol;
#[cfg(test)]
mod tests;

use super::{exhausted, HttpOciRegistry, Operation, Result};
use crate::OciDescriptor;
use acquire::{destination, Destination};
use job::{owned_job, BlobBuffer};
use latent_artifacts::{RawArtifactCache, RawArtifactKey, RawArtifactPin};
use latent_core::PlatformErrorCode;
use std::sync::Arc;
use tokio::sync::OwnedSemaphorePermit;

impl HttpOciRegistry {
    pub(super) async fn fetch_package_blob(
        &self,
        descriptor: &OciDescriptor,
        operation: Arc<Operation>,
        graph: &mut OwnedSemaphorePermit,
    ) -> Result<Vec<u8>> {
        let Some(cache) = &self.cache else {
            return self.fetch_blob(descriptor, operation.deadline).await;
        };
        let size = usize::try_from(descriptor.size_bytes)
            .map_err(|_| exhausted("oci-size-not-addressable"))?;
        let permit = graph
            .split(size)
            .ok_or_else(|| exhausted("oci-materialization-limit"))?;
        let buffer = BlobBuffer::new(permit);
        let key = RawArtifactKey::Blob(
            descriptor
                .digest
                .parse()
                .map_err(|_| super::invalid("invalid-oci-blob-digest"))?,
        );
        let buffer = self
            .cached_blob(cache, key, descriptor, operation, buffer)
            .await?;
        let BlobBuffer { bytes, permit } = buffer;
        graph.merge(permit);
        Ok(bytes)
    }

    async fn cached_blob(
        &self,
        cache: &Arc<RawArtifactCache>,
        key: RawArtifactKey,
        descriptor: &OciDescriptor,
        operation: Arc<Operation>,
        mut buffer: BlobBuffer,
    ) -> Result<BlobBuffer> {
        if let Some(pin) = cache.try_pin(&key)? {
            let (returned, hit) = self
                .cached_read(pin, descriptor, operation.clone(), buffer)
                .await?;
            buffer = returned;
            if hit {
                return Ok(buffer);
            }
        }
        let (returned, target) =
            destination(cache, key, descriptor.size_bytes, operation.clone(), buffer).await?;
        buffer = returned;
        let write = match target {
            Destination::Write(write) => write,
            Destination::Read(pin) => {
                // One re-pin after another owner committed between lookup and
                // reservation. A second corrupt/raced incarnation is an error.
                let (buffer, hit) = self.cached_read(pin, descriptor, operation, buffer).await?;
                return if hit {
                    Ok(buffer)
                } else {
                    Err(super::corrupt("oci-cache-fill-raced"))
                };
            }
        };
        // Reservation includes disk/staging/index/work pressure BEFORE GET.
        buffer.bytes = self.fetch_blob(descriptor, operation.deadline).await?;
        let (buffer, outcome) = owned_job(operation, buffer, move |buffer| {
            drop(write.publish(&buffer.bytes)?);
            Ok(())
        })
        .await?;
        outcome?;
        Ok(buffer)
    }

    async fn cached_read(
        &self,
        pin: RawArtifactPin,
        descriptor: &OciDescriptor,
        operation: Arc<Operation>,
        mut buffer: BlobBuffer,
    ) -> Result<(BlobBuffer, bool)> {
        if !self
            .authorize_cached_blob(descriptor, operation.deadline)
            .await?
        {
            // HEAD unsupported: GET remains the authorization/integrity boundary.
            drop(pin);
            buffer.bytes = self.fetch_blob(descriptor, operation.deadline).await?;
            return Ok((buffer, true));
        }
        let (mut buffer, outcome) =
            read_cached(pin, descriptor.size_bytes, operation, buffer).await?;
        match outcome {
            Ok(()) => Ok((buffer, true)),
            Err(error)
                if matches!(
                    error.code,
                    PlatformErrorCode::CorruptArtifact | PlatformErrorCode::NotFound
                ) =>
            {
                // Invalid exact incarnation stays charged until bounded cleanup.
                buffer.bytes = Vec::new();
                Ok((buffer, false))
            }
            Err(error) => Err(error),
        }
    }
}

async fn read_cached(
    pin: RawArtifactPin,
    size: u64,
    operation: Arc<Operation>,
    buffer: BlobBuffer,
) -> Result<(BlobBuffer, Result<()>)> {
    if pin.size_bytes() != size {
        return Err(super::corrupt("oci-cached-descriptor-size-mismatch"));
    }
    let read = pin.reserve_read(size)?;
    let size = usize::try_from(size).map_err(|_| exhausted("oci-size-not-addressable"))?;
    owned_job(operation, buffer, move |buffer| {
        buffer
            .bytes
            .try_reserve_exact(size)
            .map_err(|_| exhausted("oci-response-allocation-limit"))?;
        buffer.bytes.resize(size, 0);
        read.read_into(&mut buffer.bytes)
    })
    .await
}
