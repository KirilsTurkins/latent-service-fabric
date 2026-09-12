use crate::management::phase2::{
    invalid_input, invalid_response,
    projection::{self, Project},
    proto,
};
use crate::management::{association, bounds, response};
use crate::{
    client::Session,
    error::Failure,
    operation::Operation,
    output::{Category, Outcome},
};
use proto::release_service_client::ReleaseServiceClient;
use serde_json::json;

#[cfg(test)]
mod tests;

pub(super) async fn execute(operation: Operation, session: &Session) -> Result<Outcome, Failure> {
    match operation {
        Operation::PublishRelease(request) => publish(request, session).await,
        Operation::GetReleaseLifecycle(request) => lifecycle(request, session).await,
        Operation::LookupReleaseReceipt(request) => get_receipt(request, session).await,
        Operation::ChangeReleaseLifecycle(request) => change(request, session).await,
        Operation::RenewReleaseEvidence(request) => renew(request, session).await,
        _ => Err(invalid_input()),
    }
}

async fn publish(
    request: proto::PublishReleaseRequest,
    session: &Session,
) -> Result<Outcome, Failure> {
    let op = request.operation.clone();
    let digest = request
        .artifact
        .as_ref()
        .map(|artifact| latent_artifacts::content_digest(&artifact.component_bytes).0);
    let package = request.package.as_ref().map(|package| {
        latent_artifacts::package::artifact_blob_digest(&package.manifest).to_string()
    });
    let mut client = ReleaseServiceClient::new(session.channel())
        .max_decoding_message_size(session.max_response_bytes())
        .max_encoding_message_size(session.max_request_bytes());
    let value = session
        .call(client.publish_release(session.request(request)?))
        .await?
        .into_inner();
    if value.admission_warnings.len() > 64
        || value.admission_warnings.iter().any(|v| v.len() > 4096)
    {
        return Err(invalid_response());
    }
    if value.release.is_some() {
        bounds::checked(&value, session.max_response_bytes())?;
    }
    association::release(
        value.release.as_ref(),
        session.tenant(),
        digest.as_deref(),
        None,
    )?;
    if let Some(ack) = &value.audit_ack {
        projection::checked(ack, session.max_response_bytes())?;
    }
    if let Some(receipt) = &value.operation {
        checked_receipt(
            receipt,
            session,
            &receipt.operation_id,
            digest.as_deref(),
            None,
        )?;
        if receipt.action != proto::ReleaseLifecycleAction::Publish as i32 {
            return Err(invalid_response());
        }
        if let Some(release) = &value.release {
            if receipt.component_digest.as_deref() != Some(&release.digest) {
                return Err(invalid_response());
            }
        }
    }
    if let Some(op) = &op {
        let receipt = value.operation.as_ref().ok_or_else(invalid_response)?;
        checked_receipt(
            receipt,
            session,
            &op.operation_id,
            digest.as_deref(),
            Some(op),
        )?;
        if receipt.action != proto::ReleaseLifecycleAction::Publish as i32
            || package
                .as_deref()
                .is_some_and(|p| receipt.package_manifest_digest.as_deref() != Some(p))
        {
            return Err(invalid_response());
        }
        if let Some(release) = &value.release {
            if receipt.component_digest.as_deref() != Some(&release.digest) {
                return Err(invalid_response());
            }
        }
    } else if value.release.is_none() {
        return Err(invalid_response());
    }
    if prost::Message::encoded_len(&value) > session.max_response_bytes() {
        return Err(invalid_response());
    }
    publication_identity(&value, package.as_deref())?;
    let rejected = value
        .operation
        .as_ref()
        .is_some_and(|op| op.disposition == proto::ReleaseOperationDisposition::Rejected as i32);
    Ok(mutation(
        json!({"release":value.release.map(response::release).transpose()?,"admissionWarnings":value.admission_warnings,"operation":value.operation.map(Project::project),"auditAck":value.audit_ack.map(Project::project)}),
        rejected,
    ))
}

fn publication_identity(
    value: &proto::PublishReleaseResponse,
    package: Option<&str>,
) -> Result<(), Failure> {
    if let Some(receipt) = &value.operation {
        if receipt.disposition == proto::ReleaseOperationDisposition::Committed as i32
            && (value.release.is_none()
                || package.is_some_and(|expected| {
                    receipt
                        .record
                        .as_ref()
                        .is_none_or(|record| record.package_digest.as_deref() != Some(expected))
                }))
        {
            return Err(invalid_response());
        }
    }
    Ok(())
}
fn checked_receipt(
    value: &proto::ReleaseOperationReceipt,
    session: &Session,
    id: &str,
    digest: Option<&str>,
    generation: Option<&proto::ReleaseOperationPrecondition>,
) -> Result<(), Failure> {
    bounds::checked(value, session.max_response_bytes())?;
    projection::checked(value, session.max_response_bytes())?;
    if value.tenant != session.tenant()
        || value.operation_id != id
        || digest.is_some_and(|digest| value.component_digest.as_deref() != Some(digest))
        || generation
            .is_some_and(|generation| value.expected_generation != generation.expected_generation)
    {
        return Err(invalid_response());
    }
    Ok(())
}
fn lookup(disposition: i32, receipt: Option<&str>, id: &str) -> Result<(), Failure> {
    if (disposition == proto::ReleaseOperationLookupDisposition::Found as i32)
        != (receipt == Some(id))
        || receipt.is_some_and(|value| value != id)
    {
        return Err(invalid_response());
    }
    Ok(())
}
fn mutation(data: serde_json::Value, rejected: bool) -> Outcome {
    let mut output = Outcome::success(data);
    if rejected {
        output.category = Category::PlatformError;
        output.error = Some(
            json!({"code":"release-operation-rejected","message":"The node retained a rejected release operation."}),
        );
    }
    output
}

async fn lifecycle(
    request: proto::GetReleaseLifecycleRequest,
    session: &Session,
) -> Result<Outcome, Failure> {
    let digest = request.digest.clone();
    let value = call!(
        session,
        ReleaseServiceClient,
        get_release_lifecycle,
        request
    );
    if let Some(status) = &value.status {
        let record = status.record.as_ref().ok_or_else(invalid_response)?;
        bounds::checked(record, session.max_response_bytes())?;
        if record.tenant != session.tenant() || record.component_digest != digest {
            return Err(invalid_response());
        }
    }
    let found = value.status.is_some();
    Ok(if found {
        Outcome::success(value.project())
    } else {
        Outcome::not_found(value.project())
    })
}

async fn get_receipt(
    request: proto::GetReleaseOperationRequest,
    session: &Session,
) -> Result<Outcome, Failure> {
    let id = request.operation_id.clone();
    let value = call!(
        session,
        ReleaseServiceClient,
        get_release_operation,
        request
    );
    lookup(
        value.lookup,
        value
            .receipt
            .as_ref()
            .map(|receipt| receipt.operation_id.as_str()),
        &id,
    )?;
    if let Some(receipt) = &value.receipt {
        checked_receipt(receipt, session, &id, None, None)?;
    }
    let known = value.lookup == proto::ReleaseOperationLookupDisposition::Found as i32;
    let mut output = Outcome::success(value.project());
    output.outcome_known = known;
    Ok(output)
}

async fn change(
    request: proto::ChangeReleaseLifecycleRequest,
    session: &Session,
) -> Result<Outcome, Failure> {
    let op = request
        .operation
        .as_ref()
        .ok_or_else(invalid_input)?
        .clone();
    let digest = request.digest.clone();
    let action = request.action;
    let value = call!(
        session,
        ReleaseServiceClient,
        change_release_lifecycle,
        request
    );
    let receipt = value.operation.as_ref().ok_or_else(invalid_response)?;
    checked_receipt(receipt, session, &op.operation_id, Some(&digest), Some(&op))?;
    if receipt.action != action {
        return Err(invalid_response());
    }
    let rejected = receipt.disposition == proto::ReleaseOperationDisposition::Rejected as i32;
    Ok(mutation(value.project(), rejected))
}

async fn renew(
    request: proto::RenewReleaseEvidenceRequest,
    session: &Session,
) -> Result<Outcome, Failure> {
    let op = request
        .operation
        .as_ref()
        .ok_or_else(invalid_input)?
        .clone();
    let digest = request.digest.clone();
    let package = request.package_digest.clone();
    let value = call!(
        session,
        ReleaseServiceClient,
        renew_release_evidence,
        request
    );
    let receipt = value.operation.as_ref().ok_or_else(invalid_response)?;
    checked_receipt(receipt, session, &op.operation_id, Some(&digest), Some(&op))?;
    if receipt.action != proto::ReleaseLifecycleAction::RenewEvidence as i32
        || receipt
            .record
            .as_ref()
            .is_some_and(|record| record.package_digest.as_deref() != Some(&package))
    {
        return Err(invalid_response());
    }
    let rejected = receipt.disposition == proto::ReleaseOperationDisposition::Rejected as i32;
    Ok(mutation(value.project(), rejected))
}
