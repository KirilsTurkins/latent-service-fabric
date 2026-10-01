use super::file::ProtectedSnapshotFile;
use super::*;
use crate::{
    embedded::{AtomicBatch, EmbeddedStore},
    recovery::{
        restore::{RestoreChecks, RestorePlan},
        snapshot::{export_snapshot, inspect_snapshot, validate_deadline},
    },
    store_io::{StoreIoJob, StoreIoKind},
};
use latent_protected_files::ProtectedRoot;
use std::{
    pin::Pin,
    sync::atomic::Ordering,
    task::{Context, Poll},
};

type PhysicalResult<T> = Result<Result<T, OfflineRecoveryError>, ProtectedStoreError>;

#[must_use = "dropping the waiter does not cancel accepted physical recovery work"]
pub struct OfflineOperation<T> {
    inner: StoreIoJob<PhysicalResult<T>>,
}
impl<T> Future for OfflineOperation<T> {
    type Output = Result<T, OfflineRecoveryError>;
    fn poll(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Self::Output> {
        match Pin::new(&mut self.get_mut().inner).poll(context) {
            Poll::Ready(Ok(Ok(result))) => Poll::Ready(result),
            Poll::Ready(Ok(Err(error))) => Poll::Ready(Err(OfflineRecoveryError::Protected(error))),
            Poll::Ready(Err(error)) => Poll::Ready(Err(OfflineRecoveryError::Protected(
                ProtectedStoreError::Io(error),
            ))),
            Poll::Pending => Poll::Pending,
        }
    }
}

struct Busy(Arc<AtomicBool>);
impl Busy {
    fn accept(source: &OfflineRecoverySource) -> Result<Self, OfflineRecoveryError> {
        source
            .busy
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| OfflineRecoveryError::Busy)?;
        Ok(Self(Arc::clone(&source.busy)))
    }
}
impl Drop for Busy {
    fn drop(&mut self) {
        self.0.store(false, Ordering::Release);
    }
}

pub(super) fn backup(
    source: &OfflineRecoverySource,
    output: SnapshotFile,
    metadata: SnapshotMetadata,
    deadline: Instant,
) -> Result<OfflineOperation<SnapshotReceipt>, OfflineRecoveryError> {
    validate_deadline(deadline).map_err(OfflineRecoveryError::Input)?;
    metadata.validate().map_err(OfflineRecoveryError::Input)?;
    if metadata.runtime_digest != source.codecs.runtime_digest() {
        return Err(OfflineRecoveryError::InvalidConfiguration);
    }
    // Copy only bounded actual members before queueing. Spare host allocation
    // capacity is not retained by the accepted physical operation.
    let compact = metadata.clone();
    drop(metadata);
    let metadata = compact;
    if metadata.tenant != source.tenant {
        return Err(OfflineRecoveryError::InvalidConfiguration);
    }
    let installed: std::collections::BTreeSet<_> =
        source.codecs.installed_formats().iter().collect();
    if installed != metadata.decoder_formats.iter().collect() {
        return Err(OfflineRecoveryError::InvalidConfiguration);
    }
    let bytes = OPERATION_SCRATCH_BYTES
        .checked_add(source.codecs.scratch_bytes())
        .and_then(|bytes| {
            ProtectedSnapshotFile::validate(&output)
                .ok()
                .and_then(|paths| bytes.checked_add(paths))
        })
        .ok_or(OfflineRecoveryError::InvalidConfiguration)?;
    let busy = Busy::accept(source)?;
    let codecs = Arc::clone(&source.codecs);
    let source_root = source.source_root.clone();
    let inner = source
        .owner
        .with_store(StoreIoKind::Read, bytes, move |store| {
            let _busy = busy;
            let view = store.snapshot()?;
            let reviewed = codecs.review_backup(&view, &metadata, &output);
            drop(view);
            // Destination/input failure is separate from the actual source engine:
            // it must not poison or replace an otherwise valid current store.
            Ok(reviewed
                .map_err(OfflineRecoveryError::Review)
                .and_then(|()| {
                    let root = ProtectedRoot::open(&source_root)
                        .map_err(|_| OfflineRecoveryError::UnsafeDestination)?;
                    let mut file = ProtectedSnapshotFile::open(&output, root.identity(), true)?;
                    let receipt = export_snapshot(
                        store,
                        metadata,
                        &mut file,
                        deadline,
                        |view| codecs.validate_view(view),
                        |artifact| codecs.verify_artifact(artifact),
                    )
                    .map_err(OfflineRecoveryError::Input)?;
                    file.sync()?;
                    file.rewind()?;
                    let view = store.snapshot().map_err(OfflineRecoveryError::Input)?;
                    let observed = inspect_snapshot(&mut file, deadline, |key, value| {
                        codecs.validate_row(&view, key, value)
                    })
                    .map_err(OfflineRecoveryError::Input)?;
                    if observed != receipt {
                        return Err(OfflineRecoveryError::Input(StoreError::Corrupt));
                    }
                    Ok(receipt)
                }))
        })
        .map_err(OfflineRecoveryError::Protected)?;
    Ok(OfflineOperation { inner })
}

pub(super) fn restore(
    source: &OfflineRecoverySource,
    request: OfflineRestoreRequest,
    deadline: Instant,
) -> Result<OfflineOperation<OfflineRestoreReceipt>, OfflineRecoveryError> {
    validate_deadline(deadline).map_err(OfflineRecoveryError::Input)?;
    let bytes = restore_charge(source, &request)?;
    let busy = Busy::accept(source)?;
    let codecs = Arc::clone(&source.codecs);
    let source_root = source.source_root.clone();
    let inner = source
        .owner
        .with_store(StoreIoKind::Read, bytes, move |store| {
            let _busy = busy;
            let current = store.snapshot()?;
            Ok(restore_worker(
                &current,
                &source_root,
                request,
                &*codecs,
                deadline,
            ))
        })
        .map_err(OfflineRecoveryError::Protected)?;
    Ok(OfflineOperation { inner })
}

pub(super) fn inspect(
    source: &OfflineRecoverySource,
    request: OfflineRestoreRequest,
    deadline: Instant,
) -> Result<OfflineOperation<OfflineRestoreInspection>, OfflineRecoveryError> {
    validate_deadline(deadline).map_err(OfflineRecoveryError::Input)?;
    let bytes = restore_charge(source, &request)?;
    let busy = Busy::accept(source)?;
    let codecs = Arc::clone(&source.codecs);
    let source_root = source.source_root.clone();
    let inner = source
        .owner
        .with_store(StoreIoKind::Read, bytes, move |store| {
            let _busy = busy;
            let current = store.snapshot()?;
            Ok((|| {
                let (_, _, snapshot) =
                    inspect_worker(&current, &source_root, &request, &*codecs, deadline)?;
                let window = RestoreWindow::capture_until(&current, &snapshot, deadline)
                    .map_err(OfflineRecoveryError::Input)?;
                super::super::restore::require_snapshot_capacity(
                    &snapshot,
                    request.destination.engine,
                )
                .map_err(OfflineRecoveryError::Target)?;
                Ok(OfflineRestoreInspection { snapshot, window })
            })())
        })
        .map_err(OfflineRecoveryError::Protected)?;
    Ok(OfflineOperation { inner })
}

fn restore_charge(
    source: &OfflineRecoverySource,
    request: &OfflineRestoreRequest,
) -> Result<u64, OfflineRecoveryError> {
    request
        .destination
        .validate()
        .map_err(OfflineRecoveryError::Protected)?;
    for identity in [&request.review.operation_id, &request.review.operator_id] {
        crate::namespace::identity(identity)
            .map_err(|_| OfflineRecoveryError::InvalidConfiguration)?;
    }
    if request.review.runtime_digest != source.codecs.runtime_digest()
        || request.review.snapshot_digest == [0; 32]
    {
        return Err(OfflineRecoveryError::InvalidConfiguration);
    }
    if request.destination.engine.cache_bytes > 8 * 1024 * 1024 {
        return Err(OfflineRecoveryError::InvalidConfiguration);
    }
    let strings = request
        .review
        .operation_id
        .capacity()
        .checked_add(request.review.operator_id.capacity())
        .and_then(|bytes| bytes.checked_add(request.destination.root.capacity()))
        .and_then(|bytes| bytes.checked_add(request.destination.file_name.capacity()))
        .ok_or(OfflineRecoveryError::InvalidConfiguration)?;
    let paths = ProtectedSnapshotFile::validate(&request.input)?
        .checked_add(
            u64::try_from(strings).map_err(|_| OfflineRecoveryError::InvalidConfiguration)?,
        )
        .ok_or(OfflineRecoveryError::InvalidConfiguration)?;
    OPERATION_SCRATCH_BYTES
        .checked_add(source.codecs.scratch_bytes())
        .and_then(|bytes| bytes.checked_add(paths))
        .ok_or(OfflineRecoveryError::InvalidConfiguration)
}

fn restore_worker(
    current: &ReadView,
    source_root: &std::path::Path,
    request: OfflineRestoreRequest,
    codecs: &dyn RecoveryCodecs,
    deadline: Instant,
) -> Result<OfflineRestoreReceipt, OfflineRecoveryError> {
    let (root, mut input, snapshot) =
        inspect_worker(current, source_root, &request, codecs, deadline)?;
    let snapshot_digest = snapshot.snapshot_digest;
    let manifest_digest = snapshot.manifest_digest;
    let plan =
        RestorePlan::prepare_until(current, snapshot, &request.review, deadline, |window, _| {
            codecs.review_restore(current, window, &request)
        })
        .map_err(OfflineRecoveryError::Review)?;
    plan.require_capacity(request.destination.engine)
        .map_err(OfflineRecoveryError::Target)?;
    input.rewind()?;
    validate_deadline(deadline).map_err(OfflineRecoveryError::Input)?;
    let mut destination =
        Destination::create(&request.destination, [root.identity(), input.identity()])?;
    let guard = plan
        .execute_checked(
            &mut input,
            destination.engine.as_ref().expect("live selected engine"),
            deadline,
            RestoreChecks {
                row: |key: &RowKey, value: &[u8]| codecs.validate_row(current, key, value),
                view: |view: &ReadView| codecs.validate_view(view),
                fence: || destination.check().map_err(|_| StoreError::Unavailable),
            },
        )
        .map_err(OfflineRecoveryError::Target)?;
    let destination_identity = destination.root.identity();
    destination.finish()?;
    Ok(OfflineRestoreReceipt {
        guard,
        snapshot_digest,
        manifest_digest,
        destination_identity,
    })
}

fn inspect_worker(
    current: &ReadView,
    source_root: &std::path::Path,
    request: &OfflineRestoreRequest,
    codecs: &dyn RecoveryCodecs,
    deadline: Instant,
) -> Result<(ProtectedRoot, ProtectedSnapshotFile, SnapshotReceipt), OfflineRecoveryError> {
    validate_deadline(deadline).map_err(OfflineRecoveryError::Input)?;
    codecs
        .authorize_inspection(current, request)
        .map_err(OfflineRecoveryError::Review)?;
    let root =
        ProtectedRoot::open(source_root).map_err(|_| OfflineRecoveryError::UnsafeDestination)?;
    let mut input = ProtectedSnapshotFile::open(&request.input, root.identity(), false)?;
    let snapshot = inspect_snapshot(&mut input, deadline, |key, value| {
        if key.key.len() > request.destination.engine.maximum_key_bytes
            || value.len() > request.destination.engine.maximum_value_bytes
        {
            return Err(StoreError::Capacity);
        }
        codecs.validate_row(current, key, value)
    })
    .map_err(OfflineRecoveryError::Input)?;
    if snapshot.snapshot_digest != request.review.snapshot_digest {
        return Err(OfflineRecoveryError::Input(StoreError::Corrupt));
    }
    if snapshot.manifest.metadata.runtime_digest != codecs.runtime_digest() {
        return Err(OfflineRecoveryError::Input(StoreError::UnsupportedFormat));
    }
    snapshot
        .manifest
        .inventory()
        .map_err(OfflineRecoveryError::Input)?
        .require_decoders(codecs.installed_formats())
        .map_err(|_| OfflineRecoveryError::Input(StoreError::UnsupportedFormat))?;
    for artifact in &snapshot.manifest.metadata.required_artifacts {
        codecs
            .verify_artifact(artifact)
            .map_err(OfflineRecoveryError::Input)?;
    }
    Ok((root, input, snapshot))
}

struct Destination {
    engine: Option<EmbeddedStore>,
    root: ProtectedRoot,
    fence: latent_protected_files::ProtectedMutableFile,
    lock: std::fs::File,
    lock_fence: latent_protected_files::ProtectedMutableFile,
    status: crate::embedded::StoreFileStatus,
}
impl Destination {
    fn create(
        config: &ProtectedStoreConfig,
        excluded_roots: [(u64, u64); 2],
    ) -> Result<Self, OfflineRecoveryError> {
        let root = ProtectedRoot::open(&config.root)
            .map_err(|_| OfflineRecoveryError::UnsafeDestination)?;
        if excluded_roots.contains(&root.identity())
            || root
                .filesystem_type()
                .map_err(|_| OfflineRecoveryError::UnsafeDestination)?
                != 0xef53
        {
            return Err(OfflineRecoveryError::UnsafeDestination);
        }
        let (lock, lock_fence) = root
            .open_mutable_file("transaction-owner.lock", 1, true)
            .map_err(|_| OfflineRecoveryError::UnsafeDestination)?;
        lock.try_lock()
            .map_err(|_| OfflineRecoveryError::UnsafeDestination)?;
        let (file, fence) = root
            .create_mutable_file(&config.file_name, config.maximum_file_bytes)
            .map_err(|_| OfflineRecoveryError::UnsafeDestination)?;
        let (engine, status) =
            EmbeddedStore::open_bounded_file(file, config.engine, config.maximum_file_bytes)
                .map_err(OfflineRecoveryError::Target)?;
        Ok(Self {
            engine: Some(engine),
            root,
            fence,
            lock,
            lock_fence,
            status,
        })
    }
    fn finish(&mut self) -> Result<(), OfflineRecoveryError> {
        self.engine
            .as_ref()
            .expect("live selected engine")
            .apply(AtomicBatch::default())
            .map_err(OfflineRecoveryError::Target)?;
        self.check()?;
        drop(self.engine.take());
        if self.status.close_failed() || !self.status.close_observed() {
            return Err(OfflineRecoveryError::Target(StoreError::CommitUncertain));
        }
        self.check()?;
        self.lock
            .unlock()
            .map_err(|_| OfflineRecoveryError::Target(StoreError::CommitUncertain))
    }
    fn check(&self) -> Result<(), OfflineRecoveryError> {
        self.root
            .check_mutable_file(&self.lock_fence)
            .and_then(|()| self.root.check_mutable_file(&self.fence))
            .map_err(|_| OfflineRecoveryError::UnsafeDestination)
    }
}
impl Drop for Destination {
    fn drop(&mut self) {
        drop(self.engine.take());
    }
}
