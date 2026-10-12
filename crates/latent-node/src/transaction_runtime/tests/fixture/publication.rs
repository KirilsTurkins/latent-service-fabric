use super::*;
use latent_artifacts::{
    ArtifactDescriptor, ArtifactRepository, CapsuleArtifact, ContractDescriptor,
    DirectoryArtifactRepositoryConfig, LifecycleScope, ManagedPublicationUpload, ReleaseActor,
    ReleaseActorKind, ReleaseMutationContext, ReleaseOperationPrecondition,
    VerifiedArtifactMetadata,
};
use latent_core::{ArtifactReference, ContractId, TenantId};
use latent_manifest::{DeploymentManifest, JsonManifestCodec, ManifestCodec, TransactionBinding};
use serde_json::{json, Value};
use std::path::Path;

pub(super) async fn publish(
    root: &Path,
) -> (
    DirectoryArtifactRepository,
    VerifiedArtifactMetadata,
    ReleaseUseEligibility,
    DeploymentManifest,
    TransactionBinding,
) {
    // Real publication/currentness; this empty component is never executed.
    let component = b"\0asm\x0d\0\x01\0".to_vec();
    let digest = latent_artifacts::content_digest(&component);
    let mut document: Value = serde_json::from_str(include_str!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../latent-manifest/tests/fixtures/valid-capsule-v1alpha1.json"
    )))
    .unwrap();
    document["component"]["digest"] = digest.0.clone().into();
    document["metadata"]["tenant"] = "a".into();
    document["metadata"]["name"] = "a/echo".into();
    document["component"]["world"] = "a:echo/service@0.1.0".into();
    document["exports"] = json!(["a:echo/api@0.1.0"]);
    let manifest = JsonManifestCodec::default()
        .decode_capsule(&serde_json::to_vec(&document).unwrap())
        .unwrap();
    let catalog = DirectoryArtifactRepository::open(
        root.join("artifacts"),
        DirectoryArtifactRepositoryConfig::default(),
    )
    .unwrap();
    let receipt = catalog
        .publish_managed(
            ReleaseMutationContext {
                scope: LifecycleScope::Tenant(TenantId("a".into())),
                actor: ReleaseActor {
                    subject: "operator".into(),
                    kind: ReleaseActorKind::Administrator,
                },
                operation: Some(ReleaseOperationPrecondition {
                    operation_id: "native-source".into(),
                    expected_generation: 0,
                }),
            },
            ManagedPublicationUpload::Local(CapsuleArtifact {
                descriptor: ArtifactDescriptor {
                    reference: ArtifactReference("local://native-tests/source".into()),
                    release_digest: digest.clone(),
                    media_type: "application/vnd.wasm.component.v1+wasm".into(),
                    size_bytes: component.len() as u64,
                    publisher: None,
                    layers: Vec::new(),
                    annotations: Metadata::new(),
                },
                manifest,
                contracts: vec![ContractDescriptor {
                    id: ContractId("a:echo/api@0.1.0".into()),
                    package_name: "a:echo".into(),
                    semantic_version: "0.1.0".into(),
                    interfaces: Vec::new(),
                    dependencies: Vec::new(),
                    digest: format!("sha256:{}", "3".repeat(64)),
                }],
                component_bytes: component,
            }),
            &mut |_| Ok(()),
        )
        .await
        .unwrap();
    let publication = catalog
        .execution_eligibility_selected(&digest, Some(&receipt.publication.id))
        .unwrap()
        .unwrap();
    let metadata = catalog
        .fetch_verified_metadata_selected(&digest, Some(&receipt.publication.id))
        .await
        .unwrap();
    let mut document: Value = serde_json::from_str(include_str!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../latent-manifest/tests/fixtures/valid-deployment-v1alpha1.json"
    )))
    .unwrap();
    document["metadata"]["name"] = "deploy".into();
    document["metadata"]["tenant"] = "a".into();
    document["spec"]["service"] = "a/echo".into();
    document["spec"]["release"] = digest.0.into();
    document["spec"]["publication"] = publication.publication().as_str().into();
    let deployment = JsonManifestCodec::default()
        .decode_deployment(&serde_json::to_vec(&document).unwrap())
        .unwrap();
    let declaration = TransactionBinding::decode(&serde_json::to_vec(&json!({
        "apiVersion":"latent.dev/v1","kind":"TransactionBinding","capsule":"a/echo","deployment":"deploy","binding":"binding","profile":latent_core::transaction_contract::PROFILE,"hostAbiDigest":latent_manifest::phase4_host_abi_digest(),"namespace":"orders","stateSchema":schema(),
        "operations":[{"operation":"update","mode":"strict-command","inputFormat":"raw-v1","resultFormat":"result-v1"},{"operation":"query","mode":"fresh-query","inputFormat":"raw-v1","resultFormat":"result-v1"}]
    })).unwrap()).unwrap();
    (catalog, metadata, publication, deployment, declaration)
}
