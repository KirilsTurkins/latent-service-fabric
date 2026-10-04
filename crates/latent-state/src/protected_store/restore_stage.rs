//! Finite authenticated import into a physically Fresh, still-private root.
//! Live-engine adoption and explicit effect reconciliation/resume are separate.

use super::{
    checkpoint::CheckpointFile, custody::ProtectedCustodyJob, physical::PhysicalStore,
    snapshot::SnapshotFile, ProtectedCheckpointConfig, ProtectedRestoreInput, ProtectedSnapshot,
    ProtectedSnapshotConfig, ProtectedSnapshotJob, ProtectedStoreConfig, ProtectedStoreError,
    ProtectedStoreOwner, StoreInitializationWitness,
};
use crate::{
    embedded::{AtomicBatch, ExpectedRow, Family, ReadView, RowKey, RowMutation, StoreError},
    namespace::{
        history::{history_key, HISTORY_PREFIX},
        NamespaceRecord, NamespaceStatus,
    },
    recovery::{
        guard_key,
        restore::RestoreWindow,
        snapshot::{
            inspect_snapshot, visit_snapshot_rows, RequiredArtifact, SnapshotError, SnapshotReceipt,
        },
        RecoveryGuard,
    },
    store_identity::{ExternalCheckpoint, StoreIdentity},
    store_io::StoreIoError,
};
use latent_core::native_capacity::NativeReservation;
use sha2::{Digest, Sha256};
use std::{
    cell::Cell,
    future::Future,
    pin::Pin,
    sync::Arc,
    task::{Context, Poll},
};

const WORK_BYTES: u64 = 8 * 1024 * 1024;
const ROOT_RESOURCE_BYTES: u64 = 64 * 1024;
const CONTROL_BYTES: usize = 1024 * 1024;

/// Trusted operator configuration only. Neither paths, configured identity nor
/// logical emptiness are Fresh evidence. The strict initializer proves actual
/// separate empty roots and create-new leaves on the original fixed worker.
pub struct ProtectedRestoreDestinationConfig {
    pub store: ProtectedStoreConfig,
    pub checkpoint: ProtectedCheckpointConfig,
    pub identity: StoreIdentity,
}
impl ProtectedRestoreDestinationConfig {
    fn resource_bytes(&self) -> Result<u64, ProtectedStoreError> {
        let paths = self.store.validate()?;
        let checkpoint = self.checkpoint.validate()?;
        if self.store.root.capacity() > 4096 || self.store.file_name.capacity() > 255 {
            return Err(ProtectedStoreError::InvalidConfiguration);
        }
        u64::try_from(self.store.engine.cache_bytes)
            .ok()
            .and_then(|cache| cache.checked_add(paths))
            .and_then(|bytes| bytes.checked_add(checkpoint))
            .and_then(|bytes| bytes.checked_add(ROOT_RESOURCE_BYTES))
            .ok_or(ProtectedStoreError::InvalidConfiguration)
    }
}

/// The authenticated host supplies immutable attributed operation data. These
/// descriptions grant no restore authority; installed owners must review and
/// consume the actual original native fence at every physical writer boundary.
pub struct RestoreStageRequest {
    pub operation_id: String,
    pub operator_id: String,
    pub runtime_digest: [u8; 32],
    pub loss_window_acknowledgement: [u8; 32],
}
impl RestoreStageRequest {
    fn digest(&self, input: &ProtectedRestoreInput) -> Result<[u8; 32], StoreError> {
        for identity in [&self.operation_id, &self.operator_id] {
            crate::namespace::identity(identity).map_err(|_| StoreError::Invalid)?;
            if identity.capacity() > 256 {
                return Err(StoreError::Capacity);
            }
        }
        if self.runtime_digest == [0; 32]
            || self.runtime_digest != input.snapshot().manifest.metadata.runtime_digest
            || self.loss_window_acknowledgement == [0; 32]
            || self.loss_window_acknowledgement != input.window().digest()?
        {
            return Err(StoreError::Conflict);
        }
        let mut digest = Sha256::new();
        digest.update(b"latent-original-restore-stage-v1\0");
        for identity in [&self.operation_id, &self.operator_id] {
            digest.update((identity.len() as u64).to_be_bytes());
            digest.update(identity.as_bytes());
        }
        digest.update(self.runtime_digest);
        digest.update(self.loss_window_acknowledgement);
        digest.update(input.snapshot().snapshot_digest);
        digest.update(input.snapshot().manifest_digest);
        Ok(digest.finalize().into())
    }
}

pub enum RestoreRowDisposition {
    /// Exact retained business/receipt bytes and immutable IDs remain unchanged.
    Retain,
    /// Archived authority/control is never installed. Its actual current owner
    /// must supply and verify replacement rows in the separate control batch.
    CurrentControl,
}

/// Installed current controls only; no business result/effect row can be edited
/// by this batch. Namespace identity/schema/version and new paused history are
/// independently checked after controls are physically applied.
pub struct RestoreStageControls {
    pub batch: AtomicBatch,
}

/// Separate mandatory original owners; no method defaults to approved. Codec,
/// runtime/immutable artifact, linked quotas/receipts and current controls are
/// reviewed against actual native views. Currentness and writer acceptance are
/// short metadata only, with no guest, disk/network I/O, grant or clock renewal.
pub trait RestoreStageOwners: Send + Sync + 'static {
    fn archive_row(&self, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError>;
    fn required_artifact(&self, artifact: &RequiredArtifact) -> Result<(), StoreError>;
    fn review_input(
        &self,
        current: &ReadView,
        input: &ProtectedRestoreInput,
        request: &RestoreStageRequest,
    ) -> Result<(), StoreError>;
    fn row_disposition(
        &self,
        key: &RowKey,
        bytes: &[u8],
    ) -> Result<RestoreRowDisposition, StoreError>;
    fn stage_controls(
        &self,
        current: &ReadView,
        staged: &ReadView,
        input: &ProtectedRestoreInput,
        request: &RestoreStageRequest,
    ) -> Result<RestoreStageControls, StoreError>;
    /// Full same-unit record/payload/runtime/decoder/artifact/quota validation,
    /// exact fresh dispatch fencing and paused reconciliation state. A retained
    /// old Pending effect may not send before explicit later reconciliation.
    fn verify_staged(
        &self,
        staged: &ReadView,
        input: &ProtectedRestoreInput,
        request: &RestoreStageRequest,
    ) -> Result<(), StoreError>;
    fn dispatch_checkpoint(&self, staged: &ReadView) -> Result<(u64, u64), StoreError>;
    fn protected_clock_epoch(&self) -> Result<u64, StoreError>;
    fn current_role(&self) -> Result<(), StoreError>;
    fn current_audit(&self) -> Result<(), StoreError>;
    fn current_controls(&self) -> Result<(), StoreError>;
    fn current_clock(&self) -> Result<(), StoreError>;
    fn accept(&self, original: RestoreWriteFence<'_>) -> Result<(), StoreError>;
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RestoreWriteKind {
    InitializeIdentity,
    ImportRow,
    InstallControls,
    SealCheckpoint,
}

pub struct RestoreWriteFence<'a> {
    original: &'a NativeReservation,
    consumed: &'a Cell<bool>,
    operation_digest: [u8; 32],
    kind: RestoreWriteKind,
}
impl RestoreWriteFence<'_> {
    #[must_use]
    pub const fn operation_digest(&self) -> [u8; 32] {
        self.operation_digest
    }
    #[must_use]
    pub const fn kind(&self) -> RestoreWriteKind {
        self.kind
    }
    pub fn accept(self) -> Result<(), StoreError> {
        if self.consumed.get() {
            return Err(StoreError::Invalid);
        }
        self.original
            .with_live(|| self.consumed.set(true))
            .map_err(|_| StoreError::SnapshotExpired)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RestoreStageError {
    Review(StoreError),
    Destination(ProtectedStoreError),
    Checkpoint(StoreError),
}

/// Bounded description only. The retained SAME input response permit keeps
/// metadata and original current read owners until physical response drop.
/// No native engine, File, root, execution grant or adoption handle escapes.
pub struct RestoreStageReceipt {
    checkpoint: ExternalCheckpoint,
    operation_digest: [u8; 32],
    imported_rows: u64,
    owners: Arc<dyn RestoreStageOwners>,
    input: ProtectedRestoreInput,
}
impl RestoreStageReceipt {
    #[must_use]
    pub const fn checkpoint(&self) -> &ExternalCheckpoint {
        &self.checkpoint
    }
    #[must_use]
    pub const fn operation_digest(&self) -> [u8; 32] {
        self.operation_digest
    }
    #[must_use]
    pub const fn imported_rows(&self) -> u64 {
        self.imported_rows
    }
    pub fn check(&self) -> Result<(), RestoreStageError> {
        self.input.check().map_err(snapshot_error)?;
        check_owners(self.owners.as_ref()).map_err(RestoreStageError::Review)
    }
}

pub(super) struct RestoreDestination {
    // Both actual native owners die before the SnapshotFile's owner pins and
    // original Native permit. No activation method is provided by this type.
    checkpoint: CheckpointFile,
    store: PhysicalStore,
}

#[derive(Default)]
pub(super) struct RestoreStaging {
    pub(super) config: Option<ProtectedRestoreDestinationConfig>,
    destination: Option<RestoreDestination>,
    attempted: bool,
    sealed: bool,
}

#[cfg(test)]
impl RestoreStaging {
    /// Same fixed-worker inspection only. No native view or destination owner
    /// is returned from this controlled test boundary.
    pub(in crate::protected_store) fn inspect_for_tests(
        &self,
        inspect: impl FnOnce(&ReadView) -> Result<(), StoreError>,
    ) -> Result<(), StoreError> {
        let destination = self.destination.as_ref().ok_or(StoreError::Unavailable)?;
        destination
            .store
            .check()
            .map_err(|_| StoreError::Unavailable)?;
        let view = destination.store.engine().snapshot()?;
        inspect(&view)
    }
}

#[must_use = "accepted import/custody and native destruction survive waiter loss"]
pub struct ProtectedRestoreStageJob {
    inner:
        ProtectedCustodyJob<Option<SnapshotFile>, Result<RestoreStageReceipt, RestoreStageError>>,
}
impl Future for ProtectedRestoreStageJob {
    type Output = Result<
        (
            ProtectedSnapshot,
            Result<Result<RestoreStageReceipt, RestoreStageError>, ProtectedStoreError>,
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
    /// Prepay the actual destination cache/root/checkpoint footprint before any
    /// native allocation, on the SAME existing IO and original Recovery Native
    /// ledgers. Existing 8 MiB scratch/response and absolute deadline remain.
    /// A configuration that cannot fit is refused; no pool/refill/cache shrink.
    pub fn open_snapshot_for_restore(
        &self,
        config: ProtectedSnapshotConfig,
        destination: ProtectedRestoreDestinationConfig,
        original: Arc<NativeReservation>,
        validate_row: impl FnMut(&RowKey, &[u8]) -> Result<(), StoreError> + Send + 'static,
        current: Arc<dyn Fn() -> Result<(), StoreError> + Send + Sync>,
    ) -> Result<ProtectedSnapshotJob, ProtectedStoreError> {
        let bytes = config
            .validate()?
            .checked_add(destination.resource_bytes()?)
            .ok_or(ProtectedStoreError::InvalidConfiguration)?;
        let custody = self.reserve_custody(bytes, WORK_BYTES, Arc::clone(&original))?;
        let inner = self.initialize_custody_with(custody, WORK_BYTES, move |store| {
            let file = match SnapshotFile::open_existing(store, config, original, current) {
                Ok(file) => file,
                Err(SnapshotError::Source(error)) => return Err(error),
                Err(error) => return Ok((None, Err(error))),
            };
            file.restore
                .lock()
                .map_err(|_| StoreError::Unavailable)?
                .config = Some(destination);
            let receipt = inspect_snapshot(&mut file.cursor(), file.deadline(), validate_row)
                .map_err(SnapshotError::Review);
            Ok((Some(file), receipt))
        })?;
        Ok(ProtectedSnapshotJob { inner })
    }

    /// Import into configured physically Fresh staging, never this current
    /// source engine. Same input/file/native ownership, exact loss-window ack,
    /// all original controls and current writer fences are mandatory.
    pub fn stage_restore(
        &self,
        snapshot: ProtectedSnapshot,
        input: ProtectedRestoreInput,
        request: RestoreStageRequest,
        owners: Arc<dyn RestoreStageOwners>,
    ) -> Result<ProtectedRestoreStageJob, ProtectedStoreError> {
        let inner =
            self.with_physical_custody(snapshot.custody, WORK_BYTES, move |file, source| {
                let Some(file) = file else {
                    return Ok(Err(RestoreStageError::Review(StoreError::Invalid)));
                };
                Ok(stage(source, file, input, &request, owners))
            })?;
        Ok(ProtectedRestoreStageJob { inner })
    }
}

fn stage(
    source: &PhysicalStore,
    file: &SnapshotFile,
    input: ProtectedRestoreInput,
    request: &RestoreStageRequest,
    owners: Arc<dyn RestoreStageOwners>,
) -> Result<RestoreStageReceipt, RestoreStageError> {
    if !input.is_from_file(file) {
        return Err(RestoreStageError::Review(StoreError::Conflict));
    }
    {
        let mut held = file
            .restore_owner
            .lock()
            .map_err(|_| RestoreStageError::Review(StoreError::Unavailable))?;
        match held.as_ref() {
            Some(original) if Arc::ptr_eq(original, &owners) => {}
            Some(_) => return Err(RestoreStageError::Review(StoreError::Conflict)),
            None => *held = Some(Arc::clone(&owners)),
        }
    }
    let operation_digest = request.digest(&input).map_err(RestoreStageError::Review)?;
    current(file, &input, owners.as_ref())?;
    let actual = inspect_snapshot(&mut file.cursor(), file.deadline(), |key, bytes| {
        check_owners(owners.as_ref())?;
        owners.archive_row(key, bytes)
    })
    .map_err(RestoreStageError::Review)?;
    if &actual != input.snapshot() {
        return Err(RestoreStageError::Review(StoreError::Conflict));
    }
    for artifact in &actual.manifest.metadata.required_artifacts {
        current(file, &input, owners.as_ref())?;
        owners
            .required_artifact(artifact)
            .map_err(RestoreStageError::Review)?;
    }
    let current_view = source
        .engine()
        .snapshot()
        .map_err(RestoreStageError::Review)?;
    let window = RestoreWindow::capture(&current_view, &actual, file.deadline(), || {
        check_owners(owners.as_ref())?;
        file.original()
            .with_live(|| ())
            .map_err(|_| StoreError::SnapshotExpired)
    })
    .map_err(snapshot_error)?;
    if window.digest().map_err(RestoreStageError::Review)? != request.loss_window_acknowledgement {
        return Err(RestoreStageError::Review(StoreError::Conflict));
    }
    owners
        .review_input(&current_view, &input, request)
        .map_err(RestoreStageError::Review)?;
    let mut staging = file
        .restore
        .lock()
        .map_err(|_| RestoreStageError::Review(StoreError::Unavailable))?;
    if staging.attempted {
        return Err(RestoreStageError::Review(StoreError::Conflict));
    }
    let config = staging
        .config
        .take()
        .ok_or(RestoreStageError::Review(StoreError::Invalid))?;
    if config.identity.encode() == actual.manifest.source_store_identity
        || StoreIdentity::inspect(&current_view)
            .map_err(RestoreStageError::Review)?
            .as_ref()
            == Some(&config.identity)
    {
        return Err(RestoreStageError::Review(StoreError::Conflict));
    }
    staging.attempted = true;
    let destination = PhysicalStore::initialize_restore_destination(
        &config.store,
        source,
        file,
        config.identity.clone(),
        || {
            check_owners(owners.as_ref())?;
            file.check().map_err(|_| StoreError::Unavailable)
        },
        || {
            accept(
                file,
                owners.as_ref(),
                operation_digest,
                RestoreWriteKind::InitializeIdentity,
            )
        },
    )
    .map_err(RestoreStageError::Destination)?;
    if !file
        .is_separate_store(&destination)
        .map_err(RestoreStageError::Review)?
    {
        return Err(RestoreStageError::Review(StoreError::Invalid));
    }
    let fresh = StoreInitializationWitness::take_restore(&destination)
        .map_err(RestoreStageError::Review)?;
    let checkpoint = CheckpointFile::create_restore(
        &destination,
        source,
        file,
        config.checkpoint,
        fresh,
        || current_store(file, owners.as_ref()),
    )
    .map_err(RestoreStageError::Checkpoint)?;
    staging.destination = Some(RestoreDestination {
        checkpoint,
        store: destination,
    });
    let destination = staging
        .destination
        .as_ref()
        .expect("private created destination");
    // Persist closure before the first imported row. Interrupted private work
    // can never look like the pre-recovery ready profile after a later reopen.
    let guard = RecoveryGuard::staging(
        operation_digest,
        actual.snapshot_digest,
        request.loss_window_acknowledgement,
    )
    .map_err(RestoreStageError::Review)?;
    destination
        .store
        .apply_fenced(
            guard.prepare_staging().map_err(RestoreStageError::Review)?,
            || {
                accept(
                    file,
                    owners.as_ref(),
                    operation_digest,
                    RestoreWriteKind::InstallControls,
                )
            },
        )
        .map_err(|error| RestoreStageError::Review(protected_error(error)))?;
    let mut imported_rows = 0;
    visit_snapshot_rows(
        &mut file.cursor(),
        &actual,
        file.deadline(),
        |key, bytes| {
            check_owners(owners.as_ref())?;
            owners.archive_row(key, bytes)
        },
        |key, value| {
            current_store(file, owners.as_ref())?;
            if let Some((key, value)) = imported_row(key, value, &window, owners.as_ref())? {
                let batch = AtomicBatch {
                    expectations: vec![ExpectedRow {
                        key: key.clone(),
                        value: None,
                    }],
                    mutations: vec![RowMutation {
                        key,
                        value: Some(value),
                    }],
                };
                destination
                    .store
                    .apply_fenced(batch, || {
                        accept(
                            file,
                            owners.as_ref(),
                            operation_digest,
                            RestoreWriteKind::ImportRow,
                        )
                    })
                    .map_err(protected_error)?;
                imported_rows += 1;
            }
            Ok(())
        },
    )
    .map_err(RestoreStageError::Review)?;
    current(file, &input, owners.as_ref())?;
    // Legacy snapshots may omit initial NSH rows. Publish every actual reviewed
    // proposed recovery history under an exact absent/existing expectation.
    let view = destination
        .store
        .engine()
        .snapshot()
        .map_err(RestoreStageError::Review)?;
    let mut histories = AtomicBatch::default();
    for namespace in window.namespaces() {
        let proposed = namespace
            .proposed_history()
            .map_err(RestoreStageError::Review)?;
        let key = history_key(&proposed.tenant, &proposed.namespace, proposed.incarnation)
            .map_err(|_| RestoreStageError::Review(StoreError::Corrupt))?;
        let value = proposed
            .encode()
            .map_err(|_| RestoreStageError::Review(StoreError::Corrupt))?;
        let old = view.get(&key).map_err(RestoreStageError::Review)?;
        if old.as_ref() != Some(&value) {
            histories.expectations.push(ExpectedRow {
                key: key.clone(),
                value: old,
            });
            histories.mutations.push(RowMutation {
                key,
                value: Some(value),
            });
        }
    }
    drop(view);
    require_control_batch(&histories).map_err(RestoreStageError::Review)?;
    destination
        .store
        .apply_fenced(histories, || {
            accept(
                file,
                owners.as_ref(),
                operation_digest,
                RestoreWriteKind::InstallControls,
            )
        })
        .map_err(|error| RestoreStageError::Review(protected_error(error)))?;
    let staged_view = destination
        .store
        .engine()
        .snapshot()
        .map_err(RestoreStageError::Review)?;
    let controls = owners
        .stage_controls(&current_view, &staged_view, &input, request)
        .map_err(RestoreStageError::Review)?;
    require_control_batch(&controls.batch).map_err(RestoreStageError::Review)?;
    drop(staged_view);
    drop(current_view);
    destination
        .store
        .apply_fenced(controls.batch, || {
            accept(
                file,
                owners.as_ref(),
                operation_digest,
                RestoreWriteKind::InstallControls,
            )
        })
        .map_err(|error| RestoreStageError::Review(protected_error(error)))?;
    let view = destination
        .store
        .engine()
        .snapshot()
        .map_err(RestoreStageError::Review)?;
    verify_import(file, &view, &actual, &window, owners.as_ref())
        .map_err(RestoreStageError::Review)?;
    if StoreIdentity::inspect(&view)
        .map_err(RestoreStageError::Review)?
        .as_ref()
        != Some(&config.identity)
    {
        return Err(RestoreStageError::Review(StoreError::Corrupt));
    }
    owners
        .verify_staged(&view, &input, request)
        .map_err(RestoreStageError::Review)?;
    if RecoveryGuard::capture(&view)
        .map_err(RestoreStageError::Review)?
        .as_ref()
        != Some(&guard)
    {
        return Err(RestoreStageError::Review(StoreError::Corrupt));
    }
    drop(view);
    destination
        .store
        .apply_fenced(
            guard
                .prepare_completed()
                .map_err(RestoreStageError::Review)?,
            || {
                accept(
                    file,
                    owners.as_ref(),
                    operation_digest,
                    RestoreWriteKind::InstallControls,
                )
            },
        )
        .map_err(|error| RestoreStageError::Review(protected_error(error)))?;
    let view = destination
        .store
        .engine()
        .snapshot()
        .map_err(RestoreStageError::Review)?;
    let completed = RecoveryGuard::capture(&view)
        .map_err(RestoreStageError::Review)?
        .ok_or(RestoreStageError::Review(StoreError::Corrupt))?;
    if completed.status() != crate::recovery::RecoveryStatus::ReconciliationRequired
        || completed.operation_digest() != operation_digest
        || completed.snapshot_digest() != actual.snapshot_digest
        || completed.window_digest() != request.loss_window_acknowledgement
    {
        return Err(RestoreStageError::Review(StoreError::Corrupt));
    }
    let dispatch = owners
        .dispatch_checkpoint(&view)
        .map_err(RestoreStageError::Review)?;
    let epoch = owners
        .protected_clock_epoch()
        .map_err(RestoreStageError::Review)?;
    current(file, &input, owners.as_ref())?;
    let checkpoint = destination
        .checkpoint
        .seal_restore(
            &view,
            epoch,
            dispatch,
            || current_store(file, owners.as_ref()),
            || {
                accept(
                    file,
                    owners.as_ref(),
                    operation_digest,
                    RestoreWriteKind::SealCheckpoint,
                )
            },
        )
        .map_err(RestoreStageError::Checkpoint)?;
    destination
        .store
        .check()
        .map_err(RestoreStageError::Destination)?;
    current(file, &input, owners.as_ref())?;
    staging.sealed = true;
    drop(view);
    drop(staging);
    let receipt = RestoreStageReceipt {
        checkpoint,
        operation_digest,
        imported_rows,
        owners,
        input,
    };
    receipt.check()?;
    Ok(receipt)
}

fn imported_row(
    key: RowKey,
    value: Vec<u8>,
    window: &RestoreWindow,
    owners: &dyn RestoreStageOwners,
) -> Result<Option<(RowKey, Vec<u8>)>, StoreError> {
    if key == StoreIdentity::row_key() {
        return Ok(None);
    }
    if key == guard_key() || archived_control(&key) {
        return Ok(None);
    }
    if key.family == Family::Namespace && key.key.starts_with(HISTORY_PREFIX) {
        let history = crate::namespace::history::NamespaceHistory::decode(&value)
            .map_err(|_| StoreError::Corrupt)?;
        let selected = window
            .namespaces()
            .iter()
            .find(|namespace| {
                namespace.proposed_history().is_ok_and(|proposed| {
                    proposed.tenant == history.tenant
                        && proposed.namespace == history.namespace
                        && proposed.incarnation == history.incarnation
                })
            })
            .ok_or(StoreError::Corrupt)?;
        return Ok(Some((
            key,
            selected
                .proposed_history()?
                .encode()
                .map_err(|_| StoreError::Corrupt)?,
        )));
    }
    if key.family == Family::Namespace && key.key.starts_with(b"ns-v1\0") {
        let mut record = NamespaceRecord::decode(&value).map_err(|_| StoreError::Corrupt)?;
        if record.status == NamespaceStatus::Active {
            record.status = NamespaceStatus::Quiescing;
        }
        return Ok(Some((
            key,
            record.encode().map_err(|_| StoreError::Corrupt)?,
        )));
    }
    match owners.row_disposition(&key, &value)? {
        RestoreRowDisposition::Retain => Ok(Some((key, value))),
        RestoreRowDisposition::CurrentControl if key.family == Family::Maintenance => Ok(None),
        RestoreRowDisposition::CurrentControl => Err(StoreError::Invalid),
    }
}

/// Current authority and mutable accounting are reconstructed by their actual
/// installed owners. Even a codec-valid archive can never restore these rows
/// through a caller classification. Immutable dispatcher receipts remain rows.
fn archived_control(key: &RowKey) -> bool {
    key.family == Family::Maintenance
        && (key == &crate::tenant::guard_key()
            || key.key.starts_with(crate::tenant::QUOTA_PREFIX)
            || [
                b"result-retention-v1\0".as_slice(),
                b"dispatch-owner-v1\0",
                b"dispatch-control-v1\0",
            ]
            .contains(&key.key.as_slice()))
}

fn verify_import(
    file: &SnapshotFile,
    view: &ReadView,
    snapshot: &SnapshotReceipt,
    window: &RestoreWindow,
    owners: &dyn RestoreStageOwners,
) -> Result<(), StoreError> {
    visit_snapshot_rows(
        &mut file.cursor(),
        snapshot,
        file.deadline(),
        |key, bytes| {
            check_owners(owners)?;
            owners.archive_row(key, bytes)
        },
        |key, value| {
            current_store(file, owners)?;
            if let Some((key, value)) = imported_row(key, value, window, owners)? {
                if !view.matches_row(&key, &value)? {
                    return Err(StoreError::Corrupt);
                }
            }
            Ok(())
        },
    )?;
    for namespace in window.namespaces() {
        let history = namespace.proposed_history()?;
        let key = history_key(&history.tenant, &history.namespace, history.incarnation)
            .map_err(|_| StoreError::Corrupt)?;
        if !view.matches_row(&key, &history.encode().map_err(|_| StoreError::Corrupt)?)? {
            return Err(StoreError::Corrupt);
        }
    }
    Ok(())
}

fn require_control_batch(batch: &AtomicBatch) -> Result<(), StoreError> {
    if batch.mutations.capacity() > 512 || batch.expectations.capacity() > 512 {
        return Err(StoreError::Capacity);
    }
    let mut bytes = batch
        .mutations
        .capacity()
        .checked_mul(std::mem::size_of::<RowMutation>())
        .and_then(|bytes| {
            batch
                .expectations
                .capacity()
                .checked_mul(std::mem::size_of::<ExpectedRow>())
                .and_then(|expected| bytes.checked_add(expected))
        })
        .ok_or(StoreError::Capacity)?;
    for row in &batch.mutations {
        if !matches!(row.key.family, Family::Maintenance | Family::Namespace)
            || row.key == StoreIdentity::row_key()
            || row.key == guard_key()
            || row.key.family == Family::Namespace && !row.key.key.starts_with(HISTORY_PREFIX)
        {
            return Err(StoreError::Invalid);
        }
        bytes = bytes
            .checked_add(row.key.key.capacity())
            .and_then(|count| count.checked_add(row.value.as_ref().map_or(0, Vec::capacity)))
            .ok_or(StoreError::Capacity)?;
    }
    for row in &batch.expectations {
        bytes = bytes
            .checked_add(row.key.key.capacity())
            .and_then(|count| count.checked_add(row.value.as_ref().map_or(0, Vec::capacity)))
            .ok_or(StoreError::Capacity)?;
    }
    if bytes > CONTROL_BYTES {
        return Err(StoreError::Capacity);
    }
    Ok(())
}

fn check_owners(owners: &dyn RestoreStageOwners) -> Result<(), StoreError> {
    owners.current_role()?;
    owners.current_audit()?;
    owners.current_controls()?;
    owners.current_clock()
}
fn current_store(file: &SnapshotFile, owners: &dyn RestoreStageOwners) -> Result<(), StoreError> {
    check_owners(owners)?;
    file.check().map_err(|_| StoreError::Unavailable)
}
fn current(
    file: &SnapshotFile,
    input: &ProtectedRestoreInput,
    owners: &dyn RestoreStageOwners,
) -> Result<(), RestoreStageError> {
    current_store(file, owners).map_err(RestoreStageError::Review)?;
    input.check().map_err(snapshot_error)
}
fn accept(
    file: &SnapshotFile,
    owners: &dyn RestoreStageOwners,
    operation_digest: [u8; 32],
    kind: RestoreWriteKind,
) -> Result<(), StoreError> {
    current_store(file, owners)?;
    let consumed = Cell::new(false);
    owners.accept(RestoreWriteFence {
        original: file.original(),
        consumed: &consumed,
        operation_digest,
        kind,
    })?;
    if !consumed.get() {
        return Err(StoreError::Invalid);
    }
    Ok(())
}
fn protected_error(error: super::ProtectedFencedStoreError<StoreError>) -> StoreError {
    match error {
        super::ProtectedFencedStoreError::Fence(error) => error,
        super::ProtectedFencedStoreError::Store(ProtectedStoreError::Store(error)) => error,
        super::ProtectedFencedStoreError::Store(_) => StoreError::CommitUncertain,
    }
}
fn snapshot_error(error: SnapshotError) -> RestoreStageError {
    RestoreStageError::Review(match error {
        SnapshotError::Source(error) | SnapshotError::Review(error) => error,
        SnapshotError::Deadline => StoreError::SnapshotExpired,
        SnapshotError::Capacity => StoreError::Capacity,
        SnapshotError::Output => StoreError::Unavailable,
    })
}
