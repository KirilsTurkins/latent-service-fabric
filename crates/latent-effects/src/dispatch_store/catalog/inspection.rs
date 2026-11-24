use super::{validation, DispatchCatalog, DispatchCounts, EFFECT_PREFIX};
use crate::authority::{DispatchProfile, EffectScope};
use crate::dispatch::{effect_record_version, Disposition, EffectRecord};
use crate::dispatch_store::{
    codec::OwnerRecord, effect_management::EffectManagementCatalog, effect_payload_key,
    effect_row_key, storage_error,
};
use latent_state::embedded::{Family, ReadView, StoreError};
use serde::Serialize;

/// One fully validated original effect. Native payload/history buffers retire
/// inside this read; the output retains only bounded metadata, never a grant.
pub struct EffectInspection {
    pub record: EffectRecord,
    pub record_version: [u8; 32],
    pub occurred_at_millis: u64,
    pub payload_available: bool,
    pub management_receipt_digest: Option<[u8; 32]>,
}

/// Bounded operator projection for one unresolved original association.
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PublicationEffect {
    pub effect_id: String,
    pub command_id: String,
    pub attempt_id: String,
    pub commit_id: String,
    pub disposition: Disposition,
    pub binding: String,
    pub operation: String,
    pub profile: DispatchProfile,
}

#[derive(Debug)]
pub struct PublicationEffectPage {
    pub effects: Vec<PublicationEffect>,
    pub after_effect: Option<String>,
}

fn matches_publication(
    scope: &EffectScope,
    tenant: &str,
    namespace: &str,
    incarnation: u64,
    publication: &str,
) -> bool {
    scope.tenant == tenant
        && scope.namespace == namespace
        && scope.incarnation == incarnation
        && scope.publication == publication
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
                if matches_publication(
                    authority.scope(),
                    tenant,
                    namespace,
                    incarnation,
                    publication,
                ) {
                    counts.observe(&record)?;
                }
                Ok(())
            },
        )?;
        Ok(counts)
    }

    /// On the caller's bounded protected view, list at most sixteen unresolved
    /// original associations. The continuation uses an effect already disclosed
    /// in the selected scope, even when the engine scans across foreign rows.
    pub fn publication_effect_page(
        view: &ReadView,
        tenant: &str,
        namespace: &str,
        incarnation: u64,
        publication: &str,
        after_effect: Option<&str>,
        checkpoint: &mut dyn FnMut() -> Result<(), StoreError>,
    ) -> Result<PublicationEffectPage, StoreError> {
        const EFFECTS_PER_PAGE: usize = 16;
        let selected = |scope: &EffectScope| {
            matches_publication(scope, tenant, namespace, incarnation, publication)
        };
        checkpoint()?;
        let mut after = if let Some(effect) = after_effect {
            let key = effect_row_key(effect)?;
            let bytes = view
                .get_bounded(&key, 64 * 1024)?
                .ok_or(StoreError::Conflict)?;
            crate::dispatch_store::validate_row(&key, &bytes)?;
            let record = EffectRecord::decode(&bytes).map_err(storage_error)?;
            if record.disposition().terminal()
                || !selected(record.authority().map_err(storage_error)?.scope())
            {
                return Err(StoreError::Conflict);
            }
            Some(key.key)
        } else {
            None
        };
        let mut effects: Vec<PublicationEffect> = Vec::with_capacity(EFFECTS_PER_PAGE);
        loop {
            checkpoint()?;
            let page = view.scan_after(
                Family::Outbox,
                EFFECT_PREFIX,
                after.as_deref(),
                32,
                512 * 1024,
            )?;
            for (key, bytes) in page.rows {
                crate::dispatch_store::validate_row(&key, &bytes)?;
                let record = EffectRecord::decode(&bytes).map_err(storage_error)?;
                let authority = record.authority().map_err(storage_error)?;
                if record.disposition().terminal() || !selected(authority.scope()) {
                    continue;
                }
                if effects.len() == EFFECTS_PER_PAGE {
                    let after_effect = effects.last().map(|last| last.effect_id.clone());
                    return Ok(PublicationEffectPage {
                        effects,
                        after_effect,
                    });
                }
                let link = authority.link();
                effects.push(PublicationEffect {
                    effect_id: link.effect.clone(),
                    command_id: link.command.clone(),
                    attempt_id: link.attempt.to_string(),
                    commit_id: link.commit.clone(),
                    disposition: record.disposition(),
                    binding: authority.scope().binding.clone(),
                    operation: authority.scope().operation.clone(),
                    profile: authority.profile().clone(),
                });
            }
            let Some(next) = page.resume else { break };
            after = Some(next);
        }
        checkpoint()?;
        Ok(PublicationEffectPage {
            effects,
            after_effect: None,
        })
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
