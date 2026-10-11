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
use crate::{
    selected_transaction_asset::{CONTROL_METADATA_BYTES, DOCUMENT_BYTES},
    SelectedTransactionAsset, TRANSACTION_ASSET_RESPONSE_BYTES, TRANSACTION_ASSET_WORK_BYTES,
};

impl DirectoryArtifactRepository {
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
            .reserve_buffer(NativeBufferClass::Work, TRANSACTION_ASSET_WORK_BYTES)
            .map_err(|_| exhausted())?;
        let response = original
            .reserve_buffer(
                NativeBufferClass::Response,
                TRANSACTION_ASSET_RESPONSE_BYTES,
            )
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
        limits.maximum_metadata_document_bytes =
            limits.maximum_metadata_document_bytes.min(DOCUMENT_BYTES);
        limits.maximum_manifest_document_bytes =
            limits.maximum_manifest_document_bytes.min(DOCUMENT_BYTES);
        check()?;
        grant.check_current()?;
        let directory = self.publication_path(publication);
        let verified = self.load_complete_entry_with_metadata_budget(
            &directory,
            Retention::Metadata,
            limits,
            Some(CONTROL_METADATA_BYTES),
        )?;
        self.verify_publication_index(&selected, &verified)?;
        verified.metadata.verify_requested(release)?;
        check()?;
        grant.check_current()?;
        let stored = verified
            .admission
            .as_ref()
            .ok_or_else(|| super::corrupt("transaction-asset-admission"))?;
        let (declaration, asset_digest) = stored.transaction_asset(
            &directory,
            &grant,
            &verified.metadata,
            &self.codec,
            &check,
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
            original: Arc::clone(&original),
        };
        if value.retained_bytes() > TRANSACTION_ASSET_RESPONSE_BYTES as usize {
            return Err(resource_exhausted("transaction-asset-response-capacity"));
        }
        let response = response.attach(value);
        drop(work);
        check()?;
        Ok(response)
    }
}
