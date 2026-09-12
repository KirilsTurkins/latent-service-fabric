use super::super::super::{fixture_inputs::retain, fixtures::Fixture, platform};
use super::{call::auth, Clock, Node, Result};
use latent_artifacts::{encode_contract_metadata, ContractMetadataLimits};
use latent_control_store::VersionedDeployment;
use latent_executor::ExecutionBackend;
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use latent_wire::management::{deployment_to_proto, proto};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::path::Path;

#[derive(Clone, Serialize, Deserialize)]
pub(super) struct Target {
    pub tenant: String,
    pub service: String,
    pub contract: String,
    pub release_digest: String,
}
pub(super) struct Publication {
    pub targets: Vec<Target>,
    pub fixtures: Vec<Value>,
    pub commands: Vec<Value>,
}

pub(super) async fn publish(
    node: &mut Node,
    fixtures: Vec<Fixture>,
    directory: &Path,
    clock: Clock,
) -> Result<Publication> {
    let mut result = Publication {
        targets: Vec::with_capacity(8),
        fixtures: Vec::with_capacity(8),
        commands: Vec::with_capacity(16),
    };
    for (index, fixture) in fixtures.into_iter().enumerate() {
        node.fixture = fixture;
        let (receipt, commands) = one(node, clock).await?;
        result.commands.extend(commands);
        let published = node.published().await?;
        let relative = format!("fixtures/target-{index}");
        let target = directory.join(&relative);
        std::fs::create_dir_all(&target)?;
        let artifact = super::super::evidence::artifact(&target, &node.fixture, &published)?;
        let component = retain(&target, "component.wasm", &published.component_bytes)?;
        let key = node
            .owner
            .backend
            .preparation_key(&published.descriptor.release_digest)
            .map_err(platform)?;
        let value = Target {
            tenant: node.fixture.tenant.clone(),
            service: node.fixture.service.clone(),
            contract: node.fixture.contract.clone(),
            release_digest: node.fixture.release_digest.clone(),
        };
        result.fixtures.push(json!({"index":index.to_string(),"directory":relative,"target":value,"artifact":artifact,"component":component,"publication":receipt,
            "preparation_key":{"release":key.release.0,"engine_version":key.engine_version,"engine_configuration_digest":key.engine_configuration_digest,"target_triple":key.target_triple,"cpu_feature_set":key.cpu_feature_set}}));
        result.targets.push(value);
    }
    if node.work.commands != 16 || node.owner.inventory().map_err(platform)?.route_generation.0 != 8
    {
        return Err("engine publication population".into());
    }
    Ok(result)
}
async fn one(node: &mut Node, clock: Clock) -> Result<(Value, [Value; 2])> {
    let fixture = &node.fixture;
    let tenant = fixture.tenant.clone();
    let digest = fixture.release_digest.clone();
    let deployment_id = fixture.deployment.id.0.clone();
    let upload = proto::CapsuleArtifactUpload {
        capsule_manifest_json: JsonManifestCodec::default()
            .encode_capsule(&fixture.artifact.manifest)
            .map_err(|_| "engine capsule encode")?,
        contract_metadata_json: encode_contract_metadata(
            &fixture.artifact.contracts,
            ContractMetadataLimits::default(),
        )
        .map_err(platform)?,
        component_digest: digest.clone(),
        component_bytes: fixture.artifact.component_bytes.clone(),
        component_media_type: fixture.artifact.descriptor.media_type.clone(),
    };
    let deployment = deployment_to_proto(&VersionedDeployment {
        manifest: fixture.deployment.clone(),
        generation: 0,
    })
    .map_err(|_| "engine deployment encode")?;
    node.command(false)?;
    let started = clock.elapsed();
    let ordinal = node.work.commands;
    let published = proto::release_service_client::ReleaseServiceClient::new(node.channel())
        .publish_release(auth(
            proto::PublishReleaseRequest {
                package: None,
                operation: None,
                release: None,
                artifact: Some(upload),
            },
            &tenant,
            std::time::Duration::from_secs(5),
        )?)
        .await?
        .into_inner()
        .release
        .ok_or("engine publication receipt")?;
    let row = json!({"kind":"command","ordinal":ordinal.to_string(),"operation":"publish-release","target":digest,"tenant":tenant,"started_nanos":started.to_string(),"finished_nanos":clock.elapsed().to_string(),"response":{"grpc_code":0,"release_digest":published.digest}});
    if published.digest != digest {
        return Err("engine publication release mismatch".into());
    }
    node.command(false)?;
    let started = clock.elapsed();
    let ordinal = node.work.commands;
    let applied = proto::deployment_service_client::DeploymentServiceClient::new(node.channel())
        .apply_deployment(auth(
            proto::ApplyDeploymentRequest {
                operation: None,
                deployment: Some(deployment),
                expected_generation: None,
            },
            &tenant,
            std::time::Duration::from_secs(5),
        )?)
        .await?
        .into_inner()
        .deployment
        .ok_or("engine deployment receipt")?;
    let generation = node.owner.inventory().map_err(platform)?.route_generation.0;
    let receipt = json!({"release_digest":digest,"deployment_id":applied.id,"object_generation":applied.generation.to_string(),"catalog_generation":generation.to_string()});
    let second = json!({"kind":"command","ordinal":ordinal.to_string(),"operation":"apply-deployment","target":deployment_id,"tenant":tenant,"started_nanos":started.to_string(),"finished_nanos":clock.elapsed().to_string(),"response":{"grpc_code":0,"receipt":receipt}});
    if applied.id != deployment_id || applied.generation == 0 {
        return Err("engine deployment identity mismatch".into());
    }
    Ok((receipt, [row, second]))
}
