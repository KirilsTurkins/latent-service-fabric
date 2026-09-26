use super::{
    busy, capacity, corrupt, denied, error, storage, Arc, ArtifactBlobDigest,
    DirectoryArtifactRepository, PlatformError, PlatformErrorCode, PublicationRef,
    ReleaseLifecycleState, WebBlobRead, WebPublicationStatus, WebReadSnapshot, WebSelection,
    WebUseEligibility,
};
use crate::{ReleaseEligibilityReason as Reason, ReleaseLiveEligibility as Live};

impl DirectoryArtifactRepository {
    /// Select an exact current web association. No alias lookup, fallback to a
    /// component, or pairing with an independently supplied asset tree occurs.
    pub fn select_web_publication(
        &self,
        reference: &PublicationRef,
    ) -> Result<WebSelection, PlatformError> {
        self.web_selection(reference, 0)
    }
    fn web_selection(
        &self,
        reference: &PublicationRef,
        payload_bytes: usize,
    ) -> Result<WebSelection, PlatformError> {
        self.web.epoch.check()?;
        let state = self.web.state.try_read().map_err(|_| busy())?;
        let entry = state.entry(reference)?;
        if entry.record.state != ReleaseLifecycleState::Admitted {
            return Err(denied());
        }
        let grant = entry.grant.as_ref().ok_or_else(denied)?;
        let bytes = entry
            .retained_bytes()?
            .checked_add(payload_bytes)
            .and_then(|n| n.checked_add(4096))
            .ok_or_else(capacity)?;
        let permit = self.web.reads.reserve(bytes)?;
        let token = WebUseEligibility::new(
            reference.clone(),
            Arc::clone(&entry.layout),
            Arc::clone(grant),
            Arc::clone(&self.web.epoch),
            Arc::clone(&entry.generation),
            entry.record.generation,
            Arc::clone(&permit),
        )?;
        drop(state);
        token.check_current(reference.scope.tenant().ok_or_else(denied)?)?;
        Ok(WebSelection {
            eligibility: token,
            _permit: permit,
        })
    }
    /// Historical status never supplies permission to render or serve bytes.
    pub fn web_publication_status(
        &self,
        reference: &PublicationRef,
    ) -> Result<WebPublicationStatus, PlatformError> {
        let state = self.web.state.try_read().map_err(|_| busy())?;
        let entry = state.entry(reference)?;
        let record = entry.record.clone();
        let renderer = entry.layout.manifest().renderer.clone();
        drop(state);
        let (eligibility, eligibility_reason) = match record.state {
            ReleaseLifecycleState::Revoked => (Live::Denied, Reason::Revoked),
            ReleaseLifecycleState::Retired => (Live::Denied, Reason::Retired),
            ReleaseLifecycleState::Admitted => match self.select_web_publication(reference) {
                Ok(_) => (Live::Eligible, Reason::Verified),
                Err(failure) if failure.code == PlatformErrorCode::PermissionDenied => {
                    (Live::Denied, Reason::PolicyDenied)
                }
                Err(failure) if failure.code == PlatformErrorCode::IncompatibleContract => {
                    (Live::Denied, Reason::RuntimeIncompatible)
                }
                Err(_) => (Live::Unknown, Reason::AuthorityUnavailable),
            },
        };
        Ok(WebPublicationStatus {
            record,
            eligibility,
            eligibility_reason,
            renderer,
        })
    }
    pub fn web_read_snapshot(&self) -> Result<WebReadSnapshot, PlatformError> {
        self.web.reads.snapshot()
    }

    /// Only a named public allowlist entry can be read. Metadata, SBOMs,
    /// provenance and the renderer remain private even if stored as Asset layers.
    pub fn read_web_asset(
        &self,
        reference: &PublicationRef,
        path: &str,
    ) -> Result<WebBlobRead, PlatformError> {
        let state = self.web.state.try_read().map_err(|_| busy())?;
        let asset = state
            .entry(reference)?
            .layout
            .asset(path)
            .ok_or_else(|| error(PlatformErrorCode::NotFound, "web-public-asset-not-found"))?;
        let size = usize::try_from(asset.size).map_err(|_| capacity())?;
        let layer = asset.layer.clone();
        let digest = asset
            .digest
            .parse()
            .map_err(|_| corrupt("web-asset-digest"))?;
        let media_type = asset.media_type.clone();
        drop(state);
        self.read_web_blob(reference, &layer, &digest, size, &media_type)
    }
    /// The generic renderer must still validate its preparation/execution profile
    /// and use the returned guarded acceptance boundary before starting a call.
    pub fn read_web_renderer(
        &self,
        reference: &PublicationRef,
    ) -> Result<WebBlobRead, PlatformError> {
        let state = self.web.state.try_read().map_err(|_| busy())?;
        let renderer = state
            .entry(reference)?
            .layout
            .manifest()
            .renderer
            .as_ref()
            .ok_or_else(|| {
                error(
                    PlatformErrorCode::IncompatibleContract,
                    "web-publication-has-no-renderer",
                )
            })?;
        let size = usize::try_from(renderer.size).map_err(|_| capacity())?;
        let layer = renderer.layer.clone();
        let digest = renderer
            .digest
            .parse()
            .map_err(|_| corrupt("web-renderer-digest"))?;
        drop(state);
        self.read_web_blob(
            reference,
            &layer,
            &digest,
            size,
            crate::package::COMPONENT_MEDIA_TYPE,
        )
    }
    fn read_web_blob(
        &self,
        reference: &PublicationRef,
        path: &str,
        digest: &ArtifactBlobDigest,
        size: usize,
        media: &str,
    ) -> Result<WebBlobRead, PlatformError> {
        // Reserve for the bounded header as well as the actual buffer, before
        // opening or allocating either. A copied token retains this reservation.
        let selection = self.web_selection(
            reference,
            size.checked_add(self.web_authority()?.limits.max_document_bytes * 8)
                .ok_or_else(capacity)?,
        )?;
        let stored = storage::Stored::read_header(
            &self.web_publication_path(&reference.id),
            self.web_authority()?.limits,
            self.config.max_component_bytes,
        )?;
        let state = self.web.state.try_read().map_err(|_| busy())?;
        if stored.digest()? != state.entry(reference)?.completion {
            return Err(corrupt("web-publication-changed"));
        }
        drop(state);
        let layer = stored
            .layers
            .iter()
            .find(|layer| layer.path == path)
            .ok_or_else(|| corrupt("web-layer-missing"))?;
        if layer.blob.digest != digest.as_str() || layer.blob.size != size as u64 {
            return Err(corrupt("web-layer-association"));
        }
        let bytes = super::super::admission_storage::read::read_blob(
            &self.web_publication_path(&reference.id),
            &layer.blob,
            size,
        )?;
        selection
            .eligibility
            .check_current(reference.scope.tenant().ok_or_else(denied)?)?;
        Ok(WebBlobRead {
            selection,
            bytes: bytes.into_boxed_slice(),
            media_type: media.into(),
        })
    }
}
