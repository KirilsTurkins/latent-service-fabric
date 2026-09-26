use super::{invalid_input, proto, WebOperation};
use crate::{
    client::Session,
    error::Failure,
    management::{
        invalid_response,
        phase2::projection::{self, Project},
    },
    output::Outcome,
};
use proto::release_service_client::ReleaseServiceClient;

fn client(session: &Session) -> ReleaseServiceClient<tonic::transport::Channel> {
    ReleaseServiceClient::new(session.channel())
        .max_decoding_message_size(session.max_response_bytes())
        .max_encoding_message_size(session.max_request_bytes())
}

pub async fn execute(operation: WebOperation, session: &Session) -> Result<Outcome, Failure> {
    match operation {
        WebOperation::Prepare(request) => prepare(request, session).await,
        WebOperation::Publish(request) => {
            let package = request.package.as_ref().ok_or_else(invalid_input)?;
            let selected = super::publication(
                &latent_artifacts::package::package_digest(&package.manifest),
                session.tenant(),
            )?;
            let operation = request.operation.clone().ok_or_else(invalid_input)?;
            let response = session
                .call(client(session).publish_web_package(session.request(request)?))
                .await?
                .into_inner();
            mutation(
                response.operation,
                response.audit_ack,
                &selected,
                &operation,
                proto::ReleaseLifecycleAction::Publish as i32,
                proto::ReleaseLifecycleReason::Admitted as i32,
                session,
            )
        }
        WebOperation::Change(request) => {
            let selected = request.publication.clone().ok_or_else(invalid_input)?;
            let operation = request.operation.clone().ok_or_else(invalid_input)?;
            let action = request.action;
            let reason = request.reason;
            let response = session
                .call(client(session).change_web_lifecycle(session.request(request)?))
                .await?
                .into_inner();
            mutation(
                response.operation,
                response.audit_ack,
                &selected,
                &operation,
                action,
                reason,
                session,
            )
        }
        WebOperation::Renew(request) => {
            let selected = request.publication.clone().ok_or_else(invalid_input)?;
            let operation = request.operation.clone().ok_or_else(invalid_input)?;
            let response = session
                .call(client(session).renew_web_evidence(session.request(request)?))
                .await?
                .into_inner();
            mutation(
                response.operation,
                response.audit_ack,
                &selected,
                &operation,
                proto::ReleaseLifecycleAction::RenewEvidence as i32,
                proto::ReleaseLifecycleReason::EvidenceRenewed as i32,
                session,
            )
        }
        WebOperation::Get(request) => {
            let selected = request.publication.clone().ok_or_else(invalid_input)?;
            let response = session
                .call(client(session).get_web_publication(session.request(request)?))
                .await?
                .into_inner();
            projection::checked(&response, session.max_response_bytes())?;
            if selected.tenant != session.tenant()
                || response
                    .record
                    .as_ref()
                    .and_then(|record| record.publication.as_ref())
                    != Some(&selected)
            {
                return Err(invalid_response());
            }
            Ok(Outcome::success(response.project()))
        }
        WebOperation::Operation(request) => {
            let operation_id = request.operation_id.clone();
            let response = session
                .call(client(session).get_web_operation(session.request(request)?))
                .await?
                .into_inner();
            lookup(
                response,
                &operation_id,
                session.tenant(),
                session.max_response_bytes(),
            )
        }
    }
}

async fn prepare(
    request: proto::PrepareWebPublicationRequest,
    session: &Session,
) -> Result<Outcome, Failure> {
    let selected = request.publication.clone().ok_or_else(invalid_input)?;
    let generation = request.lifecycle_generation;
    let response = session
        .call(client(session).prepare_web_publication(session.request(request)?))
        .await?
        .into_inner();
    projection::checked(&response, session.max_response_bytes())?;
    if selected.tenant != session.tenant()
        || response.publication.as_ref() != Some(&selected)
        || response.lifecycle_generation != generation
    {
        return Err(invalid_response());
    }
    Ok(Outcome::success(response.project()))
}

fn mutation(
    receipt: Option<proto::WebOperationReceipt>,
    audit_ack: Option<proto::AuditAck>,
    publication: &proto::PublicationRef,
    operation: &proto::ReleaseOperationPrecondition,
    action: i32,
    reason: i32,
    session: &Session,
) -> Result<Outcome, Failure> {
    let response = proto::WebMutationResponse {
        operation: receipt,
        audit_ack,
    };
    projection::checked(&response, session.max_response_bytes())?;
    let receipt = response.operation.as_ref().ok_or_else(invalid_response)?;
    association(
        receipt,
        publication,
        operation,
        action,
        reason,
        session.tenant(),
    )?;
    Ok(Outcome::success(response.project()))
}

pub(super) fn association(
    receipt: &proto::WebOperationReceipt,
    publication: &proto::PublicationRef,
    operation: &proto::ReleaseOperationPrecondition,
    action: i32,
    reason: i32,
    tenant: &str,
) -> Result<(), Failure> {
    if publication.tenant != tenant
        || receipt.publication.as_ref() != Some(publication)
        || receipt.operation_id != operation.operation_id
        || Some(receipt.expected_generation) != operation.expected_generation
        || receipt.action != action
        || receipt.reason != reason
    {
        return Err(invalid_response());
    }
    Ok(())
}

pub(super) fn lookup(
    response: proto::GetWebOperationResponse,
    operation_id: &str,
    tenant: &str,
    maximum: usize,
) -> Result<Outcome, Failure> {
    projection::checked(&response, maximum)?;
    if response.tenant != tenant
        || response
            .operation
            .as_ref()
            .is_some_and(|receipt| receipt.operation_id != operation_id)
    {
        return Err(invalid_response());
    }
    let known = response.disposition == proto::ReleaseOperationLookupDisposition::Found as i32;
    let mut outcome = Outcome::success(response.project());
    outcome.outcome_known = known;
    Ok(outcome)
}
