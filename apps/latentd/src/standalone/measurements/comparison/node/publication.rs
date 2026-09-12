use latent_artifacts::{encode_contract_metadata, ContractMetadataLimits};
use latent_control_store::VersionedDeployment;
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use latent_wire::management::{deployment_to_proto, proto};
use serde_json::{json, Value};

use super::{authenticated, platform, Node, Result};

impl Node {
    pub async fn publish(&mut self) -> Result<Value> {
        let fixture = &self.fixture;
        let upload = proto::CapsuleArtifactUpload {
            capsule_manifest_json: JsonManifestCodec::default()
                .encode_capsule(&fixture.artifact.manifest)
                .map_err(|_| "comparison capsule encoding")?,
            contract_metadata_json: encode_contract_metadata(
                &fixture.artifact.contracts,
                ContractMetadataLimits::default(),
            )
            .map_err(platform)?,
            component_digest: fixture.release_digest.clone(),
            component_bytes: fixture.artifact.component_bytes.clone(),
            component_media_type: fixture.artifact.descriptor.media_type.clone(),
        };
        let deployment = deployment_to_proto(&VersionedDeployment {
            manifest: fixture.deployment.clone(),
            generation: 0,
        })
        .map_err(|_| "comparison deployment encoding")?;
        self.command(false)?;
        let published =
            proto::release_service_client::ReleaseServiceClient::new(self.channel.clone())
                .publish_release(authenticated(proto::PublishReleaseRequest {
                    package: None,
                    operation: None,
                    release: None,
                    artifact: Some(upload),
                })?)
                .await?
                .into_inner();
        let release = published
            .release
            .ok_or("comparison publication receipt missing")?;
        if release.digest != self.fixture.release_digest {
            return Err("comparison publication identity mismatch".into());
        }
        self.command(false)?;
        let applied =
            proto::deployment_service_client::DeploymentServiceClient::new(self.channel.clone())
                .apply_deployment(authenticated(proto::ApplyDeploymentRequest {
                    deployment: Some(deployment),
                    expected_generation: None,
                })?)
                .await?
                .into_inner();
        let deployment = applied
            .deployment
            .ok_or("comparison deployment receipt missing")?;
        if deployment.id != self.fixture.deployment.id.0 || deployment.generation == 0 {
            return Err("comparison deployment identity mismatch".into());
        }
        let catalog_generation = self.owner.inventory().map_err(platform)?.route_generation.0;
        Ok(
            json!({"release_digest":release.digest,"deployment_id":deployment.id,
            "object_generation":deployment.generation.to_string(),"catalog_generation":catalog_generation.to_string()}),
        )
    }
}
