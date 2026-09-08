use std::fs;
use std::io::Read;
use std::path::PathBuf;

use latent_artifacts::{
    content_digest, decode_contract_metadata, encode_contract_metadata, ContractMetadataLimits,
};
use latent_control_store::VersionedDeployment;
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use latent_wasmtime::WIT_VALUES_MEDIA_TYPE;
use latent_wire::invocation::{proto as invocation, InvocationServiceClient};
use latent_wire::management::{deployment_to_proto, proto};
use proto::deployment_service_client::DeploymentServiceClient;
use proto::release_service_client::ReleaseServiceClient;
use proto::route_service_client::RouteServiceClient;
use tonic::transport::Channel;

use super::support::{self, request, CALLER, FOREIGN, OPERATOR};

pub fn scenario() {
    let upload = upload();
    let digest = upload.artifact.as_ref().unwrap().component_digest.clone();
    let directory = tempfile::tempdir().expect("durable echo catalog root");
    let config = support::write_config(directory.path());
    let runtimes = support::Runtimes::new();
    runtimes.invocation.block_on(async {
        let node = runtimes.start(support::settings(&config)).await;
        let channel = support::channel(&node).await;
        let (release, applied) = publish(channel.clone(), upload).await;
        let snapshot = routes(channel.clone()).await;
        assert_route(&snapshot, &digest);
        invoke(
            channel.clone(),
            "before-restart",
            "first",
            &digest,
            snapshot.generation,
        )
        .await;
        let inventory = node.inventory().expect("post-invocation inventory");
        assert_eq!(inventory.cache_summary.entries, 1);
        assert_eq!(inventory.cell_capacity[0].available, 1);
        assert_eq!(inventory.cell_capacity[0].active, 0);
        drop(channel);
        support::stop(node).await;

        let node = runtimes.start(support::settings(&config)).await;
        assert_eq!(
            node.inventory().unwrap().cache_summary.entries,
            0,
            "compiled cache is process-local"
        );
        let channel = support::channel(&node).await;
        let recovered = ReleaseServiceClient::new(channel.clone())
            .get_release(request(
                OPERATOR,
                proto::GetReleaseRequest {
                    digest: digest.clone(),
                },
            ))
            .await
            .expect("durable release recovery")
            .into_inner()
            .release
            .expect("release survives restart");
        assert_eq!(recovered, release);
        let recovered = DeploymentServiceClient::new(channel.clone())
            .get_deployment(request(
                OPERATOR,
                proto::GetDeploymentRequest {
                    id: applied.id.clone(),
                },
            ))
            .await
            .expect("durable deployment recovery")
            .into_inner()
            .deployment
            .expect("deployment survives restart");
        assert_eq!(recovered, applied);
        let restored = routes(channel.clone()).await;
        assert_eq!(
            restored, snapshot,
            "exact committed route publication survives restart"
        );
        invoke(
            channel.clone(),
            "after-restart",
            "second",
            &digest,
            snapshot.generation,
        )
        .await;
        drop(channel);
        support::stop(node).await;
    });
    runtimes.finish();
}

async fn publish(
    channel: Channel,
    upload: proto::PublishReleaseRequest,
) -> (proto::ReleaseDescriptor, proto::Deployment) {
    let digest = upload.artifact.as_ref().unwrap().component_digest.clone();
    let mut releases = ReleaseServiceClient::new(channel.clone());
    let release = releases
        .publish_release(request(OPERATOR, upload))
        .await
        .expect("publish actual generated component through authenticated RPC")
        .into_inner()
        .release
        .expect("published receipt");
    assert_eq!(release.digest, digest);
    assert_eq!(release.tenant.as_deref(), Some("examples"));
    assert_eq!(release.service, "examples/echo");
    assert!(release.admitted);
    assert!(releases
        .get_release(request(
            FOREIGN,
            proto::GetReleaseRequest {
                digest: digest.clone(),
            }
        ))
        .await
        .expect("foreign lookup is hidden")
        .into_inner()
        .release
        .is_none());
    let applied = DeploymentServiceClient::new(channel)
        .apply_deployment(request(
            OPERATOR,
            proto::ApplyDeploymentRequest {
                deployment: Some(deployment(&digest)),
                expected_generation: Some(0),
            },
        ))
        .await
        .expect("deploy published component without editing storage")
        .into_inner()
        .deployment
        .unwrap();
    assert!(applied.generation > 0);
    (release, applied)
}

fn upload() -> proto::PublishReleaseRequest {
    let path =
        PathBuf::from(std::env::var_os("LSF_ECHO_COMPONENT").expect(
            "contracts gate must supply LSF_ECHO_COMPONENT; this test never builds fixtures",
        ));
    let mut bytes = Vec::new();
    fs::File::open(path)
        .expect("generated echo component")
        .take(16 * 1024 * 1024 + 1)
        .read_to_end(&mut bytes)
        .expect("bounded component fixture read");
    assert!(!bytes.is_empty() && bytes.len() <= 16 * 1024 * 1024);
    let digest = content_digest(&bytes);
    let codec = JsonManifestCodec::default();
    let mut manifest = codec
        .decode_capsule(include_bytes!(
            "../../../../examples/echo-contract/capsule.json"
        ))
        .expect("maintained echo manifest");
    manifest.component_digest = digest.clone();
    assert_eq!(manifest.metadata.tenant.as_ref().unwrap().0, "examples");
    let example: serde_json::Value = serde_json::from_slice(include_bytes!(
        "../../../../examples/echo-contract/publish-release.json"
    ))
    .expect("maintained typed publication example");
    let mut metadata: serde_json::Value = serde_json::from_str(
        example["artifact"]["contractMetadataJson"]
            .as_str()
            .unwrap(),
    )
    .expect("versioned contract metadata example");
    for contract in metadata["contracts"].as_array_mut().unwrap() {
        for interface in contract["interfaces"].as_array_mut().unwrap() {
            assign_descriptor_digest(interface);
        }
        assign_descriptor_digest(contract);
    }
    let contracts = decode_contract_metadata(
        &serde_json::to_vec(&metadata).unwrap(),
        ContractMetadataLimits::default(),
    )
    .expect("semantically valid typed descriptors");
    proto::PublishReleaseRequest {
        release: None,
        artifact: Some(proto::CapsuleArtifactUpload {
            capsule_manifest_json: codec.encode_capsule(&manifest).unwrap(),
            component_bytes: bytes,
            component_digest: digest.0,
            component_media_type: "application/vnd.wasm.component.v1+wasm".to_owned(),
            contract_metadata_json: encode_contract_metadata(
                &contracts,
                ContractMetadataLimits::default(),
            )
            .unwrap(),
        }),
    }
}

fn assign_descriptor_digest(descriptor: &mut serde_json::Value) {
    let mut identity = descriptor.clone();
    identity.as_object_mut().unwrap().remove("digest");
    descriptor["digest"] = content_digest(&serde_json::to_vec(&identity).unwrap())
        .0
        .into();
}

fn deployment(digest: &str) -> proto::Deployment {
    let mut manifest = JsonManifestCodec::default()
        .decode_deployment(include_bytes!(
            "../../../../examples/echo-contract/deployment.json"
        ))
        .expect("maintained echo deployment");
    manifest.release = latent_core::ReleaseDigest(digest.to_owned());
    deployment_to_proto(&VersionedDeployment {
        manifest,
        generation: 0,
    })
    .expect("honest deployment wire conversion")
}

async fn routes(channel: Channel) -> proto::RouteSnapshot {
    RouteServiceClient::new(channel)
        .get_route_snapshot(request(
            OPERATOR,
            proto::GetRouteSnapshotRequest { generation: None },
        ))
        .await
        .expect("authenticated route snapshot")
        .into_inner()
        .snapshot
        .expect("current scoped snapshot")
}

fn assert_route(snapshot: &proto::RouteSnapshot, digest: &str) {
    assert_eq!(snapshot.tenant.as_deref(), Some("examples"));
    assert!(!snapshot.services.is_empty());
    for service in &snapshot.services {
        assert_eq!(service.tenant, "examples");
        assert_eq!(service.service, "examples/echo");
        assert!(!service.revisions.is_empty());
        assert!(service
            .revisions
            .iter()
            .all(|revision| revision.release_digest == digest));
    }
}

async fn invoke(channel: Channel, id: &str, message: &str, digest: &str, generation: u64) {
    let mut client = InvocationServiceClient::new(channel);
    let result = client
        .invoke(request(
            CALLER,
            invocation::InvokeRequest {
                activation_id: Some(id.to_owned()),
                target: Some(invocation::InvocationTarget {
                    tenant: "examples".to_owned(),
                    service: "examples/echo".to_owned(),
                    contract: "examples:echo/api@0.1.0".to_owned(),
                    function: "echo".to_owned(),
                    route: None,
                }),
                payload: serde_json::to_vec(&[message]).unwrap(),
                media_type: WIT_VALUES_MEDIA_TYPE.to_owned(),
                budget: Some(invocation::ResourceBudget {
                    cpu_fuel: 1_000_000,
                    memory_bytes: 4 * 1024 * 1024,
                    wall_time_limit_millis: Some(4000),
                    log_bytes: 16384,
                    ..invocation::ResourceBudget::default()
                }),
                ..invocation::InvokeRequest::default()
            },
        ))
        .await
        .expect("bounded actual guest invocation")
        .into_inner();
    assert_eq!(result.activation_id, id);
    assert_eq!(result.release_digest, digest);
    assert_eq!(result.route_generation, generation);
    assert!(!result.revision_id.is_empty());
    let Some(invocation::invoke_response::Result::Success(success)) = result.result else {
        panic!("expected actual echo success, got {:?}", result.result);
    };
    assert_eq!(success.media_type, WIT_VALUES_MEDIA_TYPE);
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&success.payload).unwrap(),
        serde_json::json!([{"ok": message}])
    );
    let consumption = result.consumption.expect("consumption-bearing receipt");
    assert!(consumption.cpu_fuel > 0 && consumption.cpu_fuel <= 1_000_000);
    assert!(consumption.peak_memory_bytes > 0 && consumption.peak_memory_bytes <= 4 * 1024 * 1024);
    let status = client
        .get_activation(request(
            CALLER,
            invocation::GetActivationRequest {
                activation_id: id.to_owned(),
            },
        ))
        .await
        .expect("scoped terminal status")
        .into_inner();
    assert_eq!(status.terminal_state.as_deref(), Some("completed"));
    assert_eq!(status.final_consumption, Some(consumption));
    assert!(status.terminal_at_unix_millis.is_some());
}
