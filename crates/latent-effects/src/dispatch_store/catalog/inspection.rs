use super::{validation, DispatchCatalog, DispatchCounts, EFFECT_PREFIX};
use crate::dispatch::{effect_record_version, EffectRecord};
use crate::dispatch_store::{
    codec::OwnerRecord, effect_management::EffectManagementCatalog, effect_payload_key,
    effect_row_key, storage_error,
};
use latent_state::embedded::{Family, ReadView, StoreError};

/// One fully validated original effect. Native payload/history buffers retire
/// inside this read; the output retains only bounded metadata, never a grant.
pub struct EffectInspection {
    pub record: EffectRecord,
    pub record_version: [u8; 32],
    pub occurred_at_millis: u64,
    pub payload_available: bool,
    pub management_receipt_digest: Option<[u8; 32]>,
}

impl DispatchCatalog {
    /// Inspect retained disposition counts for one exact namespace and
    /// publication on the caller's already admitted recovery view.
    pub fn publication_counts(
        view: &ReadView,
        tenant: &str,
        namespace: &str,
        incarnation: u64,
        publication: &str,
        checkpoint: &mut dyn FnMut() -> Result<(), StoreError>,
    ) -> Result<DispatchCounts, StoreError> {
        let mut counts = DispatchCounts::default();
        validation::walk(
            view,
            Family::Outbox,
            EFFECT_PREFIX,
            checkpoint,
            |key, bytes, _| {
                crate::dispatch_store::validate_row(key, bytes)?;
                let record = EffectRecord::decode(bytes).map_err(storage_error)?;
                let authority = record.authority().map_err(storage_error)?;
                let scope = authority.scope();
                if scope.tenant == tenant
                    && scope.namespace == namespace
                    && scope.incarnation == incarnation
                    && scope.publication == publication
                {
                    counts.observe(&record)?;
                }
                Ok(())
            },
        )?;
        Ok(counts)
    }

    /// Read one exact row and its existing finite payload/history/receipt
    /// closure. Missing rows remain missing; reading never expires or redrives.
    pub fn inspect_effect(
        view: &ReadView,
        effect: &str,
    ) -> Result<Option<EffectInspection>, StoreError> {
        let key = effect_row_key(effect)?;
        let Some(bytes) = view.get(&key)? else {
            return Ok(None);
        };
        let owner = view
            .get(&OwnerRecord::key())?
            .as_deref()
            .map(OwnerRecord::decode)
            .transpose()?;
        validation::validate_effect(view, owner, &key, &bytes)?;
        let record = EffectRecord::decode(&bytes).map_err(storage_error)?;
        let management_receipt_digest = EffectManagementCatalog::receipt_for_effect(view, &record)?
            .map(|receipt| receipt.digest().map_err(|_| StoreError::Corrupt))
            .transpose()?;
        Ok(Some(EffectInspection {
            record_version: effect_record_version(&bytes).map_err(storage_error)?,
            occurred_at_millis: record.clock_floor(),
            payload_available: view.get(&effect_payload_key(effect)?)?.is_some(),
            management_receipt_digest,
            record,
        }))
    }
}
