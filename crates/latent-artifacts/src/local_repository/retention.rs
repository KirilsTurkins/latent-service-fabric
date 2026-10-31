//! Shared native retention owner. This does not enable committed-content deletion.
mod model;
mod storage;
use super::{
    fs, io_error, lock_error, read_bounded_file, shared_content, sync_dir, write_synced,
    DirectoryArtifactRepository, Path, PathBuf, PlatformError, PlatformErrorCode,
};
use crate::publication_retention::{failure, unavailable_target};
use crate::{
    LifecycleScope, PublicationRef, PublicationRetentionAction, PublicationRetentionFence,
    PublicationRetentionLookup, PublicationRetentionPin, PublicationRetentionReceipt,
    PublicationRetentionRequest, PublicationRetentionResult, PublicationRetentionSelection,
    PublicationRetentionSnapshot, PublicationRetentionTarget, MAX_PUBLICATION_RETENTION_BATCH,
    MAX_PUBLICATION_RETENTION_PINS, MAX_PUBLICATION_RETENTION_RECEIPTS,
};
use std::time::{Duration, Instant};

#[derive(Default)]
pub(super) struct RetentionState {
    head: Option<model::Head>,
    healthy: bool,
}
struct Prepared {
    head: model::Head,
    result: PublicationRetentionResult,
    fence: PublicationRetentionFence,
}

pub(super) fn check_format(root: &Path, promoted: bool) -> Result<(), PlatformError> {
    storage::load(root, promoted, false).map(|_| ())
}
pub(super) fn is_marker(bytes: &[u8]) -> bool {
    bytes == model::MARKER
}

impl DirectoryArtifactRepository {
    /// Fail one durability boundary on the calling thread; development builds only.
    #[cfg(feature = "development-test-host")]
    pub fn inject_retention_fault_for_test(&self, point: crate::DevelopmentRetentionFault) {
        use crate::DevelopmentRetentionFault;
        let number = match point {
            DevelopmentRetentionFault::AfterIntent => 1,
            DevelopmentRetentionFault::AfterHead => 2,
            DevelopmentRetentionFault::AfterIntentRemoval => 3,
            DevelopmentRetentionFault::AfterFormatPromotion => 4,
        };
        storage::FAIL.with(|value| value.set(number));
    }

    pub(super) fn initialize_retention(&self) -> Result<(), PlatformError> {
        let promoted = is_marker(&read_bounded_file(
            &self.root.join("LIFECYCLE_MODE"),
            64,
            "lifecycle mode",
        )?);
        let recovered = storage::load(&self.root, promoted, true)?;
        let stored = recovered.is_some();
        let head = recovered.unwrap_or(model::Head::empty(storage::authority(&self.root)?));
        for pin in &head.pins {
            if self.retention_generation(&pin.publication)? < pin.pinned_generation {
                return Err(corrupt());
            }
        }
        let bytes = if stored { exposure(&head)? } else { (0, 0) };
        self.index
            .write()
            .map_err(lock_error)?
            .replace_retention(bytes.0, self.config)?;
        self.content
            .lock()
            .map_err(lock_error)?
            .replace_retention_control(bytes.1)?;
        *self.retention.lock().map_err(lock_error)? = RetentionState {
            head: Some(head),
            healthy: true,
        };
        Ok(())
    }

    /// Exact authorized selection, never an unbounded catalog enumeration.
    /// Returned pins are negative retention authority, not rollback eligibility.
    pub fn publication_retention_snapshot(
        &self,
        scope: &LifecycleScope,
        publications: &[PublicationRef],
        timeout: Duration,
    ) -> Result<PublicationRetentionSnapshot, PlatformError> {
        let deadline = deadline(timeout)?;
        scope.validate()?;
        validate_selection(scope, publications)?;
        let _work = self.admission_work.try_lock().map_err(|_| busy())?;
        let mut snapshot = None;
        self.life_store().with_exclusive(&mut |_| {
            let _epoch = self.web.epoch.write()?;
            let mut state = self.retention.try_lock().map_err(|_| busy())?;
            ensure_identity(&mut state)?;
            let head = checked(&state)?;
            let mut selections = Vec::with_capacity(publications.len());
            for publication in publications {
                check_time(deadline)?;
                selections.push(PublicationRetentionSelection {
                    target: PublicationRetentionTarget {
                        publication: publication.clone(),
                        expected_generation: self.retention_generation(publication)?,
                    },
                    pin: head.pin(publication)?.cloned(),
                });
            }
            let catalog_fence = storage::fence(&self.root, head)?;
            check_time(deadline)?;
            snapshot = Some(PublicationRetentionSnapshot {
                catalog_fence,
                selections,
            });
            Ok(())
        })?;
        snapshot.ok_or_else(uncertain)
    }

    /// Trusted host entry point. The callback MUST preflight response capacity
    /// and required audit admission. It runs outside lifecycle/commit fences.
    /// After it returns, all original authority is rechecked before INTENT.
    pub fn change_publication_retention(
        &self,
        request: &PublicationRetentionRequest,
        timeout: Duration,
        preflight: &mut dyn FnMut(&PublicationRetentionResult) -> Result<(), PlatformError>,
    ) -> Result<PublicationRetentionResult, PlatformError> {
        let deadline = deadline(timeout)?;
        request.validate()?;
        model::encode(request, model::MAX_REQUEST)?;
        let prepared = self.prepare_retention(request, deadline)?;
        preflight(&prepared.result)?;
        check_time(deadline)?;
        if prepared.result.replay {
            return Ok(prepared.result);
        }
        let _work = self.admission_work.try_lock().map_err(|_| busy())?;
        self.life_store().with_exclusive(&mut |_| {
            let _epoch = self.web.epoch.write()?;
            let writer = self.publish_lock.try_lock().map_err(|_| busy())?;
            if writer.pending.is_some() {
                return Err(busy());
            }
            let mut state = self.retention.try_lock().map_err(|_| busy())?;
            let old = checked(&state)?;
            if storage::fence(&self.root, old)? != prepared.fence {
                return Err(conflict());
            }
            self.check_retention_generations(request)?;
            let (metadata, physical) = exposure(&prepared.head)?;
            let mut index = self.index.try_write().map_err(|_| busy())?;
            let mut content = self.content.try_lock().map_err(|_| busy())?;
            index.check_retention(metadata, self.config)?;
            content.check_retention_control(physical)?;
            check_time(deadline)?;
            if storage::persist(&self.root, old, &prepared.head, deadline).is_err() {
                state.healthy = false;
                self.life_store().poison();
                self.web.epoch.retire();
                return Err(uncertain());
            }
            // Refund only after HEAD and the intent removal's parent sync.
            index.replace_retention(metadata, self.config)?;
            content.replace_retention_control(physical)?;
            state.head = Some(prepared.head.clone());
            Ok(())
        })?;
        Ok(prepared.result)
    }

    /// A retained receipt proves the original pin/unpin, not current eligibility.
    /// Unknown is never interpreted as permission to repeat the mutation.
    pub fn publication_retention_operation(
        &self,
        scope: &LifecycleScope,
        operation_id: &str,
    ) -> Result<PublicationRetentionLookup, PlatformError> {
        scope.validate()?;
        crate::publication_retention::token(operation_id)?;
        let state = self.retention.try_lock().map_err(|_| busy())?;
        if !state.healthy || self.life_store().check_health().is_err() {
            return Ok(PublicationRetentionLookup::Uncertain);
        }
        Ok(checked(&state)?
            .receipt(scope, operation_id)
            .cloned()
            .map_or(
                PublicationRetentionLookup::Unknown,
                PublicationRetentionLookup::Found,
            ))
    }

    fn prepare_retention(
        &self,
        request: &PublicationRetentionRequest,
        deadline: Instant,
    ) -> Result<Prepared, PlatformError> {
        let _work = self.admission_work.try_lock().map_err(|_| busy())?;
        let mut prepared = None;
        self.life_store().with_exclusive(&mut |_| {
            let _epoch = self.web.epoch.write()?;
            let mut state = self.retention.try_lock().map_err(|_| busy())?;
            ensure_identity(&mut state)?;
            let head = checked(&state)?;
            if let Some(receipt) = head.receipt(&request.scope, &request.operation_id) {
                if receipt.request != *request {
                    return Err(conflict());
                }
                prepared = Some(Prepared {
                    head: head.clone(),
                    fence: request.expected_catalog_fence,
                    result: PublicationRetentionResult {
                        receipt: receipt.clone(),
                        replay: true,
                    },
                });
                return Ok(());
            }
            self.check_retention_generations(request)?;
            let fence = storage::fence(&self.root, head)?;
            if fence != request.expected_catalog_fence {
                return Err(conflict());
            }
            let next = head.next(request)?;
            let (metadata, physical) = exposure(&next)?;
            self.index
                .try_read()
                .map_err(|_| busy())?
                .check_retention(metadata, self.config)?;
            self.content
                .try_lock()
                .map_err(|_| busy())?
                .check_retention_control(physical)?;
            check_time(deadline)?;
            let receipt = next.receipts.last().cloned().ok_or_else(corrupt)?;
            prepared = Some(Prepared {
                head: next,
                fence,
                result: PublicationRetentionResult {
                    receipt,
                    replay: false,
                },
            });
            Ok(())
        })?;
        prepared.ok_or_else(uncertain)
    }
    fn check_retention_generations(
        &self,
        request: &PublicationRetentionRequest,
    ) -> Result<(), PlatformError> {
        for target in &request.targets {
            if self.retention_generation(&target.publication)? != target.expected_generation {
                return Err(conflict());
            }
        }
        Ok(())
    }
    fn retention_generation(&self, reference: &PublicationRef) -> Result<u64, PlatformError> {
        if let Some(record) = self.life_store().record_publication(&reference.id)? {
            if record.scope != reference.scope {
                return Err(unavailable_target());
            }
            return Ok(record.generation);
        }
        self.web.retention_generation(reference)
    }
}

fn checked(state: &RetentionState) -> Result<&model::Head, PlatformError> {
    if !state.healthy {
        return Err(uncertain());
    }
    state.head.as_ref().ok_or_else(uncertain)
}
fn validate_selection(
    scope: &LifecycleScope,
    publications: &[PublicationRef],
) -> Result<(), PlatformError> {
    if publications.is_empty() || publications.len() > MAX_PUBLICATION_RETENTION_BATCH {
        return Err(crate::publication_retention::invalid());
    }
    for reference in publications {
        if reference.scope != *scope {
            return Err(unavailable_target());
        }
    }
    if publications.windows(2).any(|p| p[0].id >= p[1].id) {
        return Err(crate::publication_retention::invalid());
    }
    Ok(())
}
fn exposure(head: &model::Head) -> Result<(usize, u64), PlatformError> {
    let size = model::encode(head, model::MAX_HEAD - 1024)?.len();
    // Current/candidate structures, canonical encodings and bounded recovery
    // buffers; disk exposure includes HEAD, INTENT and atomic-write staging.
    let metadata = size
        .checked_mul(12)
        .and_then(|n| n.checked_add(16 * 1024))
        .ok_or_else(capacity)?;
    let physical = size
        .checked_mul(3)
        .and_then(|n| n.checked_add(16 * 1024))
        .ok_or_else(capacity)?;
    Ok((metadata, physical as u64))
}
fn deadline(timeout: Duration) -> Result<Instant, PlatformError> {
    if timeout.is_zero() || timeout > Duration::from_secs(30) {
        return Err(crate::publication_retention::invalid());
    }
    Instant::now().checked_add(timeout).ok_or_else(capacity)
}
fn check_time(deadline: Instant) -> Result<(), PlatformError> {
    if Instant::now() >= deadline {
        return Err(failure(
            PlatformErrorCode::DeadlineExceeded,
            "publication-retention-deadline",
        ));
    }
    Ok(())
}
fn busy() -> PlatformError {
    failure(PlatformErrorCode::Unavailable, "publication-retention-busy")
}
fn corrupt() -> PlatformError {
    failure(
        PlatformErrorCode::CorruptArtifact,
        "publication-retention-corrupt",
    )
}
fn capacity() -> PlatformError {
    failure(
        PlatformErrorCode::ResourceExhausted,
        "publication-retention-capacity",
    )
}
fn conflict() -> PlatformError {
    failure(
        PlatformErrorCode::StateConflict,
        "publication-retention-authority-changed",
    )
}
fn uncertain() -> PlatformError {
    failure(
        PlatformErrorCode::Unavailable,
        "publication-retention-uncertain-reopen-query-original-operation",
    )
}

fn ensure_identity(state: &mut RetentionState) -> Result<(), PlatformError> {
    checked(state)?;
    let head = state.head.as_mut().ok_or_else(uncertain)?;
    if head.authority != [0; 32] {
        return Ok(());
    }
    #[cfg(target_os = "linux")]
    {
        use std::io::Read;
        let mut identity = [0; 32];
        fs::File::open("/dev/urandom")
            .and_then(|mut file| file.read_exact(&mut identity))
            .map_err(io_error)?;
        if identity == [0; 32] {
            return Err(uncertain());
        }
        head.authority = identity;
        Ok(())
    }
    #[cfg(not(target_os = "linux"))]
    {
        Err(failure(
            PlatformErrorCode::Unavailable,
            "publication-retention-platform-unsupported",
        ))
    }
}
