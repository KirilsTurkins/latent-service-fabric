use latent_artifacts::{ArtifactDescriptor, CapsuleArtifact, DevelopmentTestArtifact};
use latent_core::{ArtifactReference, Metadata, TenantId};
use latent_manifest::{
    JsonManifestCodec, ManifestCodec, ManifestValidator, Phase1ManifestValidator,
};

fn artifact() -> CapsuleArtifact {
    let component_bytes = b"\0asm\x0d\0\x01\0".to_vec();
    let digest = latent_artifacts::content_digest(&component_bytes);
    let mut manifest = JsonManifestCodec::default()
        .decode_capsule(include_bytes!(
            "../../../examples/echo-contract/capsule.json"
        ))
        .unwrap();
    manifest.component_digest = digest.clone();
    manifest.metadata.tenant = None;
    manifest.metadata.name = "test".into();
    Phase1ManifestValidator.validate_capsule(&manifest).unwrap();
    CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference("local://controlled-test".into()),
            release_digest: digest,
            media_type: "application/vnd.wasm.component.v1+wasm".into(),
            size_bytes: component_bytes.len() as u64,
            publisher: None,
            layers: vec![],
            annotations: Metadata::new(),
        },
        manifest,
        contracts: vec![],
        component_bytes,
    }
}

#[test]
fn test_owner_seals_are_distinct_and_retire_on_drop() {
    let first = DevelopmentTestArtifact::new(artifact(), TenantId("tests".into())).unwrap();
    let second = DevelopmentTestArtifact::new(artifact(), TenantId("tests".into())).unwrap();
    let proof = first.eligibility().clone();
    proof.check_for_catalog(&first.authority()).unwrap();
    assert!(proof.check_for_catalog(&second.authority()).is_err());
    assert!(proof.admission().is_none());
    assert!(proof.authorize_tenant(&TenantId("other".into())).is_err());
    drop(first);
    assert!(proof.check_current().is_err());
    second.eligibility().check_current().unwrap();
}

#[test]
fn test_owner_rejects_mismatched_bytes_and_tenant() {
    let mut changed = artifact();
    changed.component_bytes.push(0);
    assert!(DevelopmentTestArtifact::new(changed, TenantId("tests".into())).is_err());
    let mut changed = artifact();
    changed.manifest.metadata.tenant = Some(TenantId("other".into()));
    assert!(DevelopmentTestArtifact::new(changed, TenantId("tests".into())).is_err());
}
