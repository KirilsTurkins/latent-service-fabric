use latent_manifest::{ManifestCodec, ManifestValidator, Phase1ManifestValidator};
use latent_wire::management::{deployment_from_proto, proto, release_descriptor_from_proto};
use serde_json::{json, Value};

use crate::error::Failure;
use crate::output::Outcome;

use super::{invalid_response, node, prepare};

pub(super) fn release(value: proto::ReleaseDescriptor) -> Result<Value, Failure> {
    let entry = release_descriptor_from_proto(value).map_err(|_| invalid_response())?;
    Ok(json!({
        "digest": entry.descriptor.release_digest.0,
        "artifactReference": entry.descriptor.reference.0,
        "service": entry.service.0,
        "semanticVersion": entry.semantic_version,
        "world": entry.world.0,
        "publisher": entry.descriptor.publisher.map(|id| id.0),
        "mediaType": entry.descriptor.media_type,
        "sizeBytes": entry.descriptor.size_bytes.to_string(),
        "createdAtUnixMillis": "0",
        "admitted": true,
        "annotations": entry.descriptor.annotations,
        "tenant": entry.tenant.map(|tenant| tenant.0),
    }))
}

pub(super) fn deployment(value: proto::Deployment) -> Result<Value, Failure> {
    let versioned = deployment_from_proto(value).map_err(|_| invalid_response())?;
    Phase1ManifestValidator
        .validate_deployment(&versioned.manifest)
        .map_err(|_| invalid_response())?;
    let encoded = prepare::codec()
        .encode_deployment(&versioned.manifest)
        .map_err(|_| invalid_response())?;
    let manifest: Value = serde_json::from_slice(&encoded).map_err(|_| invalid_response())?;
    Ok(json!({"generation": versioned.generation.to_string(), "manifest": manifest}))
}

pub(super) fn published(value: proto::PublishReleaseResponse) -> Result<Outcome, Failure> {
    Ok(Outcome::success(
        json!({"release": release(value.release.ok_or_else(invalid_response)?)?, "admissionWarnings": value.admission_warnings}),
    ))
}

pub(super) fn got_release(value: proto::GetReleaseResponse) -> Result<Outcome, Failure> {
    match value.release {
        Some(value) => Ok(Outcome::success(json!({"release": release(value)?}))),
        None => Ok(Outcome::not_found(json!({"release": null}))),
    }
}

pub(super) fn releases(value: proto::ListReleasesResponse) -> Result<Outcome, Failure> {
    let rows = value
        .releases
        .into_iter()
        .map(release)
        .collect::<Result<Vec<_>, _>>()?;
    Ok(Outcome::success(
        json!({"releases": rows, "nextPageToken": token(value.page)?}),
    ))
}

pub(super) fn applied(value: proto::ApplyDeploymentResponse) -> Result<Outcome, Failure> {
    Ok(Outcome::success(
        json!({"deployment": deployment(value.deployment.ok_or_else(invalid_response)?)?, "warnings": value.warnings}),
    ))
}

pub(super) fn got_deployment(value: proto::GetDeploymentResponse) -> Result<Outcome, Failure> {
    match value.deployment {
        Some(value) => Ok(Outcome::success(json!({"deployment": deployment(value)?}))),
        None => Ok(Outcome::not_found(json!({"deployment": null}))),
    }
}

pub(super) fn deployments(value: proto::ListDeploymentsResponse) -> Result<Outcome, Failure> {
    let rows = value
        .deployments
        .into_iter()
        .map(deployment)
        .collect::<Result<Vec<_>, _>>()?;
    Ok(Outcome::success(
        json!({"deployments": rows, "nextPageToken": token(value.page)?}),
    ))
}

pub(super) fn route(value: proto::GetRouteSnapshotResponse) -> Outcome {
    let Some(snapshot) = value.snapshot else {
        return Outcome::not_found(json!({"snapshot":null}));
    };
    let services = snapshot.services.into_iter().map(|service| {
        let revisions = service.revisions.into_iter().map(|revision| json!({
            "revisionId":revision.revision_id,"releaseDigest":revision.release_digest,"weight":revision.weight,"attributes":revision.attributes,
        })).collect::<Vec<_>>();
        json!({"routeId":service.route_id,"service":service.service,"tenant":service.tenant,"revisions":revisions})
    }).collect::<Vec<_>>();
    let bindings = snapshot.bindings.into_iter().map(|binding| json!({
        "bindingId":binding.binding_id,"consumerService":binding.consumer_service,"importedContract":binding.imported_contract,
        "providerService":binding.provider_service,"providerContract":binding.provider_contract,"mode":binding.mode,
        "policyDigest":binding.policy_digest,"consumerTenant":binding.consumer_tenant,"providerTenant":binding.provider_tenant,
    })).collect::<Vec<_>>();
    Outcome::success(json!({"snapshot": {
        "generation":snapshot.generation.to_string(),"generatedAtUnixMillis":snapshot.generated_at_unix_millis.to_string(),
        "services":services,"bindings":bindings,"policyDigests":snapshot.policy_digests,"snapshotDigest":snapshot.snapshot_digest,"tenant":snapshot.tenant,
    }}))
}

pub(super) fn got_node(value: proto::GetNodeResponse) -> Result<Outcome, Failure> {
    match value.inventory {
        Some(value) => Ok(Outcome::success(
            json!({"inventory": node::inventory(value)?}),
        )),
        None => Ok(Outcome::not_found(json!({"inventory": null}))),
    }
}

pub(super) fn nodes(value: proto::ListNodesResponse) -> Result<Outcome, Failure> {
    let rows = value
        .nodes
        .into_iter()
        .map(node::inventory)
        .collect::<Result<Vec<_>, _>>()?;
    Ok(Outcome::success(
        json!({"nodes":rows,"nextPageToken":token(value.page)?}),
    ))
}

fn token(page: Option<proto::PageResponse>) -> Result<Option<String>, Failure> {
    Ok(page.ok_or_else(invalid_response)?.next_page_token)
}
