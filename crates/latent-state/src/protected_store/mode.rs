//! Closed state-mode evidence on the same protected recovery writer.

use std::sync::Arc;

use latent_core::native_capacity::{
    NativeAdmissionClass, NativeBufferClass, NativeBufferPermit, NativeReservation,
};

use super::{ProtectedStoreError, ProtectedStoreOwner};
use crate::store_identity::StoreIdentity;
use crate::store_io::{StoreIoJob, StoreIoKind};

pub const STATE_MODE_FILE: &str = "STATE_OWNER_MODE";
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub(super) const FORMAT: &[u8] = b"LSM\0\x01";
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub(super) const MAXIMUM_BYTES: usize = FORMAT.len() + crate::store_identity::MAXIMUM_ENCODED_BYTES;
/// Exact bounded native Work prepaid for the closed marker operation.
pub const STATE_MODE_NATIVE_BYTES: u64 = 32 * 1024;

struct ModeKeeper {
    _buffer: NativeBufferPermit,
    original: Arc<NativeReservation>,
}

/// Evidence for this bounded operation, never a state or restore grant.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct StateModeObservation {
    pub created_here: bool,
}

impl ProtectedStoreOwner {
    /// Verify the fixed mode leaf through the actual protected business root.
    /// Missing creation requires the initializer's real fresh identity still
    /// retained in this exclusive startup and one coherent view still contains
    /// only its identity row. Matching reopened bytes cannot mint that
    /// permission. This does not consume the checkpoint's affine witness.
    /// All descriptors, buffers and original capacity retire on the same fixed
    /// recovery writer, including a detached response or failed partial write.
    pub fn ensure_state_mode_marker(
        &self,
        identity: StoreIdentity,
        original: Arc<NativeReservation>,
    ) -> Result<StoreIoJob<Result<StateModeObservation, ProtectedStoreError>>, ProtectedStoreError>
    {
        self.ensure_state_mode_marker_inner(identity, original, || {})
    }

    pub(super) fn ensure_state_mode_marker_inner(
        &self,
        identity: StoreIdentity,
        original: Arc<NativeReservation>,
        before_native_retirement: impl FnOnce() + Send + 'static,
    ) -> Result<StoreIoJob<Result<StateModeObservation, ProtectedStoreError>>, ProtectedStoreError>
    {
        self.available()?;
        if original.class() != NativeAdmissionClass::Recovery
            || !original.is_from_owner(&self.native_capacity()?)
        {
            return Err(ProtectedStoreError::InvalidConfiguration);
        }
        original
            .with_live(|| ())
            .map_err(|_| ProtectedStoreError::InvalidConfiguration)?;
        let keeper = Arc::new(ModeKeeper {
            _buffer: original
                .reserve_buffer(NativeBufferClass::Work, STATE_MODE_NATIVE_BYTES)
                .map_err(|_| ProtectedStoreError::InvalidConfiguration)?,
            original,
        });
        self.ready
            .submit_retaining(
                StoreIoKind::RecoveryWrite,
                STATE_MODE_NATIVE_BYTES,
                keeper.clone(),
                move |store| {
                    store.with_store(StoreIoKind::RecoveryWrite, |_| {
                        store.ensure_state_mode_marker(
                            &identity,
                            &keeper.original,
                            before_native_retirement,
                        )
                    })
                },
            )
            .map_err(ProtectedStoreError::Io)
    }
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub(super) fn require_initializer_only(
    view: &crate::embedded::ReadView,
    identity: &StoreIdentity,
) -> Result<(), crate::embedded::StoreError> {
    use crate::embedded::{Family, StoreError};

    for family in [
        Family::Namespace,
        Family::State,
        Family::Tombstone,
        Family::Command,
        Family::Result,
        Family::Outbox,
        Family::Attempt,
        Family::Inbox,
        Family::PayloadReference,
    ] {
        // No arbitrarily large stored value is copied into the marker's
        // 32 KiB native reservation just to determine that it is not fresh.
        if view.contains_prefix(family, b"")? {
            return Err(StoreError::Conflict);
        }
    }
    let page = view
        .scan_after(Family::Maintenance, b"", None, 1, 4096)
        .map_err(|error| match error {
            StoreError::Capacity => StoreError::Conflict,
            other => other,
        })?;
    if page.resume.is_some()
        || page.rows.as_slice() != [(StoreIdentity::row_key(), identity.encode())]
    {
        return Err(StoreError::Conflict);
    }
    Ok(())
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub(super) fn encoded(identity: &StoreIdentity) -> Vec<u8> {
    let identity = identity.encode();
    let mut bytes = Vec::with_capacity(FORMAT.len() + identity.len());
    bytes.extend_from_slice(FORMAT);
    bytes.extend_from_slice(&identity);
    bytes
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub(super) fn ensure_native(
    root: &latent_protected_files::ProtectedRoot,
    identity: &StoreIdentity,
    actual_fresh_identity: bool,
    original: &NativeReservation,
    before_native_retirement: impl FnOnce(),
) -> Result<StateModeObservation, crate::embedded::StoreError> {
    use crate::embedded::StoreError;
    use std::os::unix::fs::FileExt;

    let expected = encoded(identity);
    let maximum = u64::try_from(MAXIMUM_BYTES).expect("closed mode marker bound");
    original
        .with_live(|| ())
        .map_err(|_| StoreError::Conflict)?;
    let (file, fence, created_here) = if actual_fresh_identity {
        match root.create_mutable_file(STATE_MODE_FILE, maximum) {
            Ok((file, fence)) => (file, fence, true),
            // Any existing, failed or racing entry is inspected byte exactly;
            // it is never truncated, removed or silently adopted as empty.
            Err(_) => {
                let (file, fence) = root
                    .open_mutable_file(STATE_MODE_FILE, maximum, false)
                    .map_err(|_| StoreError::Unavailable)?;
                (file, fence, false)
            }
        }
    } else {
        let (file, fence) = root
            .open_mutable_file(STATE_MODE_FILE, maximum, false)
            .map_err(|_| StoreError::Unavailable)?;
        (file, fence, false)
    };
    root.check_mutable_file(&fence)
        .map_err(|_| StoreError::Unavailable)?;
    original.with_live(|| ()).map_err(|_| {
        if created_here {
            StoreError::CommitUncertain
        } else {
            StoreError::Conflict
        }
    })?;
    if created_here {
        if file.metadata().map_err(|_| StoreError::Unavailable)?.len() != 0 {
            return Err(StoreError::Corrupt);
        }
        // Partial or uncertain initialization remains difficult existing data.
        // No later startup erases it or recreates a missing reopened marker.
        file.write_all_at(&expected, 0)
            .map_err(|_| StoreError::CommitUncertain)?;
        file.sync_all().map_err(|_| StoreError::CommitUncertain)?;
    }
    let length = file.metadata().map_err(|_| StoreError::Unavailable)?.len();
    if length != u64::try_from(expected.len()).expect("bounded marker") {
        return Err(StoreError::Corrupt);
    }
    let mut bytes = vec![0; expected.len()];
    file.read_exact_at(&mut bytes, 0)
        .map_err(|_| StoreError::Unavailable)?;
    if !bytes.starts_with(FORMAT) {
        return Err(StoreError::UnsupportedFormat);
    }
    if bytes != expected {
        return Err(StoreError::Corrupt);
    }
    root.check_mutable_file(&fence)
        .map_err(|_| StoreError::CommitUncertain)?;
    original.with_live(|| ()).map_err(|_| {
        if created_here {
            StoreError::CommitUncertain
        } else {
            StoreError::Conflict
        }
    })?;
    before_native_retirement();
    drop(bytes);
    drop(expected);
    drop(file);
    Ok(StateModeObservation { created_here })
}
