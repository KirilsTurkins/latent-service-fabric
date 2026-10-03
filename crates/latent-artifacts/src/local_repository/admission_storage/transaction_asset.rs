//! Associate small control documents without materializing the package layers.
use std::path::Path;

use latent_core::{ArtifactBlobDigest, PlatformError};
use latent_manifest::{JsonManifestCodec, ManifestCodec, TransactionBinding};

use super::{read::read_blob, StoredAdmission};
use crate::local_repository::{
    contract_metadata::parse_control_document, corrupt, resource_exhausted,
};
use crate::package::{
    decode_referrer, inspect_package, EvidenceKind, LayerRole, PackageKind, PackageLimits,
};
use crate::selected_transaction_asset::{
    COMPANION_BYTES, COMPANION_MEDIA_TYPE, COMPANION_PATH, CONTROL_METADATA_BYTES, DOCUMENT_BYTES,
};
use crate::{
    decode_contract_metadata, ContractMetadataLimits, ReleaseUseEligibility,
    VerifiedArtifactMetadata,
};

impl StoredAdmission {
    #[expect(
        clippy::too_many_lines,
        reason = "Independent package, layer, metadata and detached evidence associations remain explicit"
    )]
    pub(in crate::local_repository) fn transaction_asset(
        &self,
        directory: &Path,
        grant: &ReleaseUseEligibility,
        metadata: &VerifiedArtifactMetadata,
        codec: &JsonManifestCodec,
        check: &dyn Fn() -> Result<(), PlatformError>,
    ) -> Result<(TransactionBinding, ArtifactBlobDigest), PlatformError> {
        check()?;
        let manifest = read_blob(directory, &self.manifest, DOCUMENT_BYTES)?;
        let configuration = read_blob(directory, &self.configuration, DOCUMENT_BYTES)?;
        let layout = inspect_package(&manifest, &configuration, PackageLimits::default())?;
        if grant.tenant().map(|tenant| tenant.0.as_str()) != Some(self.tenant.as_str())
            || grant.package().map(|package| package.as_str()) != Some(self.package.as_str())
            || grant.release().0 != self.release
            || layout.digest().as_str() != self.package
            || layout.config().kind != PackageKind::Capsule
            || metadata.verified_digest().0 != self.release
            || metadata
                .manifest()
                .metadata
                .tenant
                .as_ref()
                .is_some_and(|tenant| tenant.0 != self.tenant)
            || layout.config().layers.len() != self.layers.len()
        {
            return Err(corrupt("transaction-asset-package-association"));
        }
        let mut companion = None;
        for (layer, stored) in layout.config().layers.iter().zip(&self.layers) {
            check()?;
            if layer.path != stored.path
                || layer.digest.as_str() != stored.blob.digest
                || layer.size != stored.blob.size
            {
                return Err(corrupt("transaction-asset-layer-association"));
            }
            // StoredAdmission::read streamed every auxiliary blob and the
            // enclosing COMPLETE reader streamed the component before this
            // structural comparison. Only these three small documents allocate.
            match layer.role {
                LayerRole::Component => {
                    if layer.digest.as_str() != metadata.verified_digest().0
                        || layer.size != metadata.descriptor().size_bytes
                    {
                        return Err(corrupt("transaction-asset-component-association"));
                    }
                }
                LayerRole::CapsuleManifest => {
                    let bytes = read_blob(directory, &stored.blob, DOCUMENT_BYTES)?;
                    drop(parse_control_document(
                        &bytes,
                        DOCUMENT_BYTES,
                        CONTROL_METADATA_BYTES,
                    )?);
                    let actual = codec
                        .decode_capsule(&bytes)
                        .map_err(|_| corrupt("transaction-asset-capsule"))?;
                    if &actual != metadata.manifest() {
                        return Err(corrupt("transaction-asset-capsule-association"));
                    }
                }
                LayerRole::Contracts => {
                    let bytes = read_blob(directory, &stored.blob, DOCUMENT_BYTES)?;
                    let actual = decode_contract_metadata(
                        &bytes,
                        ContractMetadataLimits {
                            max_document_bytes: DOCUMENT_BYTES,
                            max_retained_bytes: CONTROL_METADATA_BYTES,
                            ..ContractMetadataLimits::default()
                        },
                    )?;
                    if actual != metadata.contracts() {
                        return Err(corrupt("transaction-asset-contract-association"));
                    }
                }
                LayerRole::Asset if layer.path == COMPANION_PATH => {
                    if companion.is_some()
                        || layer.media_type != COMPANION_MEDIA_TYPE
                        || layer.size > COMPANION_BYTES as u64
                    {
                        return Err(resource_exhausted("transaction-asset-companion-shape"));
                    }
                    let bytes = read_blob(directory, &stored.blob, COMPANION_BYTES)?;
                    let declaration = TransactionBinding::decode(&bytes)
                        .map_err(|_| corrupt("transaction-asset-companion"))?;
                    if declaration.capsule != metadata.manifest().metadata.name {
                        return Err(corrupt("transaction-asset-companion-capsule"));
                    }
                    companion = Some((declaration, layer.digest.clone()));
                }
                LayerRole::Renderer => return Err(corrupt("transaction-asset-renderer")),
                LayerRole::WitLock | LayerRole::Asset => {}
            }
        }
        for (kind, entries) in [
            (EvidenceKind::Signature, &self.signatures),
            (EvidenceKind::Provenance, &self.provenance),
            (EvidenceKind::Sbom, &self.sboms),
        ] {
            for entry in entries {
                check()?;
                let bytes = read_blob(directory, &entry.manifest, DOCUMENT_BYTES)?;
                let evidence = decode_referrer(&bytes, PackageLimits::default())?;
                let config = read_blob(directory, &entry.configuration, DOCUMENT_BYTES)?;
                if evidence.artifact_type != kind.artifact_type()
                    || evidence.subject.digest != *layout.digest()
                    || evidence.subject.size != manifest.len() as u64
                    || config != b"{}"
                    || evidence.config.digest.as_str() != entry.configuration.digest
                    || evidence.config.size != entry.configuration.size
                    || evidence.layers.len() != 1
                    || evidence.layers[0].digest.as_str() != entry.payload.digest
                    || evidence.layers[0].size != entry.payload.size
                {
                    return Err(corrupt("transaction-asset-evidence-association"));
                }
            }
        }
        companion.ok_or_else(|| corrupt("transaction-asset-companion-missing"))
    }
}
