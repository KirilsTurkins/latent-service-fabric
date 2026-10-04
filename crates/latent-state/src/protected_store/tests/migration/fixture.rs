use super::*;
use crate::{
    embedded::{ReadView, RowKey},
    recovery::{
        migration::{
            tests::fixture as logical, AggregateMigrationObservation, AggregateMigrationRecipe,
            AggregateMigrationRequest, NamespaceMigrationView,
        },
        snapshot::{visit_view, RequiredArtifact, SnapshotClosure},
    },
    store_identity::StoreIdentity,
    tenant::{GlobalMetadataAllowance, TenantCensus},
};
use latent_core::{
    native_capacity::{
        NativeAdmissionClass, NativeCapacityOwner, NativeReservation, NativeReservationRequest,
    },
    test_support::coordination::PauseTicket,
    SystemActivationClock,
};
use std::{
    path::Path,
    sync::{
        atomic::{AtomicBool, AtomicU8, AtomicUsize},
        Mutex,
    },
    time::Duration,
};

pub(super) struct Seed {
    inputs: logical::Inputs,
    rows: Vec<(RowKey, Vec<u8>)>,
}

pub(super) struct Setup {
    root: tempfile::TempDir,
    target: tempfile::TempDir,
    config: ProtectedStoreConfig,
    clock: Arc<dyn ActivationClock>,
    response_bytes: u64,
    work_bytes: u64,
    pub owner: ProtectedStoreOwner,
    pub native: NativeCapacityOwner,
    original: Option<Arc<NativeReservation>>,
    pub seed: Arc<Seed>,
}

mod restore;
pub(super) use restore::StageOwners;

pub(super) struct Observed {
    pub progress: Option<Vec<u8>>,
    pub value: Vec<u8>,
    pub status: NamespaceStatus,
    pub history: HistoryStatus,
}

pub(super) struct Owners {
    seed: Arc<Seed>,
    pub accept_mode: AtomicU8,
    pub source_fault: AtomicBool,
    pub archive_reads: AtomicUsize,
    pub read_acceptances: AtomicUsize,
    pause: Mutex<Option<(Rendezvous, mpsc::Sender<PauseTicket>)>>,
}

impl Owners {
    pub fn new(seed: Arc<Seed>) -> Self {
        Self {
            seed,
            accept_mode: AtomicU8::new(0),
            source_fault: AtomicBool::new(false),
            archive_reads: AtomicUsize::new(0),
            read_acceptances: AtomicUsize::new(0),
            pause: Mutex::new(None),
        }
    }

    pub fn pause_review(&self) -> (Rendezvous, mpsc::Receiver<PauseTicket>) {
        let gates = Rendezvous::new(1);
        let (notice, receiver) = mpsc::channel();
        assert!(self
            .pause
            .lock()
            .unwrap()
            .replace((gates.clone(), notice))
            .is_none());
        (gates, receiver)
    }
}

impl AggregateMigrationOwners for Owners {
    fn row(&self, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
        // The bounded archive must retain these exact original, producer-
        // validated fixture rows; even a canonical substituted row refuses.
        if self
            .seed
            .rows
            .iter()
            .any(|(original, value)| original == key && value == bytes)
        {
            Ok(())
        } else {
            Err(StoreError::Corrupt)
        }
    }

    fn linked(&self, view: &ReadView) -> Result<SnapshotClosure, MigrationError> {
        if self.source_fault.load(Ordering::SeqCst) {
            return Err(MigrationError::Source(StoreError::CommitUncertain));
        }
        logical::closure(view, self.seed.inputs.metadata.required_artifacts.clone())
            .map_err(MigrationError::source)
    }

    fn artifact(&self, artifact: &RequiredArtifact) -> Result<(), StoreError> {
        if self
            .seed
            .inputs
            .metadata
            .required_artifacts
            .contains(artifact)
        {
            Ok(())
        } else {
            Err(StoreError::UnsupportedFormat)
        }
    }

    fn review(
        &self,
        _: &ReadView,
        request: &AggregateMigrationRequest,
        observation: AggregateMigrationObservation<'_>,
    ) -> Result<(), StoreError> {
        if request.package_digest != self.seed.inputs.request.package_digest
            || request.review_digest != self.seed.inputs.request.review_digest
            || observation.schema.declaration_digest()
                != self.seed.inputs.schema.declaration_digest()
        {
            return Err(StoreError::UnsupportedFormat);
        }
        let pause = self.pause.lock().unwrap().take();
        if let Some((gates, notice)) = pause {
            pause_review(&gates, notice);
        }
        Ok(())
    }

    fn accept(&self, native: MigrationCommitFence<'_>) -> Result<(), StoreError> {
        match self.accept_mode.load(Ordering::SeqCst) {
            0 => native.accept(),
            1 => Err(StoreError::Unavailable),
            2 => Ok(()), // Writer must independently reject this ignored gate.
            _ => Err(StoreError::Invalid),
        }
    }

    fn review_resume(
        &self,
        _: &ReadView,
        request: &crate::recovery::resume::MigrationResumeRequest,
        observation: crate::recovery::resume::MigrationResumeObservation<'_>,
        _: &SnapshotClosure,
    ) -> Result<(), StoreError> {
        if request.migration.package_digest != self.seed.inputs.request.package_digest
            || observation.schema.declaration_digest()
                != self.seed.inputs.schema.declaration_digest()
            || !observation.progress.completed()
        {
            return Err(StoreError::UnsupportedFormat);
        }
        let pause = self.pause.lock().unwrap().take();
        if let Some((gates, notice)) = pause {
            pause_review(&gates, notice);
        }
        Ok(())
    }

    fn accept_resume(&self, native: MigrationResumeCommitFence<'_>) -> Result<(), StoreError> {
        match self.accept_mode.load(Ordering::SeqCst) {
            0 => native.accept(),
            1 => Err(StoreError::Unavailable),
            2 => Ok(()),
            _ => Err(StoreError::UnsupportedFormat),
        }
    }
}

impl RestoreInputOwners for Owners {
    fn archive_row(&self, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
        self.archive_reads.fetch_add(1, Ordering::SeqCst);
        self.row(key, bytes)
    }
    fn current_closure(&self, view: &ReadView) -> Result<SnapshotClosure, SnapshotError> {
        self.linked(view).map_err(|error| match error {
            MigrationError::Source(error) => SnapshotError::Source(error),
            MigrationError::Review(error) => SnapshotError::Review(error),
            MigrationError::Deadline => SnapshotError::Deadline,
            MigrationError::Capacity => SnapshotError::Capacity,
        })
    }
    fn required_artifact(&self, artifact: &RequiredArtifact) -> Result<(), StoreError> {
        self.artifact(artifact)
    }
    fn review_window(
        &self,
        _: &ReadView,
        window: &crate::recovery::restore::RestoreWindow,
    ) -> Result<(), StoreError> {
        if window.namespaces().len() != 1 {
            return Err(StoreError::Conflict);
        }
        let pause = self.pause.lock().unwrap().take();
        if let Some((gates, notice)) = pause {
            pause_review(&gates, notice);
        }
        Ok(())
    }
    fn accept_read(&self, original: RestoreReadFence<'_>) -> Result<(), StoreError> {
        self.read_acceptances.fetch_add(1, Ordering::SeqCst);
        match self.accept_mode.load(Ordering::SeqCst) {
            0 => original.accept(),
            1 => Err(StoreError::Unavailable),
            2 => Ok(()),
            _ => Err(StoreError::Invalid),
        }
    }

    fn current(&self) -> Result<(), StoreError> {
        if self.accept_mode.load(Ordering::SeqCst) == 1 {
            Err(StoreError::Unavailable)
        } else {
            Ok(())
        }
    }
}

impl Setup {
    pub fn new() -> Self {
        Self::with_clock(Arc::new(SystemActivationClock))
    }

    pub fn with_clock(clock: Arc<dyn ActivationClock>) -> Self {
        Self::with_response(clock, 1024 * 1024)
    }

    pub fn with_restore_response() -> Self {
        Self::with_response(
            Arc::new(SystemActivationClock),
            RESTORE_INPUT_RESPONSE_BYTES,
        )
    }

    pub fn with_response(clock: Arc<dyn ActivationClock>, response_bytes: u64) -> Self {
        Self::with_admission(clock, response_bytes, 9 * 1024 * 1024)
    }

    /// Selected restore input at ORIGINAL admission, within the unchanged
    /// 32 MiB Recovery partition. Existing migration fixtures keep 9 MiB work.
    pub fn with_restore_destination() -> Self {
        Self::with_admission(
            Arc::new(SystemActivationClock),
            RESTORE_INPUT_RESPONSE_BYTES,
            16 * 1024 * 1024,
        )
    }

    fn with_admission(
        clock: Arc<dyn ActivationClock>,
        response_bytes: u64,
        work_bytes: u64,
    ) -> Self {
        let (root, config) = super::super::fixture();
        let (target, _) = super::super::fixture();
        let owner = start(&config, Arc::clone(&clock));
        let native =
            NativeCapacityOwner::with_clock(Default::default(), Arc::clone(&clock)).unwrap();
        owner.bind_native_capacity(&native).unwrap();
        let original = reserve(&native, clock.as_ref(), response_bytes, work_bytes);
        let seed = wait(
            owner
                .with_store_retaining(
                    StoreIoKind::RecoveryWrite,
                    256 * 1024,
                    Arc::clone(&original) as Arc<dyn std::any::Any + Send + Sync>,
                    |engine| {
                        let inputs = logical::populate(
                            engine,
                            AggregateMigrationRecipe::Count,
                            true,
                            32,
                            None,
                        );
                        let view = engine.snapshot()?;
                        let mut rows = Vec::new();
                        visit_view(&view, Instant::now() + WATCHDOG, |_, key, bytes| {
                            logical::row(&view, key, bytes)?;
                            rows.push((key.clone(), bytes.to_vec()));
                            Ok(())
                        })?;
                        Ok(Seed { inputs, rows })
                    },
                )
                .unwrap(),
        )
        .unwrap()
        .unwrap();
        owner
            .ready
            .wait_test_metadata_retirement(Instant::now() + WATCHDOG);
        Self {
            root,
            target,
            config,
            clock,
            response_bytes,
            work_bytes,
            owner,
            native,
            original: Some(original),
            seed: Arc::new(seed),
        }
    }

    pub fn checkpoint_path(&self) -> PathBuf {
        self.target.path().join("original-migration.v2")
    }

    pub fn original(&self) -> &Arc<NativeReservation> {
        self.original.as_ref().expect("fixture request retained")
    }

    pub fn release_original(&mut self) {
        assert!(self.original.take().is_some());
    }

    pub fn checkpoint(&self) -> (ProtectedSnapshot, Arc<Owners>, AggregateMigrationRequest) {
        let owners = Arc::new(Owners::new(Arc::clone(&self.seed)));
        let linked = Arc::clone(&owners);
        let artifact = Arc::clone(&owners);
        let row = Arc::clone(&owners);
        let job = self
            .owner
            .create_reviewed_snapshot(
                config(self.target.path()),
                self.seed.inputs.metadata.clone(),
                Arc::clone(self.original()),
                move |view| {
                    linked.linked(view).map_err(|error| match error {
                        MigrationError::Source(error) => SnapshotError::Source(error),
                        MigrationError::Review(error) => SnapshotError::Review(error),
                        MigrationError::Deadline => SnapshotError::Deadline,
                        MigrationError::Capacity => SnapshotError::Capacity,
                    })
                },
                move |required| artifact.artifact(required),
                move |key, bytes| row.row(key, bytes),
                Arc::new(|| Ok(())),
            )
            .unwrap();
        let (snapshot, receipt) = wait(job).unwrap();
        let receipt = receipt.unwrap().unwrap();
        let mut request = self.seed.inputs.request.clone();
        request.checkpoint_digest = receipt.snapshot_digest;
        request.checkpoint_manifest_digest = receipt.manifest_digest;
        (snapshot, owners, request)
    }

    pub fn open_checkpoint(&self) -> Result<ProtectedSnapshot, SnapshotError> {
        let row = Arc::new(Owners::new(Arc::clone(&self.seed)));
        let job = self
            .owner
            .open_snapshot(
                config(self.target.path()),
                Arc::clone(self.original()),
                move |key, bytes| row.row(key, bytes),
                Arc::new(|| Ok(())),
            )
            .unwrap();
        let (snapshot, result) = wait(job).unwrap();
        match result.unwrap() {
            Ok(_) => Ok(snapshot),
            Err(error) => {
                self.retire(snapshot);
                Err(error)
            }
        }
    }

    pub fn job(
        &self,
        snapshot: ProtectedSnapshot,
        owners: &Arc<Owners>,
        request: &AggregateMigrationRequest,
        phase: MigrationPhase,
    ) -> ProtectedMigrationJob {
        self.owner
            .migrate_aggregate(
                snapshot,
                request.clone(),
                self.seed.inputs.schema.clone(),
                (self.seed.inputs.recipe, phase),
                Arc::clone(owners) as Arc<dyn AggregateMigrationOwners>,
            )
            .unwrap()
    }

    pub fn migrate(
        &self,
        snapshot: ProtectedSnapshot,
        owners: &Arc<Owners>,
        request: &AggregateMigrationRequest,
        phase: MigrationPhase,
    ) -> (
        ProtectedSnapshot,
        Result<Result<MigrationReceipt, MigrationError>, ProtectedStoreError>,
    ) {
        wait(self.job(snapshot, owners, request, phase)).unwrap()
    }

    pub fn resume_job(
        &self,
        snapshot: ProtectedSnapshot,
        owners: &Arc<Owners>,
        request: crate::recovery::resume::MigrationResumeRequest,
    ) -> ProtectedMigrationResumeJob {
        self.owner
            .resume_migration(
                snapshot,
                request,
                self.seed.inputs.schema.clone(),
                Arc::clone(owners) as Arc<dyn AggregateMigrationOwners>,
            )
            .unwrap()
    }

    pub fn retire(&self, mut snapshot: ProtectedSnapshot) {
        let witness = snapshot.retirement_witness().unwrap();
        wait(snapshot.retire());
        self.owner
            .ready
            .wait_test_metadata_retirement(Instant::now() + WATCHDOG);
        assert!(witness.has_retired());
        assert!(!self.owner.snapshot().unwrap().custody_active);
    }

    pub fn observe(&self) -> Observed {
        let seed = Arc::clone(&self.seed);
        wait(
            self.owner
                .with_store(StoreIoKind::RecoveryRead, 64 * 1024, move |engine| {
                    let view = engine.snapshot()?;
                    let request = &seed.inputs.request;
                    let current = NamespaceMigrationView::capture(
                        &view,
                        &request.scope.tenant,
                        &request.scope.namespace,
                    )?;
                    let rows = view.scan_after(Family::State, b"state-v1\0", None, 2, 4096)?;
                    assert_eq!(rows.rows.len(), 1);
                    let (key, bytes) = &rows.rows[0];
                    let value = crate::session::inspect_cell(&view, key, bytes)?
                        .value
                        .unwrap()
                        .bytes;
                    Ok(Observed {
                        progress: view.get(&request.progress_key()?)?,
                        value,
                        status: current.namespace.status,
                        history: current.history.status,
                    })
                })
                .unwrap(),
        )
        .unwrap()
        .unwrap()
    }

    pub fn require_census(&self) {
        let quota = self.seed.inputs.quota.clone().unwrap();
        wait(
            self.owner
                .with_store(StoreIoKind::RecoveryRead, 64 * 1024, move |engine| {
                    let view = engine.snapshot()?;
                    let mut census = TenantCensus::capture(
                        &view,
                        std::slice::from_ref(&quota),
                        GlobalMetadataAllowance {
                            rows: 64,
                            bytes: 256 * 1024,
                        },
                        Instant::now() + WATCHDOG,
                    )?;
                    visit_view(&view, Instant::now() + WATCHDOG, |_, key, bytes| {
                        census.observe(
                            key,
                            bytes,
                            crate::tenant::census_contribution(&view, key, bytes)?,
                        )
                    })?;
                    census.finish().map(|_| ())
                })
                .unwrap(),
        )
        .unwrap()
        .unwrap();
    }

    pub fn restart(self) -> Self {
        assert!(finish(&self.owner).clean);
        self.restart_retired()
    }

    pub fn restart_retired(self) -> Self {
        assert!(self.owner.snapshot().unwrap().physically_retired());
        let Self {
            root,
            target,
            mut config,
            clock,
            response_bytes,
            work_bytes,
            native,
            original,
            seed,
            owner,
        } = self;
        drop(owner);
        drop(original);
        assert_eq!(native.snapshot().unwrap().recovery.slots, 0);
        config.create_if_missing = false;
        let owner = start(&config, Arc::clone(&clock));
        owner.bind_native_capacity(&native).unwrap();
        let original = reserve(&native, clock.as_ref(), response_bytes, work_bytes);
        Self {
            root,
            target,
            config,
            clock,
            response_bytes,
            work_bytes,
            owner,
            native,
            original: Some(original),
            seed,
        }
    }
}

fn start(config: &ProtectedStoreConfig, clock: Arc<dyn ActivationClock>) -> ProtectedStoreOwner {
    wait(
        ProtectedStoreOwner::start_bound_validated_view_with_clock(
            config.clone(),
            StoreIdentity::new("original-protected-migration-source".into()).unwrap(),
            0,
            |view| {
                visit_view(view, Instant::now() + WATCHDOG, |_, key, bytes| {
                    logical::row(view, key, bytes)
                })
                .map(|_| ())
            },
            clock,
        )
        .unwrap(),
    )
    .unwrap()
}

fn reserve(
    native: &NativeCapacityOwner,
    clock: &dyn ActivationClock,
    response_bytes: u64,
    work_bytes: u64,
) -> Arc<NativeReservation> {
    Arc::new(
        native
            .reserve(
                NativeAdmissionClass::Recovery,
                NativeReservationRequest {
                    request_bytes: 8192,
                    work_bytes,
                    response_bytes,
                },
                clock.monotonic_now() + Duration::from_secs(30),
            )
            .unwrap(),
    )
}

fn config(root: &Path) -> ProtectedSnapshotConfig {
    ProtectedSnapshotConfig {
        root: root.to_path_buf(),
        file_name: "original-migration.v2".into(),
    }
}

fn pause_review(gates: &Rendezvous, notice: mpsc::Sender<PauseTicket>) {
    let (registration, mut tracked) = gates.track(()).unwrap();
    tracked.commit(Stage::Entered).unwrap();
    let mut paused = Box::pin(tracked.pause());
    PollProbe::default().pending(paused.as_mut());
    notice
        .send(gates.blocked(registration, Stage::Entered).unwrap())
        .unwrap();
    block_on(paused);
}
