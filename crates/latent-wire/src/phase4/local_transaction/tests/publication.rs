//! A real maintained compiled component in a trusted-local test catalog.
//! Publisher/builder qualification remains a separate signed-package campaign.
use super::*;
use latent_artifacts::*;
use latent_core::{ArtifactReference, ContractId, Metadata, TenantId};
use latent_manifest::{DeploymentManifest, JsonManifestCodec, ManifestCodec, TransactionBinding};
use serde_json::{json, Value};
use std::{fs, path::PathBuf};

pub(super) const TENANT: &str = "examples";
pub(super) const SERVICE: &str = "examples/transaction-rust-aggregate";
pub(super) const CONTRACT: &str = "examples:transactional-aggregate/api@1.0.0";
pub(super) const NAMESPACE: &str = "transactional-aggregate";
pub(super) const FORMAT: &str = "lsf-wit-values-v1";

pub(super) async fn publish(
    catalog: &DirectoryArtifactRepository,
) -> (
    ReleaseUseEligibility,
    VerifiedArtifactMetadata,
    DeploymentManifest,
    TransactionBinding,
) {
    let root = PathBuf::from(
        std::env::var_os("LSF_TRANSACTION_GUEST_ROOT")
            .expect("maintained compiled transaction fixture root"),
    );
    let root = root.join("aggregate");
    let report: Value =
        serde_json::from_slice(&fs::read(root.join("report.json")).unwrap()).unwrap();
    assert_eq!(report["compiled"], true);
    assert_eq!(report["language"], "rust");
    assert_eq!(report["variant"], "aggregate");
    let component = fs::read(root.join("component.wasm")).unwrap();
    assert!(
        component.len() > 8,
        "an empty component cannot count as execution"
    );
    let digest = latent_artifacts::content_digest(&component);
    assert_eq!(report["componentDigest"].as_str(), Some(digest.0.as_str()));
    let locks: Value =
        serde_json::from_slice(&fs::read(root.join("project/sdk-lock.json")).unwrap()).unwrap();
    assert_eq!(
        locks["template"]["componentDigest"],
        latent_artifacts::content_digest(include_bytes!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../examples/rust-capsules/transactional-aggregate/component.rs"
        )))
        .0
    );
    assert_eq!(
        locks["template"]["witDigest"],
        latent_artifacts::content_digest(include_bytes!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../examples/rust-capsules/transactional-aggregate/world.wit"
        )))
        .0
    );
    let mut document: Value = serde_json::from_slice(include_bytes!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../latent-manifest/tests/fixtures/valid-capsule-v1alpha1.json"
    )))
    .unwrap();
    document["component"]["digest"] = digest.0.clone().into();
    document["component"]["world"] = "examples:transactional-aggregate/service@1.0.0".into();
    document["component"]["version"] = "1.0.0".into();
    document["metadata"]["tenant"] = TENANT.into();
    document["metadata"]["name"] = SERVICE.into();
    document["exports"] = json!([CONTRACT]);
    document["imports"] = json!([{"contract":latent_capabilities::namespace::STATE_CONTRACT,"optional":false},{"contract":latent_capabilities::namespace::INTENT_CONTRACT,"optional":false}]);
    document["execution"]["threading"] = "single-threaded".into();
    document["execution"]["snapshotEligible"] = false.into();
    document["execution"]["fusionEligible"] = false.into();
    document["execution"]["limits"] = json!({"cpuFuel":100_000_000,"memoryBytes":64*1024*1024,"wallTimeLimitMillis":10_000,"childCalls":0,"outboundRequests":0,"stateReadBytes":4*1024*1024,"stateWriteBytes":2*1024*1024,"blobReadBytes":0,"blobWriteBytes":0,"logBytes":0,"effectCount":32});
    let manifest = JsonManifestCodec::default()
        .decode_capsule(&serde_json::to_vec(&document).unwrap())
        .unwrap();
    let receipt = catalog
        .publish_managed(
            ReleaseMutationContext {
                scope: LifecycleScope::Tenant(TenantId(TENANT.into())),
                actor: ReleaseActor {
                    subject: "compiled-guest-test-operator".into(),
                    kind: ReleaseActorKind::Administrator,
                },
                operation: Some(ReleaseOperationPrecondition {
                    operation_id: "actual-aggregate-source".into(),
                    expected_generation: 0,
                }),
            },
            ManagedPublicationUpload::Local(CapsuleArtifact {
                descriptor: ArtifactDescriptor {
                    reference: ArtifactReference("local://compiled-guest/aggregate".into()),
                    release_digest: digest.clone(),
                    media_type: "application/vnd.wasm.component.v1+wasm".into(),
                    size_bytes: component.len() as u64,
                    publisher: None,
                    layers: Vec::new(),
                    annotations: Metadata::new(),
                },
                manifest,
                contracts: vec![ContractDescriptor {
                    id: ContractId(CONTRACT.into()),
                    package_name: "examples:transactional-aggregate".into(),
                    semantic_version: "1.0.0".into(),
                    interfaces: Vec::new(),
                    dependencies: Vec::new(),
                    digest: latent_artifacts::content_digest(include_bytes!(concat!(
                        env!("CARGO_MANIFEST_DIR"),
                        "/../../examples/rust-capsules/transactional-aggregate/world.wit"
                    )))
                    .0,
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
    let mut document: Value = serde_json::from_slice(include_bytes!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../latent-manifest/tests/fixtures/valid-deployment-v1alpha1.json"
    )))
    .unwrap();
    document["metadata"]["tenant"] = TENANT.into();
    document["metadata"]["name"] = "transaction-rust-aggregate".into();
    document["spec"]["service"] = SERVICE.into();
    document["spec"]["release"] = digest.0.into();
    document["spec"]["publication"] = publication.publication().as_str().into();
    document["spec"]["resources"] = json!({"cpuFuel":100_000_000,"memoryBytes":64*1024*1024,"wallTimeLimitMillis":10_000,"childCalls":0,"outboundRequests":0,"stateReadBytes":4*1024*1024,"stateWriteBytes":2*1024*1024,"blobReadBytes":0,"blobWriteBytes":0,"logBytes":0,"effectCount":32});
    document["spec"]["placement"] =
        json!({"trustClass":"sandbox","architectures":[std::env::consts::ARCH]});
    let deployment = JsonManifestCodec::default()
        .decode_deployment(&serde_json::to_vec(&document).unwrap())
        .unwrap();
    let declaration = TransactionBinding::decode(
        &fs::read(root.join("project/transaction-binding.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(declaration.namespace, NAMESPACE);
    (publication, metadata, deployment, declaration)
}
