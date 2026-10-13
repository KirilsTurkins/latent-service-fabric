//! Current protected input/staging owners. Every callback retains actual seals.
use super::codecs::Codecs;
use latent_effects::dispatch_store::DispatchCatalog;
use latent_state::{
    embedded::{ExpectedRow, Family, ReadView, RowKey, RowMutation, StoreError},
    protected_store::{
        ProtectedRestoreInput, RestoreInputOwners, RestoreReadFence, RestoreRowDisposition,
        RestoreStageControls, RestoreStageOwners, RestoreStageRequest, RestoreWriteFence,
    },
    recovery::{
        restore::RestoreWindow,
        snapshot::{visit_view, RequiredArtifact, SnapshotClosure, SnapshotError},
        RecoveryGuard, RecoveryStatus,
    },
    tenant::{TenantCensusContribution, TenantUsage},
};

impl RestoreInputOwners for Codecs {
    fn archive_row(&self, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
        self.row(key, bytes)
    }
    fn current_closure(&self, view: &ReadView) -> Result<SnapshotClosure, SnapshotError> {
        self.closure(view).map_err(SnapshotError::Review)
    }
    fn required_artifact(&self, artifact: &RequiredArtifact) -> Result<(), StoreError> {
        self.artifact(artifact)
    }
    fn review_window(&self, view: &ReadView, window: &RestoreWindow) -> Result<(), StoreError> {
        self.authority.check("namespace-inspect-restore")?;
        self.closure(view)?;
        for pair in window.namespaces() {
            for record in [pair.snapshot().decode()?.0, pair.current().decode()?.0] {
                let operation = &self.catalog.primary().operation;
                if record.tenant != operation.target().tenant
                    || record.id.0 != operation.namespace()
                    || record.version.incarnation != operation.incarnation()
                {
                    return Err(StoreError::UnsupportedFormat);
                }
                self.catalog
                    .primary()
                    .schema
                    .require_namespace(&record)
                    .map_err(|_| StoreError::UnsupportedFormat)?;
            }
        }
        Ok(())
    }
    fn current(&self) -> Result<(), StoreError> {
        self.check()
    }
    fn accept_read(&self, original: RestoreReadFence<'_>) -> Result<(), StoreError> {
        self.fence("namespace-inspect-restore", || original.accept())
    }
}

impl Codecs {
    fn restore_request(
        &self,
        input: &ProtectedRestoreInput,
        request: &RestoreStageRequest,
    ) -> Result<(), StoreError> {
        self.check()?;
        if request.operator_id != self.authority.actor
            || request.runtime_digest != self.runtime
            || request.loss_window_acknowledgement != input.window().digest()?
        {
            return Err(StoreError::Conflict);
        }
        Ok(())
    }
    fn verify_restore(
        &self,
        staged: &ReadView,
        input: &ProtectedRestoreInput,
        request: &RestoreStageRequest,
        status: RecoveryStatus,
    ) -> Result<(), StoreError> {
        self.restore_request(input, request)?;
        self.closure(staged)?;
        let guard = RecoveryGuard::capture(staged)?.ok_or(StoreError::Corrupt)?;
        if guard.status() != status
            || guard.window_digest() != request.loss_window_acknowledgement
            || guard.snapshot_digest() != input.snapshot().snapshot_digest
        {
            return Err(StoreError::Corrupt);
        }
        for pair in input.window().namespaces() {
            let history = pair.proposed_history()?;
            let key = latent_state::namespace::history::history_key(
                &history.tenant,
                &history.namespace,
                history.incarnation,
            )
            .map_err(|_| StoreError::Corrupt)?;
            if staged.get(&key)?.as_deref()
                != Some(
                    history
                        .encode()
                        .map_err(|_| StoreError::Corrupt)?
                        .as_slice(),
                )
            {
                return Err(StoreError::Corrupt);
            }
        }
        let owner = DispatchCatalog::checkpoint(staged)?.ok_or(StoreError::Corrupt)?;
        if owner.0 <= self.checkpoint.dispatch_owner_epoch()
            || owner.1 < self.checkpoint.clock_floor_millis()
        {
            return Err(StoreError::Corrupt);
        }
        Ok(())
    }
}

impl RestoreStageOwners for Codecs {
    fn archive_row(&self, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
        self.row(key, bytes)
    }
    fn required_artifact(&self, artifact: &RequiredArtifact) -> Result<(), StoreError> {
        self.artifact(artifact)
    }
    fn review_input(
        &self,
        current: &ReadView,
        input: &ProtectedRestoreInput,
        request: &RestoreStageRequest,
    ) -> Result<(), StoreError> {
        self.authority.check("namespace-restore")?;
        self.restore_request(input, request)?;
        self.closure(current)?;
        self.review_window(current, input.window())
    }
    fn row_disposition(
        &self,
        key: &RowKey,
        bytes: &[u8],
    ) -> Result<RestoreRowDisposition, StoreError> {
        self.row(key, bytes)?;
        Ok(RestoreRowDisposition::Retain)
    }
    fn stage_controls(
        &self,
        current: &ReadView,
        staged: &ReadView,
        input: &ProtectedRestoreInput,
        request: &RestoreStageRequest,
    ) -> Result<RestoreStageControls, StoreError> {
        self.restore_request(input, request)?;
        self.closure(current)?;
        let quota = self.quotas.first().ok_or(StoreError::UnsupportedFormat)?;
        let mut record =
            latent_state::tenant::inspect(current, &quota.tenant)?.ok_or(StoreError::Corrupt)?;
        if record.quota != *quota {
            return Err(StoreError::Conflict);
        }
        record.generation = record
            .generation
            .checked_add(1)
            .ok_or(StoreError::Capacity)?;
        let key = latent_state::tenant::quota_key(&quota.tenant)?;
        let mut usage = TenantUsage {
            metadata_rows: 1,
            metadata_bytes: latent_state::tenant::row_charge(
                &key,
                &[0; latent_state::tenant::RECORD_BYTES],
            )?,
            ..TenantUsage::default()
        };
        visit_view(staged, self.authority.deadline, |_, key, bytes| {
            if key.family == Family::Outbox {
                // The new local owner is installed in this same control batch;
                // retained attempts are reviewed against it after publication.
                latent_effects::dispatch_store::validate_row(key, bytes)?;
                let effect = latent_effects::dispatch::EffectRecord::decode(bytes)
                    .map_err(|_| StoreError::Corrupt)?;
                if effect
                    .authority()
                    .map_err(|_| StoreError::Corrupt)?
                    .scope()
                    .tenant
                    != quota.tenant.0
                {
                    return Err(StoreError::UnsupportedFormat);
                }
                return Ok(());
            }
            match contribution(staged, key, bytes)? {
                TenantCensusContribution::Usage {
                    tenant,
                    usage: added,
                } if tenant == quota.tenant => {
                    add_usage(&mut usage, added)?;
                    Ok(())
                }
                TenantCensusContribution::Covered { tenant } if tenant == quota.tenant => Ok(()),
                TenantCensusContribution::Global => Ok(()),
                _ => Err(StoreError::UnsupportedFormat),
            }
        })?;
        record.usage = usage;
        let guard_key = latent_state::tenant::guard_key();
        let guard = current.get(&guard_key)?.ok_or(StoreError::Corrupt)?;
        if staged.get(&guard_key)?.is_some() || staged.get(&key)?.is_some() {
            return Err(StoreError::Corrupt);
        }
        let mut batch = DispatchCatalog::prepare_restored_owner(staged, current, self.time()?)?;
        batch.expectations.extend([
            ExpectedRow {
                key: guard_key.clone(),
                value: None,
            },
            ExpectedRow {
                key: key.clone(),
                value: None,
            },
        ]);
        batch.mutations.extend([
            RowMutation {
                key: guard_key,
                value: Some(guard),
            },
            RowMutation {
                key,
                value: Some(record.encode()?),
            },
        ]);
        Ok(RestoreStageControls { batch })
    }
    fn verify_staged(
        &self,
        staged: &ReadView,
        input: &ProtectedRestoreInput,
        request: &RestoreStageRequest,
    ) -> Result<(), StoreError> {
        self.verify_restore(staged, input, request, RecoveryStatus::Staging)
    }
    fn verify_completed(
        &self,
        staged: &ReadView,
        input: &ProtectedRestoreInput,
        request: &RestoreStageRequest,
    ) -> Result<(), StoreError> {
        self.verify_restore(
            staged,
            input,
            request,
            RecoveryStatus::ReconciliationRequired,
        )
    }
    fn dispatch_checkpoint(&self, staged: &ReadView) -> Result<(u64, u64), StoreError> {
        self.check()?;
        DispatchCatalog::checkpoint(staged)?.ok_or(StoreError::Corrupt)
    }
    fn protected_clock_epoch(&self) -> Result<u64, StoreError> {
        self.authority
            .clock
            .covered_epoch()
            .map_err(|_| StoreError::Unavailable)
    }
    fn current_role(&self) -> Result<(), StoreError> {
        self.authority.check("namespace-restore")
    }
    fn current_audit(&self) -> Result<(), StoreError> {
        self.check()
    }
    fn current_controls(&self) -> Result<(), StoreError> {
        self.catalog.current()
    }
    fn current_clock(&self) -> Result<(), StoreError> {
        self.time().map(|_| ())
    }
    fn accept(&self, original: RestoreWriteFence<'_>) -> Result<(), StoreError> {
        self.fence("namespace-restore", || original.accept())
    }
}

fn add_usage(usage: &mut TenantUsage, added: TenantUsage) -> Result<(), StoreError> {
    macro_rules! add { ($($field:ident),*) => { $(usage.$field = usage.$field.checked_add(added.$field).ok_or(StoreError::Capacity)?;)* }; }
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

pub(super) fn contribution(
    view: &ReadView,
    key: &RowKey,
    bytes: &[u8],
) -> Result<TenantCensusContribution, StoreError> {
    type Contributor =
        fn(&ReadView, &RowKey, &[u8]) -> Result<TenantCensusContribution, StoreError>;
    let contributors: [Contributor; 4] = [
        latent_wire::phase4::StateManagementBackend::tenant_metadata_contribution,
        latent_commit::atomic::tenant_census_contribution,
        DispatchCatalog::tenant_census_contribution,
        latent_state::tenant::census_contribution,
    ];
    for contributor in contributors {
        match contributor(view, key, bytes) {
            Err(StoreError::UnsupportedFormat) => {}
            result => return result,
        }
    }
    Err(StoreError::UnsupportedFormat)
}
