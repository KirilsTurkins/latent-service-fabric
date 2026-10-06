//! Controlled installed owners for physical import schedules only. The exact
//! producer rows, current source quota and same Original Native are real; these
//! fixtures do not qualify authenticated RPC, external clock or effect resume.
use super::*;
use crate::{
    embedded::{AtomicBatch, ExpectedRow, RowMutation},
    namespace::history::NamespaceHistory,
    protected_store::{
        ProtectedRestoreDestinationConfig, RestoreRowDisposition, RestoreStageControls,
        RestoreStageOwners, RestoreStageRequest, RestoreWriteFence, RestoreWriteKind,
    },
    recovery::{RecoveryGuard, RecoveryStatus},
    tenant::{TenantCensusContribution, TenantUsage},
};
use std::sync::atomic::AtomicU64;

pub(in crate::protected_store::tests::migration) struct StageOwners {
    source: Arc<Owners>,
    original: Arc<NativeReservation>,
    clock: Arc<dyn ActivationClock>,
    pub revoked: AtomicU8,
    pub ignored_gate: AtomicBool,
    pub writes: AtomicUsize,
    pub verified: AtomicUsize,
    clock_epoch: AtomicU64,
    dispatch_epoch: AtomicU64,
    floor: u64,
    pause: Mutex<Option<(RestoreWriteKind, Rendezvous, mpsc::Sender<PauseTicket>)>>,
}

impl StageOwners {
    pub fn new(setup: &Setup, source: &Arc<Owners>) -> Self {
        Self {
            source: Arc::clone(source),
            original: Arc::clone(setup.original()),
            clock: Arc::clone(&setup.clock),
            revoked: AtomicU8::new(0),
            ignored_gate: AtomicBool::new(false),
            writes: AtomicUsize::new(0),
            verified: AtomicUsize::new(0),
            clock_epoch: AtomicU64::new(1),
            dispatch_epoch: AtomicU64::new(7),
            floor: setup.clock.sample().unix_millis(),
            pause: Mutex::new(None),
        }
    }

    pub fn pause_kind(&self, kind: RestoreWriteKind) -> (Rendezvous, mpsc::Receiver<PauseTicket>) {
        let gates = Rendezvous::new(1);
        let (notice, receiver) = mpsc::channel();
        assert!(self
            .pause
            .lock()
            .unwrap()
            .replace((kind, gates.clone(), notice))
            .is_none());
        (gates, receiver)
    }

    fn current(&self, owner: u8) -> Result<(), StoreError> {
        if self.revoked.load(Ordering::SeqCst) == owner {
            return Err(StoreError::Unavailable);
        }
        self.source.current()?;
        self.original
            .with_live(|| ())
            .map_err(|_| StoreError::SnapshotExpired)
    }

    fn request(
        &self,
        input: &ProtectedRestoreInput,
        request: &RestoreStageRequest,
    ) -> Result<(), StoreError> {
        if request.operator_id != "restore-operator"
            || request.operation_id != "restore-original-backup"
            || request.runtime_digest != self.source.seed.inputs.metadata.runtime_digest
            || request.loss_window_acknowledgement != input.window().digest()?
            || input.window().namespaces().len() != 1
        {
            return Err(StoreError::Conflict);
        }
        Ok(())
    }
}

impl StageOwners {
    pub(in crate::protected_store::tests::migration) fn review_reopened(
        &self,
        view: &ReadView,
        input: &ProtectedRestoreInput,
        request: &RestoreStageRequest,
    ) -> Result<(), StoreError> {
        self.verify_view(view, input, request, RecoveryStatus::ReconciliationRequired)
    }

    fn verify_view(
        &self,
        staged: &ReadView,
        input: &ProtectedRestoreInput,
        request: &RestoreStageRequest,
        expected_status: RecoveryStatus,
    ) -> Result<(), StoreError> {
        self.request(input, request)?;
        let selected = self
            .source
            .seed
            .inputs
            .quota
            .as_ref()
            .ok_or(StoreError::Invalid)?;
        let mut census = TenantCensus::capture(
            staged,
            std::slice::from_ref(selected),
            GlobalMetadataAllowance {
                rows: 64,
                bytes: 256 * 1024,
            },
            self.original.original_deadline(),
        )?;
        visit_view(
            staged,
            self.original.original_deadline(),
            |_, key, bytes| {
                census.observe(
                    key,
                    bytes,
                    crate::tenant::census_contribution(staged, key, bytes)?,
                )
            },
        )?;
        census.finish()?;
        let guard = RecoveryGuard::capture(staged)?.ok_or(StoreError::Corrupt)?;
        if guard.status() != expected_status {
            return Err(StoreError::Corrupt);
        }
        for reviewed in input.window().namespaces() {
            let history = reviewed.proposed_history()?;
            let key = crate::namespace::history::history_key(
                &history.tenant,
                &history.namespace,
                history.incarnation,
            )
            .map_err(|_| StoreError::Corrupt)?;
            let actual = staged.get(&key)?.ok_or(StoreError::Corrupt)?;
            if NamespaceHistory::decode(&actual).map_err(|_| StoreError::Corrupt)? != history {
                return Err(StoreError::Corrupt);
            }
        }
        if self.source.seed.rows.iter().any(|(key, _)| {
            matches!(
                key.family,
                Family::Outbox | Family::Attempt | Family::Inbox | Family::PayloadReference
            )
        }) {
            return Err(StoreError::UnsupportedFormat);
        }
        self.verified.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
}

impl RestoreStageOwners for StageOwners {
    fn archive_row(&self, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
        self.source.row(key, bytes)
    }
    fn required_artifact(&self, artifact: &RequiredArtifact) -> Result<(), StoreError> {
        self.source.artifact(artifact)
    }
    fn review_input(
        &self,
        current: &ReadView,
        input: &ProtectedRestoreInput,
        request: &RestoreStageRequest,
    ) -> Result<(), StoreError> {
        self.request(input, request)?;
        self.source
            .linked(current)
            .map_err(|_| StoreError::Corrupt)?;
        let quota = self
            .source
            .seed
            .inputs
            .quota
            .as_ref()
            .ok_or(StoreError::Invalid)?;
        crate::tenant::require_installation(current, std::slice::from_ref(quota))?;
        Ok(())
    }
    fn row_disposition(
        &self,
        key: &RowKey,
        bytes: &[u8],
    ) -> Result<RestoreRowDisposition, StoreError> {
        self.source.row(key, bytes)?;
        Ok(RestoreRowDisposition::Retain)
    }
    fn stage_controls(
        &self,
        current: &ReadView,
        staged: &ReadView,
        input: &ProtectedRestoreInput,
        request: &RestoreStageRequest,
    ) -> Result<RestoreStageControls, StoreError> {
        self.request(input, request)?;
        self.current_controls()?;
        let selected = self
            .source
            .seed
            .inputs
            .quota
            .as_ref()
            .ok_or(StoreError::Invalid)?;
        crate::tenant::require_installation(current, std::slice::from_ref(selected))?;
        let mut record =
            crate::tenant::inspect(current, &selected.tenant)?.ok_or(StoreError::Corrupt)?;
        if record.quota != *selected {
            return Err(StoreError::Conflict);
        }
        record.generation = record
            .generation
            .checked_add(1)
            .ok_or(StoreError::Capacity)?;
        let quota_key = crate::tenant::quota_key(&selected.tenant)?;
        let mut usage = TenantUsage {
            metadata_rows: 1,
            metadata_bytes: crate::tenant::row_charge(
                &quota_key,
                &[0; crate::tenant::RECORD_BYTES],
            )?,
            ..TenantUsage::default()
        };
        visit_view(
            staged,
            self.original.original_deadline(),
            |_, key, bytes| {
                if *key == crate::store_identity::StoreIdentity::row_key()
                    || *key == crate::recovery::guard_key()
                {
                    crate::tenant::census_contribution(staged, key, bytes)?;
                    return Ok(());
                }
                match crate::tenant::census_contribution(staged, key, bytes)? {
                    TenantCensusContribution::Usage {
                        tenant,
                        usage: added,
                    } if tenant == selected.tenant => add_usage(&mut usage, added),
                    _ => Err(StoreError::UnsupportedFormat),
                }
            },
        )?;
        record.usage = usage;
        let encoded = record.encode()?; // Current quota bounds apply to actual retained totals.
        let guard_key = crate::tenant::guard_key();
        let guard = current
            .get_bounded(&guard_key, crate::tenant::GUARD_BYTES)?
            .ok_or(StoreError::Corrupt)?;
        if staged.get(&guard_key)?.is_some() || staged.get(&quota_key)?.is_some() {
            return Err(StoreError::Corrupt);
        }
        Ok(RestoreStageControls {
            batch: AtomicBatch {
                expectations: vec![
                    ExpectedRow {
                        key: guard_key.clone(),
                        value: None,
                    },
                    ExpectedRow {
                        key: quota_key.clone(),
                        value: None,
                    },
                ],
                mutations: vec![
                    RowMutation {
                        key: guard_key,
                        value: Some(guard),
                    },
                    RowMutation {
                        key: quota_key,
                        value: Some(encoded),
                    },
                ],
            },
        })
    }
    fn verify_staged(
        &self,
        staged: &ReadView,
        input: &ProtectedRestoreInput,
        request: &RestoreStageRequest,
    ) -> Result<(), StoreError> {
        self.verify_view(staged, input, request, RecoveryStatus::Staging)
    }
    fn dispatch_checkpoint(&self, staged: &ReadView) -> Result<(u64, u64), StoreError> {
        self.current_controls()?;
        if RecoveryGuard::capture(staged)?
            .ok_or(StoreError::Corrupt)?
            .status()
            != RecoveryStatus::ReconciliationRequired
        {
            return Err(StoreError::Corrupt);
        }
        for family in [
            Family::Outbox,
            Family::Attempt,
            Family::Inbox,
            Family::PayloadReference,
        ] {
            if !staged
                .scan_after(family, b"", None, 1, 2 * 1024 * 1024 + 8192)?
                .rows
                .is_empty()
            {
                return Err(StoreError::UnsupportedFormat);
            }
        }
        let epoch = self.dispatch_epoch.load(Ordering::SeqCst);
        if epoch == 0 {
            return Err(StoreError::Unavailable);
        }
        Ok((epoch, self.clock.sample().unix_millis()))
    }
    fn protected_clock_epoch(&self) -> Result<u64, StoreError> {
        self.current_clock()?;
        let epoch = self.clock_epoch.load(Ordering::SeqCst);
        if epoch == 0 {
            return Err(StoreError::Unavailable);
        }
        Ok(epoch)
    }
    fn current_role(&self) -> Result<(), StoreError> {
        self.current(1)
    }
    fn current_audit(&self) -> Result<(), StoreError> {
        self.current(2)
    }
    fn current_controls(&self) -> Result<(), StoreError> {
        self.current(3)
    }
    fn current_clock(&self) -> Result<(), StoreError> {
        self.current(4)?;
        if self.clock.sample().unix_millis() < self.floor {
            return Err(StoreError::Unavailable);
        }
        Ok(())
    }
    fn accept(&self, native: RestoreWriteFence<'_>) -> Result<(), StoreError> {
        let pause = {
            let mut pause = self.pause.lock().unwrap();
            if pause
                .as_ref()
                .is_some_and(|(kind, _, _)| *kind == native.kind())
            {
                pause.take()
            } else {
                None
            }
        };
        if let Some((_, gates, notice)) = pause {
            pause_review(&gates, notice);
        }
        self.current_role()?;
        self.current_audit()?;
        self.current_controls()?;
        self.current_clock()?;
        if self.ignored_gate.load(Ordering::SeqCst) {
            return Ok(());
        }
        if native.operation_digest() == [0; 32] {
            return Err(StoreError::Invalid);
        }
        native.accept()?;
        self.writes.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }
}

impl Setup {
    pub fn source_path(&self) -> PathBuf {
        self.config.root.join(&self.config.file_name)
    }

    pub fn plan_restore(
        &self,
        destination: ProtectedRestoreDestinationConfig,
        owners: &Arc<Owners>,
    ) -> Result<ProtectedSnapshot, ProtectedStoreError> {
        let row = Arc::clone(owners);
        let current = Arc::clone(owners);
        let job = self.owner.open_snapshot_for_restore(
            config(self.target.path()),
            destination,
            Arc::clone(self.original()),
            move |key, bytes| row.row(key, bytes),
            Arc::new(move || current.current()),
        )?;
        let (snapshot, result) = wait(job).unwrap();
        match result? {
            Ok(_) => Ok(snapshot),
            Err(_) => {
                self.retire(snapshot);
                Err(ProtectedStoreError::Store(StoreError::Corrupt))
            }
        }
    }
}

fn add_usage(left: &mut TenantUsage, right: TenantUsage) -> Result<(), StoreError> {
    macro_rules! add { ($($field:ident),*) => { $(left.$field = left.$field.checked_add(right.$field).ok_or(StoreError::Capacity)?;)* }; }
    add!(
        state_keys,
        state_bytes,
        tombstone_keys,
        tombstone_bytes,
        result_rows,
        result_bytes,
        effect_rows,
        effect_bytes,
        payload_bytes,
        recovery_bytes,
        metadata_rows,
        metadata_bytes
    );
    Ok(())
}
