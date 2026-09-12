use latent_artifacts::{AdmissionAuthority, AdmissionBinding, PackageAdmissionUpload};
use latent_core::{PlatformErrorCode, TenantId};

use super::super::receipt::Receipt;
use super::{Fixture, SupplyChainAuthority};

fn corrupt_field(binding: &AdmissionBinding, field: &str) -> AdmissionBinding {
    let mut changed = binding.clone();
    let mut receipt: Receipt = serde_json::from_slice(&binding.receipt).unwrap();
    let digest = format!("sha256:{}", "0".repeat(64));
    match field {
        "publisherKey" => receipt.publisher_key = digest,
        "signatureManifest" => receipt.signature_manifest = digest,
        "signaturePayload" => receipt.signature_payload = digest,
        "builderKey" => receipt.builder_key = digest,
        "provenanceManifest" => receipt.provenance_manifest = digest,
        "provenancePayload" => receipt.provenance_payload = digest,
        "sbomInventory" => receipt.sbom_inventory = Some(digest),
        "sbomReferrer" => receipt.sbom_referrer = Some(digest),
        "publisher" => receipt.publisher = "different-publisher".to_owned(),
        "builder" => receipt.builder = "different-builder".to_owned(),
        _ => unreachable!(),
    }
    changed.receipt = receipt.encode().unwrap();
    Receipt::validate_history(&changed).unwrap(); // Shape/digests remain canonical.
    changed
}

#[test]
fn canonical_wrong_receipt_identities_are_corruption_even_after_expiry() {
    let fixture = Fixture::new();
    let root = tempfile::tempdir().unwrap();
    let owner =
        SupplyChainAuthority::open(root.path(), fixture.approved(), fixture.clock.clone(), 5)
            .unwrap();
    let binding = owner
        .verify(&TenantId("tests".to_owned()), fixture.upload())
        .unwrap()
        .grant
        .binding()
        .clone();
    fixture.clock.set(2000);
    for field in [
        "publisherKey",
        "signatureManifest",
        "signaturePayload",
        "builderKey",
        "provenanceManifest",
        "provenancePayload",
        "sbomInventory",
        "sbomReferrer",
        "publisher",
        "builder",
    ] {
        let changed = corrupt_field(&binding, field);
        assert_eq!(
            owner
                .recover(&changed, fixture.upload())
                .err()
                .unwrap()
                .code,
            PlatformErrorCode::CorruptArtifact,
            "{field}"
        );
    }
    assert_eq!(
        owner
            .recover(&binding, fixture.upload())
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::PermissionDenied
    );
}

#[test]
fn supplied_detached_sbom_must_be_the_historical_exact_association() {
    let fixture = Fixture::new();
    let root = tempfile::tempdir().unwrap();
    let owner =
        SupplyChainAuthority::open(root.path(), fixture.approved(), fixture.clock.clone(), 5)
            .unwrap();
    let mut upload = fixture.upload();
    let bundle = latent_packaging::inspect_bundle(
        latent_packaging::BundleInput {
            manifest: upload.manifest,
            configuration: upload.configuration,
            layers: upload.layers,
        },
        latent_packaging::PackagingLimits::default(),
    )
    .unwrap();
    let association = latent_packaging::attach_package_sbom(
        &bundle,
        latent_packaging::SbomEvidenceLimits::default(),
    )
    .unwrap();
    upload.sboms.push(latent_artifacts::AdmissionEvidence {
        manifest: association.manifest_bytes().to_vec(),
        configuration: association.config_bytes().to_vec(),
        payload: association.payload_bytes().to_vec(),
    });
    drop(association);
    let input = bundle.into_input();
    upload.manifest = input.manifest;
    upload.configuration = input.configuration;
    upload.layers = input.layers;
    let admitted = owner.verify(&TenantId("tests".to_owned()), upload).unwrap();
    let binding = admitted.grant.binding().clone();
    let checked = Receipt::validate_retained(&binding, admitted.upload).unwrap();
    fixture.clock.set(2000);
    let missing = PackageAdmissionUpload {
        sboms: Vec::new(),
        ..checked
    };
    assert_eq!(
        owner.recover(&binding, missing).err().unwrap().code,
        PlatformErrorCode::CorruptArtifact
    );
}
