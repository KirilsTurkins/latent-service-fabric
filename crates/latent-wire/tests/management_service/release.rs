#[path = "release/authorization.rs"]
mod authorization;
#[path = "release/pagination.rs"]
mod pagination;

use latent_artifacts::{encode_contract_metadata, CapsuleArtifact, ContractMetadataLimits};
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use latent_wire::management::{proto, ManagementLimits};
use tonic::Status;

use super::support::{artifact, deployment, request, Harness};

fn upload(artifact: &CapsuleArtifact) -> proto::PublishReleaseRequest {
    proto::PublishReleaseRequest {
        release: None,
        artifact: Some(proto::CapsuleArtifactUpload {
            capsule_manifest_json: JsonManifestCodec::default()
                .encode_capsule(&artifact.manifest)
                .unwrap(),
            component_bytes: artifact.component_bytes.clone(),
            component_digest: artifact.descriptor.release_digest.0.clone(),
            component_media_type: artifact.descriptor.media_type.clone(),
            contract_metadata_json: encode_contract_metadata(
                &artifact.contracts,
                ContractMetadataLimits::default(),
            )
            .unwrap(),
        }),
    }
}

async fn publish(
    harness: &Harness,
    identity: &str,
    value: proto::PublishReleaseRequest,
) -> Result<proto::ReleaseDescriptor, Status> {
    harness
        .releases_client()
        .publish_release(request(identity, value))
        .await
        .map(|response| response.into_inner().release.unwrap())
}

async fn get(harness: &Harness, identity: &str, digest: &str) -> Option<proto::ReleaseDescriptor> {
    harness
        .releases_client()
        .get_release(request(
            identity,
            proto::GetReleaseRequest {
                digest: digest.to_owned(),
            },
        ))
        .await
        .unwrap()
        .into_inner()
        .release
}

async fn list(
    harness: &Harness,
    identity: &str,
    service: Option<&str>,
    page: Option<proto::PageRequest>,
) -> Result<proto::ListReleasesResponse, Status> {
    harness
        .releases_client()
        .list_releases(request(
            identity,
            proto::ListReleasesRequest {
                service: service.map(str::to_owned),
                page,
            },
        ))
        .await
        .map(tonic::Response::into_inner)
}

#[tokio::test]
async fn published_typed_capsule_can_be_deployed_without_editing_the_data_directory() {
    let harness = Harness::new(ManagementLimits::default()).await;
    let capsule = artifact("acme", "echo", "rpc-publish-deploy");
    let mut message = upload(&capsule);
    message.release = Some(proto::ReleaseDescriptor {
        annotations: [("inert.auth.claim".to_owned(), "operator=true".to_owned())].into(),
        ..proto::ReleaseDescriptor::default()
    });
    let release = publish(&harness, "alice", message.clone()).await.unwrap();
    assert_eq!(release.digest, capsule.descriptor.release_digest.0);
    assert_eq!(release.tenant.as_deref(), Some("acme"));
    assert_eq!(release.service, "echo");
    assert_eq!(release.world, capsule.manifest.world.0);
    assert_eq!(release.semantic_version, "1.0.0");
    assert_eq!(
        release.artifact_reference,
        format!("local:release:{}", release.digest)
    );
    assert_eq!(release.size_bytes, capsule.descriptor.size_bytes);
    assert!(release.publisher.is_empty());
    assert_eq!(release.created_at_unix_millis, 0);
    assert!(release.admitted);
    assert_eq!(release.annotations["inert.auth.claim"], "operator=true");
    assert_eq!(publish(&harness, "alice", message).await.unwrap(), release);
    assert_eq!(
        get(&harness, "alice", &release.digest).await,
        Some(release.clone())
    );
    assert!(get(&harness, "bob", &release.digest).await.is_none());
    let desired = deployment(
        "published",
        "acme",
        "echo",
        &capsule.descriptor.release_digest,
    );
    let receipt = harness
        .deployments_client()
        .apply_deployment(request(
            "alice",
            proto::ApplyDeploymentRequest {
                deployment: Some(desired),
                expected_generation: Some(0),
            },
        ))
        .await
        .unwrap()
        .into_inner()
        .deployment
        .unwrap();
    assert_eq!(receipt.release_digest, release.digest);
    assert!(receipt.generation > 0);
    harness.shutdown().await;
}
