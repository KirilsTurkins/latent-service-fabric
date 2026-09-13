mod limits;
pub use limits::SbomEvidenceLimits;

use std::{collections::BTreeMap, fmt};

use latent_artifacts::package::{
    artifact_blob_digest, decode_referrer, package_digest, ArtifactDescriptor, EvidenceKind,
    PackageLimits, PackageSubject, ReferrerManifest, EMPTY_CONFIG_MEDIA_TYPE,
    LAYER_PATH_ANNOTATION, LAYER_ROLE_ANNOTATION, OCI_MANIFEST_MEDIA_TYPE,
};
use latent_core::{ArtifactBlobDigest, PackageDigest, PlatformError};

use crate::PackageBundle;

/// Untrusted detached association bytes. Inspection establishes association with
/// the package's embedded inventory, never publisher authority or admission.
#[derive(Clone, Copy)]
pub struct SbomEvidenceRef<'a> {
    pub manifest: &'a [u8],
    pub config: &'a [u8],
    pub payload: &'a [u8],
}

/// A small owned association manifest borrowing the package's exact BOM bytes.
pub struct SbomEvidence<'a> {
    manifest: Box<[u8]>,
    payload: &'a [u8],
    digest: PackageDigest,
}

impl fmt::Debug for SbomEvidence<'_> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("SbomEvidence")
            .field("digest", &self.digest)
            .field("payload_bytes", &self.payload.len())
            .finish_non_exhaustive()
    }
}

impl SbomEvidence<'_> {
    #[must_use]
    pub fn manifest_bytes(&self) -> &[u8] {
        &self.manifest
    }
    #[must_use]
    pub const fn config_bytes(&self) -> &[u8] {
        b"{}"
    }
    #[must_use]
    pub fn payload_bytes(&self) -> &[u8] {
        self.payload
    }
    #[must_use]
    pub fn digest(&self) -> &PackageDigest {
        &self.digest
    }
    #[must_use]
    pub fn as_ref(&self) -> SbomEvidenceRef<'_> {
        SbomEvidenceRef {
            manifest: &self.manifest,
            config: b"{}",
            payload: self.payload,
        }
    }
}

/// Creates an OCI association using the exact already-checked embedded inventory.
/// The final package identity lives only in this detached manifest, avoiding a
/// circular identity inside its own inventory layer.
pub fn attach_package_sbom(
    package: &PackageBundle,
    limits: SbomEvidenceLimits,
) -> Result<SbomEvidence<'_>, PlatformError> {
    limits.validate()?;
    let embedded = package
        .sbom()
        .ok_or_else(|| crate::invalid("missing-embedded-sbom"))?;
    let payload = package
        .blob(super::SBOM_PATH)
        .expect("checked embedded layer");
    if payload.len() > limits.max_payload_bytes {
        return Err(crate::exceeded("sbom-evidence-payload-limit"));
    }
    let manifest_limit = limits
        .max_total_bytes
        .checked_sub(payload.len() + 2)
        .filter(|remaining| *remaining > 0)
        .ok_or_else(|| crate::exceeded("sbom-evidence-total-limit"))?
        .min(limits.max_manifest_bytes);
    let model = ReferrerManifest {
        schema_version: 2,
        media_type: OCI_MANIFEST_MEDIA_TYPE.to_owned(),
        artifact_type: EvidenceKind::Sbom.artifact_type().to_owned(),
        config: ArtifactDescriptor {
            media_type: EMPTY_CONFIG_MEDIA_TYPE.to_owned(),
            digest: artifact_blob_digest(b"{}"),
            size: 2,
            annotations: None,
        },
        layers: vec![ArtifactDescriptor {
            media_type: EvidenceKind::Sbom.payload_media_type().to_owned(),
            digest: embedded.inventory_digest().clone(),
            size: payload.len() as u64,
            annotations: Some(BTreeMap::from([
                (
                    LAYER_PATH_ANNOTATION.to_owned(),
                    "evidence/sbom.json".to_owned(),
                ),
                (LAYER_ROLE_ANNOTATION.to_owned(), "evidence".to_owned()),
            ])),
        }],
        subject: subject(package),
        annotations: BTreeMap::new(),
    };
    // Subject size retains the package profile's independent 256 KiB ceiling.
    // Only this manifest's serialized bytes use the smaller evidence ceiling.
    let manifest = super::json::encode(&model, manifest_limit)?;
    let evidence = SbomEvidence {
        digest: package_digest(&manifest),
        manifest: manifest.into_boxed_slice(),
        payload,
    };
    inspect_sbom_association(package, evidence.as_ref(), limits)?;
    Ok(evidence)
}

#[derive(Debug)]
#[allow(clippy::struct_field_names)] // Distinguish three different exact identities.
pub struct CheckedSbomAssociation {
    package_digest: PackageDigest,
    inventory_digest: ArtifactBlobDigest,
    referrer_digest: PackageDigest,
}

impl CheckedSbomAssociation {
    #[must_use]
    pub fn package_digest(&self) -> &PackageDigest {
        &self.package_digest
    }
    #[must_use]
    pub fn inventory_digest(&self) -> &ArtifactBlobDigest {
        &self.inventory_digest
    }
    #[must_use]
    pub fn referrer_digest(&self) -> &PackageDigest {
        &self.referrer_digest
    }
}

pub fn inspect_sbom_association(
    package: &PackageBundle,
    evidence: SbomEvidenceRef<'_>,
    limits: SbomEvidenceLimits,
) -> Result<CheckedSbomAssociation, PlatformError> {
    limits.check_one(evidence)?;
    let embedded = package
        .sbom()
        .ok_or_else(|| crate::invalid("missing-embedded-sbom"))?;
    if evidence.config != b"{}" {
        return Err(crate::invalid("sbom-evidence-config-mismatch"));
    }
    let manifest = decode_referrer(evidence.manifest, PackageLimits::default())?;
    if manifest.artifact_type != EvidenceKind::Sbom.artifact_type() {
        return Err(crate::invalid("unsupported-sbom-evidence"));
    }
    if manifest.subject != subject(package) {
        return Err(crate::invalid("sbom-evidence-subject-mismatch"));
    }
    let descriptor = &manifest.layers[0]; // Referrer codec requires exactly one.
    let raw = package
        .blob(super::SBOM_PATH)
        .expect("checked embedded layer");
    if descriptor.digest != *embedded.inventory_digest()
        || descriptor.size != raw.len() as u64
        || artifact_blob_digest(evidence.payload) != descriptor.digest
        || evidence.payload != raw
    {
        return Err(crate::invalid("sbom-evidence-content-mismatch"));
    }
    Ok(CheckedSbomAssociation {
        package_digest: package.layout().digest().clone(),
        inventory_digest: embedded.inventory_digest().clone(),
        referrer_digest: package_digest(evidence.manifest),
    })
}

fn subject(package: &PackageBundle) -> PackageSubject {
    PackageSubject {
        media_type: OCI_MANIFEST_MEDIA_TYPE.to_owned(),
        digest: package.layout().digest().clone(),
        size: package.manifest_bytes().len() as u64,
    }
}
