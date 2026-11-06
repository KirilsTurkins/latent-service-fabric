//! Negative web identity retained independently of reclaimed payloads.
use super::*;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(in crate::local_repository) struct WebCleanupIdentity {
    pub record: WebLifecycleRecord,
    #[serde(with = "crate::web::codec::blob")]
    pub completion: ArtifactBlobDigest,
}
impl WebCleanupIdentity {
    pub fn validate(&self) -> Result<(), PlatformError> {
        persistence::validate_record(&self.record)?;
        if PublicationRef::package(self.record.publication.scope.clone(), &self.record.package)?
            != self.record.publication
            || !matches!(
                self.record.state,
                ReleaseLifecycleState::Retired | ReleaseLifecycleState::Revoked
            )
        {
            return Err(corrupt("web-cleanup-identity"));
        }
        Ok(())
    }
    pub(super) fn entry(&self) -> Entry {
        Entry {
            deleted: true,
            record: self.record.clone(),
            completion: self.completion.clone(),
            layout: None,
            projection: None,
            grant: None,
            generation: Arc::new(WebGeneration::new(self.record.generation)),
        }
    }
}
impl WebCatalog {
    pub(in crate::local_repository) fn cleanup_identity(
        &self,
        publication: &PublicationRef,
    ) -> Result<WebCleanupIdentity, PlatformError> {
        let state = self.state.try_read().map_err(|_| busy())?;
        let entry = state
            .entries
            .get(&publication.id)
            .filter(|e| e.deleted && e.record.publication == *publication && e.layout.is_some())
            .ok_or_else(crate::publication_retention::unavailable_target)?;
        let identity = WebCleanupIdentity {
            record: entry.record.clone(),
            completion: entry.completion.clone(),
        };
        identity.validate()?;
        Ok(identity)
    }
    /// Called only after synchronized payload removal and durable completion.
    /// Retained rows/receipts/evidence remain charged; only layouts and payload
    /// catalog slots are refunded. Work touches the selected identities only.
    pub(in crate::local_repository) fn finish_cleanup(
        &self,
        identities: &[WebCleanupIdentity],
        index: &mut super::super::CatalogIndex,
    ) -> Result<(), PlatformError> {
        let mut state = self.state.try_write().map_err(|_| busy())?;
        let mut refund = 0usize;
        for identity in identities {
            let entry = state
                .entries
                .get_mut(&identity.record.publication.id)
                .filter(|e| {
                    e.deleted
                        && e.record == identity.record
                        && e.completion == identity.completion
                        && e.layout.is_some()
                })
                .ok_or_else(|| corrupt("web-cleanup-identity-changed"))?;
            let before = entry.retained_bytes()?;
            *entry = identity.entry();
            refund = refund
                .checked_add(
                    before
                        .checked_sub(entry.retained_bytes()?)
                        .ok_or_else(capacity)?,
                )
                .ok_or_else(capacity)?;
        }
        index.refund_reclaimed_web(identities.len(), refund)
    }
}
