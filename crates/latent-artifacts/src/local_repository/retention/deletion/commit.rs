//! Durable visibility removal. This stage deliberately retains all payload and
//! lifecycle/evidence bytes and charges; it cannot be used as a GC permit.
use super::super::{ensure_identity, exposure, RetentionState};
use super::*;
use crate::{LifecycleScope, PublicationDeletionLookup, PublicationDeletionResult};
use std::time::Instant;

struct Prepared {
    head: model::Head,
    result: PublicationDeletionResult,
}
impl DirectoryArtifactRepository {
    /// Trusted-host-only visibility removal. Authenticate and authorize the exact
    /// scope/actor before calling. `preflight` MUST reserve required finite audit
    /// attempt/outcome and response capacity; the host retains that reservation
    /// until the returned original outcome (including uncertainty) is recorded.
    /// The callback runs without native fences. Every protection is rechecked
    /// afterward and held through intent/head synchronization and visibility.
    ///
    /// This is NOT physical deletion: payloads, evidence, lifecycle rows and
    /// storage/publication charges remain retained. No unpin/refund is performed.
    pub fn tombstone_publications(
        &self,
        request: &PublicationDeletionRequest,
        timeout: Duration,
        preflight: &mut dyn FnMut(&PublicationDeletionResult) -> Result<(), PlatformError>,
    ) -> Result<PublicationDeletionResult, PlatformError> {
        let deadline = deadline(timeout)?;
        request.validate()?;
        model::encode(request, model::MAX_REQUEST)?;
        if let PublicationDeletionLookup::Found(receipt) =
            self.publication_deletion_operation(&request.scope, &request.operation_id)?
        {
            if receipt.request != *request {
                return Err(conflict());
            }
            let result = PublicationDeletionResult {
                receipt,
                replay: true,
            };
            preflight(&result)?;
            check_time(deadline)?;
            return Ok(result);
        }
        let mut prepared = None;
        self.with_deletion_selection(request, deadline, &mut |state, reference_revision| {
            ensure_identity(state)?;
            let next = checked(state)?.next_deletion(request, reference_revision)?;
            storage::validate_transition(checked(state)?, &next)?;
            let (metadata, physical) = exposure(&next)?;
            self.index
                .try_read()
                .map_err(|_| busy())?
                .check_retention(metadata, self.config)?;
            self.content
                .try_lock()
                .map_err(|_| busy())?
                .check_retention_control(physical)?;
            let receipt = next
                .deletion_receipt(&request.scope, &request.operation_id)
                .cloned()
                .ok_or_else(corrupt)?;
            check_time(deadline)?;
            prepared = Some(Prepared {
                head: next,
                result: PublicationDeletionResult {
                    receipt,
                    replay: false,
                },
            });
            Ok(())
        })?;
        let prepared = prepared.ok_or_else(uncertain)?;
        preflight(&prepared.result)?;
        check_time(deadline)?;
        self.with_deletion_selection(request, deadline, &mut |state, revision| {
            if revision != prepared.result.receipt.reference_revision
                || checked(state)?.next_deletion(request, revision)? != prepared.head
            {
                return Err(conflict());
            }
            self.commit_tombstones(state, &prepared, deadline)
        })?;
        Ok(prepared.result)
    }

    /// Receipt absence/eviction remains UNKNOWN. Neither this lookup nor a
    /// tombstone grants rollback, eligibility, physical cleanup or fresh replay.
    pub fn publication_deletion_operation(
        &self,
        scope: &LifecycleScope,
        operation_id: &str,
    ) -> Result<PublicationDeletionLookup, PlatformError> {
        scope.validate()?;
        crate::publication_retention::token(operation_id)?;
        let state = self.retention.try_lock().map_err(|_| busy())?;
        if !state.healthy || self.life_store().check_health().is_err() {
            return Ok(PublicationDeletionLookup::Uncertain);
        }
        Ok(checked(&state)?
            .deletion_receipt(scope, operation_id)
            .cloned()
            .map_or(
                PublicationDeletionLookup::Unknown,
                PublicationDeletionLookup::Found,
            ))
    }

    fn commit_tombstones(
        &self,
        state: &mut RetentionState,
        prepared: &Prepared,
        deadline: Instant,
    ) -> Result<(), PlatformError> {
        let old = checked(state)?.clone();
        let (metadata, physical) = exposure(&prepared.head)?;
        let mut index = self.index.try_write().map_err(|_| busy())?;
        let mut content = self.content.try_lock().map_err(|_| busy())?;
        let (old_metadata, old_physical) = exposure(&old)?;
        let reserved_metadata = metadata.max(old_metadata);
        let reserved_physical = physical.max(old_physical);
        index.check_retention(reserved_metadata, self.config)?;
        index.check_tombstone_generation(prepared.result.receipt.request.targets.len())?;
        content.check_retention_control(reserved_physical)?;
        let publications: Vec<_> = prepared
            .result
            .receipt
            .request
            .targets
            .iter()
            .map(|t| t.publication.clone())
            .collect();
        self.web.with_tombstones(&publications, &mut || {
            // Charge the full candidate/recovery exposure before the first I/O.
            // All payload charges remain unchanged even after success.
            check_time(deadline)?;
            index.replace_retention(reserved_metadata, self.config)?;
            content.replace_retention_control(reserved_physical)?;
            state.healthy = false;
            let result: Result<(), PlatformError> = (|| {
                storage::persist(&self.root, &old, &prepared.head, deadline)?;
                for publication in &publications {
                    index.tombstone(&publication.id);
                }
                state.head = Some(prepared.head.clone());
                storage::fault(6)?;
                // Control-file replacement may release only the excess recovery
                // reservation, after durable HEAD and INTENT parent sync. Never
                // refund a publication, its evidence or a shared payload here.
                index.replace_retention(metadata, self.config)?;
                content.replace_retention_control(physical)?;
                Ok(())
            })();
            if result.is_err() {
                self.life_store().retire();
                self.web.epoch.retire();
                return Err(uncertain());
            }
            state.healthy = true;
            Ok(())
        })
    }

    pub(in crate::local_repository::retention) fn restore_publication_tombstones(
        &self,
        head: &model::Head,
    ) -> Result<(), PlatformError> {
        let Some(history) = &head.deletion else {
            return Ok(());
        };
        // Reopen work is capped by MAX_PUBLICATION_TOMBSTONES; no public request
        // can request an unbounded catalog walk. Validate the complete set first.
        for tombstone in &history.tombstones {
            if self.retention_generation(&tombstone.target.publication)?
                != tombstone.target.expected_generation
                || !self.terminal_publication(&tombstone.target.publication)?
            {
                return Err(corrupt());
            }
        }
        let mut index = self.index.try_write().map_err(|_| busy())?;
        index.check_tombstone_generation(history.tombstones.len())?;
        for batch in history
            .tombstones
            .chunks(crate::MAX_PUBLICATION_RETENTION_BATCH)
        {
            let publications: Vec<_> = batch.iter().map(|t| t.target.publication.clone()).collect();
            self.web.with_tombstones(&publications, &mut || {
                for publication in &publications {
                    index.tombstone(&publication.id);
                }
                Ok(())
            })?;
        }
        Ok(())
    }
}
