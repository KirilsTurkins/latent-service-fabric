//! Same-file response custody. The installed owner retains current read/audit
//! and immutable artifact inputs through physical metadata/frame destruction.

use super::{ProtectedSnapshot, SnapshotFile};
use crate::{
    embedded::{RowKey, StoreError},
    protected_store::{
        custody::ProtectedCustodyJob, ProtectedStoreError, ProtectedStoreOwner,
        RestoreInputPrecondition,
    },
    recovery::snapshot::{inspect_snapshot, RequiredArtifact, SnapshotError, SnapshotReceipt},
    store_io::{StoreIoError, StoreIoKind},
};
use latent_core::native_capacity::{
    NativeBufferClass, NativeBufferPermit, NativeCapacityError, NativeReservation,
};
use std::{
    cell::Cell,
    future::Future,
    pin::Pin,
    sync::Arc,
    task::{Context, Poll},
};

/// Conservative finite charge for the closed decoded manifest, bounded native
/// metadata and one canonical encoded manifest. This is not snapshot payload
/// storage; the private archive remains on the original protected file.
pub const SNAPSHOT_RECEIPT_RESPONSE_BYTES: u64 = 8 * 1024 * 1024;

/// Trusted host composition, never supplied by transport DTOs. The SAME owner
/// retains real current read/audit decisions and catalog/artifact pins. Its
/// final callback holds original short fences before consuming the native gate;
/// none may perform file/guest/provider I/O, clock renewal, audit flush or await.
pub trait SnapshotReceiptOwners: Send + Sync + 'static {
    fn row(&self, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError>;
    fn artifact(&self, artifact: &RequiredArtifact) -> Result<(), StoreError>;
    fn review(&self, receipt: &SnapshotReceipt) -> Result<(), StoreError>;
    fn current(&self) -> Result<(), StoreError>;
    fn accept_read(&self, native: SnapshotReceiptReadFence<'_>) -> Result<(), StoreError>;
}

/// Affine read acceptance on the actual original native reservation. Ignoring
/// this gate cannot publish a retained response. It creates no restore grant.
pub struct SnapshotReceiptReadFence<'a> {
    original: &'a NativeReservation,
    consumed: &'a Cell<bool>,
}
impl SnapshotReceiptReadFence<'_> {
    pub fn accept(self) -> Result<(), StoreError> {
        if self.consumed.get() {
            return Err(StoreError::Invalid);
        }
        self.original
            .with_live(|| self.consumed.set(true))
            .map_err(native_store_error)
    }
}

/// Nonclone result. All decoded metadata and actual policy/artifact inputs
/// precede the prepaid buffer/native owner in destruction order. The transport
/// must carry this owner through the final physical response frame.
pub struct ProtectedSnapshotReceipt {
    receipt: SnapshotReceipt,
    current: Arc<dyn Fn() -> Result<(), StoreError> + Send + Sync>,
    owners: Arc<dyn SnapshotReceiptOwners>,
    buffer: NativeBufferPermit,
    original: Arc<NativeReservation>,
}
impl ProtectedSnapshotReceipt {
    /// Descriptive metadata, not an authorization or retirement proof.
    #[must_use]
    pub const fn receipt(&self) -> &SnapshotReceipt {
        &self.receipt
    }

    #[must_use]
    pub fn response_bytes(&self) -> u64 {
        self.buffer.bytes()
    }

    pub fn check(&self) -> Result<(), SnapshotError> {
        self.original
            .with_live(|| ())
            .map_err(native_snapshot_error)?;
        (self.current)().map_err(SnapshotError::Review)?;
        self.owners.current().map_err(SnapshotError::Review)
    }

    /// Encode only the bounded manifest under its already prepaid response
    /// owner. No raw database/backup payload or client-selected file escapes.
    pub fn encode_manifest(self) -> Result<ProtectedSnapshotManifestFrame, SnapshotError> {
        self.check()?;
        let bytes = self
            .receipt
            .manifest
            .encode()
            .map_err(SnapshotError::Review)?;
        self.check()?;
        Ok(ProtectedSnapshotManifestFrame { bytes, owner: self })
    }
}

/// Suitable for a transport's existing `Bytes::from_owner` path. The encoded
/// bytes die before the original decoded metadata, pins, permit and reservation.
/// No `into_bytes` API detaches those bytes from their actual capacity owner.
pub struct ProtectedSnapshotManifestFrame {
    bytes: Vec<u8>,
    owner: ProtectedSnapshotReceipt,
}
impl ProtectedSnapshotManifestFrame {
    #[must_use]
    pub fn receipt(&self) -> &SnapshotReceipt {
        self.owner.receipt()
    }

    pub fn check(&self) -> Result<(), SnapshotError> {
        self.owner.check()
    }
}
impl AsRef<[u8]> for ProtectedSnapshotManifestFrame {
    fn as_ref(&self) -> &[u8] {
        &self.bytes
    }
}

#[must_use = "accepted receipt read and native response custody survive waiter loss"]
pub struct ProtectedSnapshotReceiptJob {
    inner:
        ProtectedCustodyJob<Option<SnapshotFile>, Result<ProtectedSnapshotReceipt, SnapshotError>>,
}
impl Future for ProtectedSnapshotReceiptJob {
    type Output = Result<
        (
            ProtectedSnapshot,
            Result<Result<ProtectedSnapshotReceipt, SnapshotError>, ProtectedStoreError>,
        ),
        StoreIoError,
    >;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        match Pin::new(&mut self.get_mut().inner).poll(cx) {
            Poll::Ready(Ok((custody, result))) => {
                Poll::Ready(Ok((ProtectedSnapshot { custody }, result)))
            }
            Poll::Ready(Err(error)) => Poll::Ready(Err(error)),
            Poll::Pending => Poll::Pending,
        }
    }
}

impl ProtectedStoreOwner {
    /// Add a retained metadata response to an existing original private
    /// checkpoint. The creator/open/read APIs keep their established contract.
    /// This consumes SAME custody, worker, file and original absolute deadline;
    /// it does not create another engine, pool, grant, path or lease.
    pub fn inspect_retained_snapshot(
        &self,
        snapshot: ProtectedSnapshot,
        expected: RestoreInputPrecondition,
        owners: Arc<dyn SnapshotReceiptOwners>,
    ) -> Result<ProtectedSnapshotReceiptJob, ProtectedStoreError> {
        if expected.snapshot_digest == [0; 32] || expected.manifest_digest == [0; 32] {
            return Err(ProtectedStoreError::InvalidConfiguration);
        }
        let inner = self.with_custody(
            snapshot.custody,
            StoreIoKind::RecoveryRead,
            8 * 1024 * 1024,
            move |file, _| {
                let Some(file) = file else {
                    return Ok(Err(SnapshotError::Review(StoreError::Invalid)));
                };
                if let Err(error) = file.retain_receipt_owner(&owners) {
                    return Ok(Err(SnapshotError::Review(error)));
                }
                // These errors concern the operator input/permission; the
                // enclosing original physical-store fence stays authoritative.
                // This callback reads or mutates no business-engine rows.
                Ok(read(file, &expected, owners))
            },
        )?;
        Ok(ProtectedSnapshotReceiptJob { inner })
    }
}

fn read(
    file: &SnapshotFile,
    expected: &RestoreInputPrecondition,
    owners: Arc<dyn SnapshotReceiptOwners>,
) -> Result<ProtectedSnapshotReceipt, SnapshotError> {
    let original = file.retain_original();
    // Reserve BEFORE the decoder or reviewers allocate their bounded result.
    // Field/local ordering keeps actual metadata destruction before refund.
    let buffer = original
        .reserve_buffer(NativeBufferClass::Response, SNAPSHOT_RECEIPT_RESPONSE_BYTES)
        .map_err(native_snapshot_error)?;
    check_input(file, &owners)?;
    let receipt = inspect_snapshot(&mut file.cursor(), file.deadline(), |key, bytes| {
        owners.row(key, bytes)
    })
    .map_err(|error| {
        file.original()
            .with_live(|| ())
            .map_err(native_snapshot_error)
            .err()
            .unwrap_or(SnapshotError::Review(error))
    })?;
    if receipt.snapshot_digest != expected.snapshot_digest
        || receipt.manifest_digest != expected.manifest_digest
    {
        return Err(SnapshotError::Review(StoreError::Conflict));
    }
    for artifact in &receipt.manifest.metadata.required_artifacts {
        check_input(file, &owners)?;
        owners.artifact(artifact).map_err(SnapshotError::Review)?;
    }
    owners.review(&receipt).map_err(SnapshotError::Review)?;
    check_input(file, &owners)?;
    let consumed = Cell::new(false);
    owners
        .accept_read(SnapshotReceiptReadFence {
            original: &original,
            consumed: &consumed,
        })
        .map_err(|error| {
            if error == StoreError::SnapshotExpired {
                SnapshotError::Deadline
            } else {
                SnapshotError::Review(error)
            }
        })?;
    if !consumed.get() {
        return Err(SnapshotError::Review(StoreError::Invalid));
    }
    let result = ProtectedSnapshotReceipt {
        receipt,
        current: file.retain_current(),
        owners,
        buffer,
        original,
    };
    result.check()?;
    Ok(result)
}

fn check_input(
    file: &SnapshotFile,
    owners: &Arc<dyn SnapshotReceiptOwners>,
) -> Result<(), SnapshotError> {
    file.original()
        .with_live(|| ())
        .map_err(native_snapshot_error)?;
    file.check()
        .map_err(|_| SnapshotError::Review(StoreError::Unavailable))?;
    owners.current().map_err(SnapshotError::Review)
}

fn native_store_error(error: NativeCapacityError) -> StoreError {
    if error == NativeCapacityError::DeadlineExceeded {
        StoreError::SnapshotExpired
    } else {
        StoreError::Unavailable
    }
}

fn native_snapshot_error(error: NativeCapacityError) -> SnapshotError {
    match error {
        NativeCapacityError::DeadlineExceeded => SnapshotError::Deadline,
        NativeCapacityError::BufferLimit
        | NativeCapacityError::BufferTooLarge
        | NativeCapacityError::AllocationFailed => SnapshotError::Capacity,
        _ => SnapshotError::Review(StoreError::Unavailable),
    }
}
