use super::NativeAotService;
use crate::aot::TrustedAotOutput;
use latent_artifacts::{RawArtifactCache, RawArtifactEviction, RawArtifactKey, RawArtifactPin};
use latent_core::{PlatformError, PlatformErrorCode};
use std::sync::Arc;

impl NativeAotService {
    pub(super) fn persist(&self, output: &TrustedAotOutput) -> Result<(), PlatformError> {
        let key = RawArtifactKey::Blob(output.output_digest().clone());
        // Exact digest produced by the approved child; storage publishes a
        // separately verified blob before its compatibility locator.
        let pin = persist_blob(&self.raw, &key, output.output())?;
        let digest = output.compatibility().digest();
        let result = match self.receipts.publish(&digest, output.receipt()) {
            Err(error) if error.message == "native-receipt-cache-reclaimable-pressure" => {
                self.receipts
                    .reclaim(self.receipts.limits().maximum_entries.min(16))?;
                self.receipts.publish(&digest, output.receipt())
            }
            result => result,
        };
        drop(pin);
        result
    }
}

fn persist_blob(
    raw: &Arc<RawArtifactCache>,
    key: &RawArtifactKey,
    bytes: &[u8],
) -> Result<RawArtifactPin, PlatformError> {
    match publish_blob(raw, key, bytes) {
        Err(error) if error.message == "raw-cache-reclaimable-pressure" => {
            let maximum = raw.limits().maximum_recovery_entries.min(16);
            raw.reserve_reclaim(maximum)?.run()?;
            publish_blob(raw, key, bytes)
        }
        result => result,
    }
}

fn publish_blob(
    raw: &Arc<RawArtifactCache>,
    key: &RawArtifactKey,
    bytes: &[u8],
) -> Result<RawArtifactPin, PlatformError> {
    if let Some(pin) = raw.try_pin(key)? {
        match verify_existing(raw, pin, key, bytes) {
            Ok(pin) => return Ok(pin),
            Err(error)
                if matches!(
                    error.code,
                    PlatformErrorCode::CorruptArtifact | PlatformErrorCode::NotFound
                ) =>
            {
                remove_exact(raw, key)?;
            }
            Err(error) => return Err(error),
        }
    }
    let write = match raw.reserve_write(key.clone(), bytes.len() as u64) {
        Err(error) if error.message == "raw-cache-reclaimable-pressure" => {
            // A prior failed read may already have invalidated this exact row.
            // Absent means aggregate pressure; leave general bounded LRU to the
            // caller. Never reclaim unrelated entries to clear a pinned row.
            if !remove_exact(raw, key)? {
                return Err(error);
            }
            raw.reserve_write(key.clone(), bytes.len() as u64)?
        }
        result => result?,
    };
    write.publish(bytes)
}

fn verify_existing(
    raw: &Arc<RawArtifactCache>,
    pin: RawArtifactPin,
    key: &RawArtifactKey,
    expected: &[u8],
) -> Result<RawArtifactPin, PlatformError> {
    if pin.size_bytes() != expected.len() as u64 {
        return Err(crate::aot::error(
            PlatformErrorCode::CorruptArtifact,
            "native-cache-size-mismatch",
        ));
    }
    // The read owns its exact allowance, and is consumed before reacquiring the
    // publication pin. No extra pin capacity or unaccounted buffer is needed.
    let bytes = pin.reserve_read(expected.len() as u64)?.read_verified()?;
    if bytes.as_bytes() != expected {
        return Err(crate::aot::error(
            PlatformErrorCode::CorruptArtifact,
            "native-cache-bytes-mismatch",
        ));
    }
    // A concurrent eviction can remove the file after the read retires its pin.
    // Do not claim a successful publication or loop if that happened. A newly
    // published incarnation of this content key is independently hash checked
    // by RawArtifactCache, and future loading still authenticates its own read.
    let pin = raw.try_pin(key)?.ok_or_else(persistence_busy)?;
    if pin.size_bytes() != expected.len() as u64 {
        return Err(persistence_busy());
    }
    drop(bytes);
    Ok(pin)
}

fn remove_exact(raw: &Arc<RawArtifactCache>, key: &RawArtifactKey) -> Result<bool, PlatformError> {
    match raw.evict(key)? {
        RawArtifactEviction::Removed => Ok(true),
        RawArtifactEviction::Absent => Ok(false),
        RawArtifactEviction::Pinned => Err(persistence_busy()),
    }
}

fn persistence_busy() -> PlatformError {
    crate::aot::error(
        PlatformErrorCode::Unavailable,
        "native-cache-persistence-busy",
    )
}

#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
mod tests;
