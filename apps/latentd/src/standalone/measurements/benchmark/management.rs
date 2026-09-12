mod persisted;

use std::time::Instant;

use latent_artifacts::{encode_contract_metadata, ContractMetadataLimits};
use latent_control_store::DeploymentStore;
use latent_core::TenantId;
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use latent_routing::RouteResolver;
use latent_wire::management::{deployment_from_proto, deployment_to_proto, proto};
use serde_json::json;

use super::super::node::authenticated;
use super::{platform, MeasurementNode, MeasurementWriter, Result};

pub(super) async fn sample(
    node: &MeasurementNode,
    writer: &mut MeasurementWriter,
    index: u32,
) -> Result<()> {
    let fixture = &node.fixtures.echo;
    let tenant = TenantId(fixture.tenant.clone());
    let previous = node
        .deployments
        .get_versioned(&tenant, &fixture.deployment.id)
        .await
        .map_err(platform)?
        .ok_or("missing benchmark deployment")?;
    let upload = proto::CapsuleArtifactUpload {
        capsule_manifest_json: JsonManifestCodec::default()
            .encode_capsule(&fixture.artifact.manifest)
            .map_err(|_| "benchmark manifest encoding")?,
        component_bytes: fixture.artifact.component_bytes.clone(),
        component_digest: fixture.release_digest.clone(),
        component_media_type: fixture.artifact.descriptor.media_type.clone(),
        contract_metadata_json: encode_contract_metadata(
            &fixture.artifact.contracts,
            ContractMetadataLimits::default(),
        )
        .map_err(platform)?,
    };
    let mut releases = proto::release_service_client::ReleaseServiceClient::new(node.channel());
    let request = authenticated(
        &fixture.tenant,
        proto::PublishReleaseRequest {
            package: None,
            operation: None,
            release: None,
            artifact: Some(upload),
        },
    )?;
    node.before_command(false)?;
    let started = Instant::now();
    let published = releases.publish_release(request).await?.into_inner();
    let publish_elapsed = started.elapsed().as_nanos();
    let release = published.release.ok_or("missing republish receipt")?;
    if release.digest != fixture.release_digest
        || release.tenant.as_deref() != Some(fixture.tenant.as_str())
        || release.service != fixture.service
        || release.size_bytes != fixture.artifact.descriptor.size_bytes
        || !release.admitted
        || !published.admission_warnings.is_empty()
    {
        return Err("idempotent republish receipt mismatch".into());
    }
    let expected_catalog = node
        .deployments
        .generation()
        .0
        .checked_add(1)
        .ok_or("benchmark generation overflow")?;
    let deployment = deployment_to_proto(&previous).map_err(|_| "benchmark deployment encoding")?;
    let mut deployments =
        proto::deployment_service_client::DeploymentServiceClient::new(node.channel());
    let request = authenticated(
        &fixture.tenant,
        proto::ApplyDeploymentRequest {
            operation: None,
            deployment: Some(deployment),
            expected_generation: Some(previous.generation),
        },
    )?;
    node.before_command(false)?;
    let started = Instant::now();
    let applied = deployments.apply_deployment(request).await?.into_inner();
    let apply_elapsed = started.elapsed().as_nanos();
    let receipt = deployment_from_proto(applied.deployment.ok_or("missing reapply receipt")?)
        .map_err(|_| "invalid reapply receipt")?;
    let committed = node
        .deployments
        .get_versioned(&tenant, &fixture.deployment.id)
        .await
        .map_err(platform)?
        .ok_or("missing committed reapply")?;
    if receipt != committed
        || receipt.manifest != previous.manifest
        || receipt.generation != expected_catalog
        || receipt.generation <= previous.generation
        || node.deployments.generation().0 != expected_catalog
        || !applied.warnings.is_empty()
    {
        return Err("durable reapply receipt mismatch".into());
    }
    let persisted = persisted::verify(
        &node.catalog_state_path,
        &fixture.deployment.id.0,
        &fixture.release_digest,
        expected_catalog,
    )?;
    writer.write("benchmark-management",&json!({"sample":index.to_string(),"publish_mode":"idempotent-existing-release",
        "apply_mode":"same-manifest-new-generation","publish_elapsed_nanos":publish_elapsed.to_string(),"apply_elapsed_nanos":apply_elapsed.to_string(),
        "release_digest":fixture.release_digest,"deployment_id":fixture.deployment.id.0,"previous_object_generation":previous.generation.to_string(),
        "object_generation":receipt.generation.to_string(),"catalog_generation":expected_catalog.to_string(),"persisted_generation_matches":true,
        "persisted_record_sha256":persisted}))?;
    Ok(())
}
