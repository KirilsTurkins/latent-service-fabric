use crate::management::phase2::{
    audit_metadata, invalid_input, invalid_response,
    projection::{self, Project},
    proto,
};
use crate::management::{association, bounds, response};
use crate::{client::Session, error::Failure, operation::Operation, output::Outcome};
use latent_manifest::ManifestCodec;
use proto::deployment_service_client::DeploymentServiceClient;
use serde_json::json;

#[cfg(test)]
mod tests;

pub(super) async fn execute(operation: Operation, session: &Session) -> Result<Outcome, Failure> {
    match operation {
        Operation::LookupDeploymentReceipt(request) => lookup(request, session).await,
        Operation::GetDeployment(request) => get(request, session).await,
        Operation::ApplyDeployment(request) => apply(request, session).await,
        Operation::DeleteDeployment(request) => delete(request, session).await,
        _ => Err(invalid_input()),
    }
}
fn client(session: &Session) -> DeploymentServiceClient<tonic::transport::Channel> {
    DeploymentServiceClient::new(session.channel())
        .max_decoding_message_size(session.max_response_bytes())
        .max_encoding_message_size(session.max_request_bytes())
}
fn header<'a>(metadata: &'a tonic::metadata::MetadataMap, key: &str) -> Result<&'a str, Failure> {
    let value = metadata
        .get(key)
        .ok_or_else(invalid_response)?
        .to_str()
        .map_err(|_| invalid_response())?;
    if value.len() > 128 {
        return Err(invalid_response());
    }
    Ok(value)
}
fn durability(value: i32) -> Result<&'static str, Failure> {
    match proto::DeploymentDurability::try_from(value) {
        Ok(proto::DeploymentDurability::Confirmed) => Ok("confirmed"),
        Ok(proto::DeploymentDurability::Uncertain) => Ok("uncertain"),
        _ => Err(invalid_response()),
    }
}
fn receipt_scope(
    value: &proto::DeploymentOperationReceipt,
    session: &Session,
    id: &str,
    deployment: Option<&str>,
) -> Result<(), Failure> {
    projection::checked(value, session.max_response_bytes())?;
    if value.format_version != 1
        || value.state_version <= value.expected_state_version
        || value.actor.is_none()
        || value.tenant != session.tenant()
        || value.operation_id != id
        || deployment.is_some_and(|id| value.deployment_id != id)
        || [
            &value.request_digest,
            &value.receipt_digest,
            &value.manifest_digest,
            &value.component_digest,
        ]
        .iter()
        .any(|v| !crate::management::canonical_digest(v))
    {
        return Err(invalid_response());
    }
    Ok(())
}

async fn lookup(
    request: proto::GetDeploymentOperationRequest,
    session: &Session,
) -> Result<Outcome, Failure> {
    let id = request.operation_id.clone();
    let value = call!(
        session,
        DeploymentServiceClient,
        get_deployment_operation,
        request
    );
    let found = value.disposition == proto::DeploymentOperationLookupDisposition::Found as i32;
    if found != value.receipt.is_some() {
        return Err(invalid_response());
    }
    if let Some(receipt) = &value.receipt {
        receipt_scope(receipt, session, &id, None)?;
    }
    if found && value.durability != Some(proto::DeploymentDurability::Confirmed as i32) {
        return Err(invalid_response());
    }
    let mut output = Outcome::success(value.project());
    output.outcome_known = found;
    Ok(output)
}

async fn get(request: proto::GetDeploymentRequest, session: &Session) -> Result<Outcome, Failure> {
    let id = request.id.clone();
    let snapshot = request.include_operation_snapshot;
    let mut client = client(session);
    let value = session
        .call(client.get_deployment(session.request(request)?))
        .await?
        .into_inner();
    bounds::checked(&value, session.max_response_bytes())?;
    association::deployment(value.deployment.as_ref(), session.tenant(), Some(&id), None)?;
    if snapshot
        && (value.state_version.is_none()
            || value.route_generation.is_none()
            || value.durability.is_none())
    {
        return Err(invalid_response());
    }
    let durability = value.durability.map(durability).transpose()?;
    let found = value.deployment.is_some();
    let data = json!({"deployment":value.deployment.map(response::deployment).transpose()?,"stateVersion":value.state_version.map(|v|v.to_string()),"routeGeneration":value.route_generation.map(|v|v.to_string()),"durability":durability});
    let mut output = if found {
        Outcome::success(data)
    } else {
        Outcome::not_found(data)
    };
    output.outcome_known = durability != Some("uncertain");
    Ok(output)
}

async fn apply(
    request: proto::ApplyDeploymentRequest,
    session: &Session,
) -> Result<Outcome, Failure> {
    let deployment = request.deployment.as_ref().ok_or_else(invalid_input)?;
    let id = deployment.id.clone();
    let component = deployment.release_digest.clone();
    let expected = request.expected_generation;
    let op = request.operation.clone();
    let expected_manifest = op
        .as_ref()
        .map(|_| manifest_digest(deployment))
        .transpose()?;
    let mut client = client(session);
    let value = session
        .call(client.apply_deployment(session.request(request)?))
        .await?
        .into_inner();
    bounds::checked(&value, session.max_response_bytes())?;
    association::deployment(value.deployment.as_ref(), session.tenant(), Some(&id), None)?;
    if value
        .deployment
        .as_ref()
        .is_some_and(|value| value.release_digest != component)
    {
        return Err(invalid_response());
    }
    if let Some(receipt) = &value.receipt {
        receipt_scope(receipt, session, &receipt.operation_id, Some(&id))?;
    }
    if let Some(op) = op {
        let receipt = value.receipt.as_ref().ok_or_else(invalid_response)?;
        check_manifest(
            value.deployment.as_ref().ok_or_else(invalid_response)?,
            receipt,
            expected_manifest.as_deref().ok_or_else(invalid_response)?,
        )?;
        receipt_scope(receipt, session, &op.operation_id, Some(&id))?;
        if receipt.action != proto::DeploymentOperationAction::Apply as i32
            || Some(receipt.expected_state_version) != op.expected_state_version
            || Some(receipt.expected_generation) != expected
            || receipt.component_digest != component
            || value
                .deployment
                .as_ref()
                .is_none_or(|value| value.generation != receipt.object_generation)
        {
            return Err(invalid_response());
        }
    }
    if let Some(ack) = &value.audit_ack {
        projection::checked(ack, session.max_response_bytes())?;
    }
    let state = if value.receipt.is_some() {
        Some(durability(value.durability)?)
    } else {
        None
    };
    let mut output = Outcome::success(
        json!({"deployment":response::deployment(value.deployment.ok_or_else(invalid_response)?)?,"warnings":value.warnings,"receipt":value.receipt.map(Project::project),"replayed":value.replayed,"durability":state,"auditAck":value.audit_ack.map(Project::project)}),
    );
    output.outcome_known = state != Some("uncertain");
    Ok(output)
}

fn manifest_digest(value: &proto::Deployment) -> Result<String, Failure> {
    bounds::checked_deployment_manifest(
        value,
        latent_control_store::deployment_operations::MAX_REQUEST_BYTES,
    )?;
    let mut domain = latent_wire::management::deployment_from_proto(value.clone())
        .map_err(|_| invalid_response())?;
    domain.manifest.normalize_storage_fields();
    let bytes = latent_manifest::JsonManifestCodec::default()
        .encode_deployment(&domain.manifest)
        .map_err(|_| invalid_response())?;
    Ok(latent_artifacts::package::artifact_blob_digest(&bytes).to_string())
}

fn check_manifest(
    value: &proto::Deployment,
    receipt: &proto::DeploymentOperationReceipt,
    expected: &str,
) -> Result<(), Failure> {
    if receipt.manifest_digest != expected || manifest_digest(value)? != expected {
        return Err(invalid_response());
    }
    Ok(())
}

async fn delete(
    request: proto::DeleteDeploymentRequest,
    session: &Session,
) -> Result<Outcome, Failure> {
    let op = request.operation.clone();
    let mut client = client(session);
    let value = session
        .call(client.delete_deployment(session.request(request)?))
        .await?;
    let ack = audit_metadata(value.metadata())?;
    let mut data = json!({"auditAck":ack});
    if let Some(op) = op {
        let metadata = value.metadata();
        let id = metadata
            .get_bin("latent-deployment-operation-bin")
            .ok_or_else(invalid_response)?
            .to_bytes()
            .map_err(|_| invalid_response())?;
        if id.as_ref() != op.operation_id.as_bytes() {
            return Err(invalid_response());
        }
        let request = header(metadata, "latent-deployment-request")?;
        let receipt = header(metadata, "latent-deployment-receipt")?;
        if !crate::management::canonical_digest(request)
            || !crate::management::canonical_digest(receipt)
        {
            return Err(invalid_response());
        }
        let replayed = match header(metadata, "latent-deployment-replayed")? {
            "true" => true,
            "false" => false,
            _ => return Err(invalid_response()),
        };
        let durability = header(metadata, "latent-deployment-durability")?;
        if !matches!(durability, "confirmed" | "uncertain") {
            return Err(invalid_response());
        }
        data["operation"] = json!({"operationId":op.operation_id,"requestDigest":request,"receiptDigest":receipt,"replayed":replayed,"durability":durability});
    }
    let mut output = Outcome::success(data);
    output.outcome_known = output.data["operation"]["durability"] != "uncertain";
    Ok(output)
}
