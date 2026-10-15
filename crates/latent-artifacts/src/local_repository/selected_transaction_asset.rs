//! Blocking producer for exactly one selected, currently admitted companion.
use std::sync::Arc;

use latent_core::{
    native_capacity::{
        NativeAdmissionClass, NativeBuffer, NativeBufferClass, NativeCapacityOwner,
        NativeReservation,
    },
    PlatformError, PublicationId, ReleaseDigest, TenantId,
};

use super::{resource_exhausted, DirectoryArtifactRepository, Retention};
use crate::SelectedTransactionAsset;

impl DirectoryArtifactRepository {
    /// One finite asset subset from the SAME admitted companion and reservation.
    /// StoredAdmission streams every retained layer/evidence blob; named assets
    /// must match the exact package layout and cannot select another decoder.
    pub fn capture_selected_transaction_layers(
        &self,
        asset: &SelectedTransactionAsset,
        names: &[&str],
        native: &NativeCapacityOwner,
        original: Arc<NativeReservation>,
    ) -> Result<NativeBuffer<crate::SelectedTransactionLayers>, PlatformError> {
        let refused = || resource_exhausted("transaction-layer-original-capacity");
        if !asset.is_from_reservation(&original)
            || !original.is_from_owner(native)
            || original.class() != NativeAdmissionClass::Recovery
            || names.is_empty()
            || names.len() > 16
            || names
                .iter()
                .enumerate()
                .any(|(index, name)| name.len() > 512 || names[..index].contains(name))
        {
            return Err(refused());
        }
        let work = original
            .reserve_buffer(NativeBufferClass::Work, 4 * 1024 * 1024)
            .map_err(|_| refused())?;
        let response = original
            .reserve_buffer(NativeBufferClass::Response, 1024 * 1024)
            .map_err(|_| refused())?;
        let check = || {
            original.with_live(|| ()).map_err(|_| refused())?;
            asset.publication().check_current()
        };
        check()?;
        let _read = self.admission_work.try_lock().map_err(|_| refused())?;
        let selected = self.select_execution_publication(
            asset.publication().tenant().ok_or_else(refused)?,
            asset.publication().release(),
            Some(asset.publication().publication()),
        )?;
        let mut limits = self.repository_read_limits();
        limits.maximum_metadata_document_bytes =
            limits.maximum_metadata_document_bytes.min(64 * 1024);
        limits.maximum_manifest_document_bytes =
            limits.maximum_manifest_document_bytes.min(64 * 1024);
        let directory = self.publication_path(asset.publication().publication());
        let verified = self.load_complete_entry_with_metadata_budget(
            &directory,
            Retention::Metadata,
            limits,
            Some(512 * 1024),
        )?;
        self.verify_publication_index(&selected, &verified)?;
        if &verified.metadata != asset.metadata() {
            return Err(super::corrupt("transaction-layer-original-metadata"));
        }
        let stored = verified.admission.as_ref().ok_or_else(refused)?;
        let inputs =
            stored.selected_asset_layers(&directory, asset.publication(), names, &check)?;
        if inputs.retained_bytes() > 1024 * 1024 {
            return Err(refused());
        }
        check()?;
        let inputs = response.attach(inputs);
        drop(work);
        Ok(inputs)
    }

    /// Call only on the already admitted finite blocking recovery worker.
    /// The actual original job must own the same node's NativeCapacityOwner.
    /// Neither catalog choice nor proof is refreshed during this operation.
    /// Large component/asset/evidence payloads are streamed, never copied into
    /// the response. Slow/stuck file I/O keeps the original worker physically
    /// charged; returning after expiry cannot authorize installation.
    pub fn capture_selected_transaction_asset(
        &self,
        tenant: &TenantId,
        release: &ReleaseDigest,
        publication: &PublicationId,
        native: &NativeCapacityOwner,
        original: Arc<NativeReservation>,
    ) -> Result<NativeBuffer<SelectedTransactionAsset>, PlatformError> {
        self.capture_selected_transaction_asset_profile(
            tenant,
            release,
            publication,
            native,
            original,
            crate::TransactionAssetProfile::Broad,
        )
    }

    /// Stricter streamed control profile for a reviewed finite worker. Complete
    /// component, package and detached evidence associations are unchanged;
    /// oversized documents/metadata refuse before decoding or response transfer.
    #[allow(clippy::too_many_arguments)]
    pub fn capture_selected_transaction_asset_profile(
        &self,
        tenant: &TenantId,
        release: &ReleaseDigest,
        publication: &PublicationId,
        native: &NativeCapacityOwner,
        original: Arc<NativeReservation>,
        profile: crate::TransactionAssetProfile,
    ) -> Result<NativeBuffer<SelectedTransactionAsset>, PlatformError> {
        let exhausted = || resource_exhausted("transaction-asset-original-capacity");
        if !original.is_from_owner(native)
            || original.class() != NativeAdmissionClass::Recovery
            || tenant.0.capacity() > 512
            || release.0.capacity() > 71
            || self.admission.is_none()
        {
            return Err(exhausted());
        }
        // Guards precede every source clone, document parse and filesystem read.
        let work = original
            .reserve_buffer(NativeBufferClass::Work, profile.work_bytes())
            .map_err(|_| exhausted())?;
        let response = original
            .reserve_buffer(NativeBufferClass::Response, profile.response_bytes())
            .map_err(|_| exhausted())?;
        let check = || original.with_live(|| ()).map_err(|_| exhausted());
        check()?;
        let _read = self.admission_work.try_lock().map_err(|_| exhausted())?;
        let selected = self.select_execution_publication(tenant, release, Some(publication))?;
        let grant = self.publication_execution_eligibility(&selected)?;
        if grant.admission().is_none() || grant.web_projection().is_some() {
            return Err(super::corrupt("transaction-asset-not-admitted-capsule"));
        }
        let mut limits = self.repository_read_limits();
        limits.maximum_metadata_document_bytes = limits
            .maximum_metadata_document_bytes
            .min(profile.document_bytes());
        limits.maximum_manifest_document_bytes = limits
            .maximum_manifest_document_bytes
            .min(profile.document_bytes());
        check()?;
        grant.check_current()?;
        let directory = self.publication_path(publication);
        let verified = self.load_complete_entry_with_metadata_budget(
            &directory,
            Retention::Metadata,
            limits,
            Some(profile.metadata_bytes()),
        )?;
        self.verify_publication_index(&selected, &verified)?;
        verified.metadata.verify_requested(release)?;
        check()?;
        grant.check_current()?;
        let stored = verified
            .admission
            .as_ref()
            .ok_or_else(|| super::corrupt("transaction-asset-admission"))?;
        let (declaration, asset_digest, http_requirements) = stored.transaction_asset(
            &directory,
            &grant,
            &verified.metadata,
            &self.codec,
            &check,
            profile,
        )?;
        check()?;
        // Recheck this original proof, without selecting or minting a new one.
        grant.check_current()?;
        self.verify_publication_index(&selected, &verified)?;
        let value = SelectedTransactionAsset {
            metadata: verified.metadata,
            declaration,
            publication: grant,
            asset_digest,
            http_requirements,
            original: Arc::clone(&original),
        };
        if value.retained_bytes() > profile.response_bytes() as usize {
            return Err(resource_exhausted("transaction-asset-response-capacity"));
        }
        let response = response.attach(value);
        drop(work);
        check()?;
        Ok(response)
    }
}
