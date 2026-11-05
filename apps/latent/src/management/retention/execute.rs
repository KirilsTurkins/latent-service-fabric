use super::{proto, MaintenanceOperation};
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
pub async fn execute(
    operation: MaintenanceOperation,
    session: &Session,
) -> Result<Outcome, Failure> {
    let mut client = ReleaseServiceClient::new(session.channel())
        .max_decoding_message_size(session.max_response_bytes())
        .max_encoding_message_size(session.max_request_bytes());
    let tenant = session.tenant();
    let maximum = session.max_response_bytes();
    let value = match operation {
        MaintenanceOperation::Snapshot(request) => {
            let selected = request.publications.clone();
            let value = session
                .call(client.get_publication_retention(session.request(request)?))
                .await?
                .into_inner();
            projection::checked(&value, maximum)?;
            if value.tenant != tenant
                || !value
                    .entries
                    .iter()
                    .map(|e| e.target.as_ref().unwrap().publication.as_ref().unwrap())
                    .eq(selected.iter())
            {
                return Err(invalid_response());
            }
            value.project()
        }
        MaintenanceOperation::Maintain(request) => {
            let command = request.command.clone();
            let response = session
                .call(client.maintain_publications(session.request(request)?))
                .await?;
            let metadata = crate::management::phase2::audit_metadata(response.metadata())?;
            let value = response.into_inner();
            projection::checked(&value, maximum)?;
            let receipt = value.receipt.as_ref().unwrap();
            if receipt.tenant != tenant || receipt.command != command {
                return Err(invalid_response());
            }
            // The public protocol always carries both audit representations.
            // Reject contradictions instead of hiding a lost audit acknowledgement.
            let ack = value.audit_ack.as_ref().unwrap();
            let status = match proto::AuditAckStatus::try_from(ack.status)
                .map_err(|_| invalid_response())?
            {
                proto::AuditAckStatus::Durable => "durable",
                proto::AuditAckStatus::OutcomeUnknown => "outcome-unknown",
                proto::AuditAckStatus::AuditUnavailable => "audit-unavailable",
                _ => return Err(invalid_response()),
            };
            let sequence = ack.attempt_sequence.map(|v| v.to_string());
            if metadata != Some(serde_json::json!({"status":status,"attemptSequence":sequence})) {
                return Err(invalid_response());
            }
            value.project()
        }
        MaintenanceOperation::Assess(request) => {
            let deletion = request.deletion.clone();
            let files = request.maximum_files;
            let bytes = request.maximum_bytes_hashed;
            let value = session
                .call(client.assess_publication_reclamation(session.request(request)?))
                .await?
                .into_inner();
            projection::checked(&value, maximum)?;
            if value.tenant != tenant
                || value.deletion != deletion
                || value.potential.as_ref().unwrap().bytes_hashed > bytes
                || value.potential.as_ref().unwrap().publication_files > files
            {
                return Err(invalid_response());
            }
            value.project()
        }
        MaintenanceOperation::Lookup(request) => {
            let kind = request.kind;
            let id = request.operation_id.clone();
            let value = session
                .call(client.get_publication_maintenance_operation(session.request(request)?))
                .await?
                .into_inner();
            projection::checked(&value, maximum)?;
            if value.tenant != tenant
                || value.receipt.as_ref().is_some_and(|r| {
                    r.command.as_ref().unwrap().kind != kind
                        || r.command
                            .as_ref()
                            .unwrap()
                            .selection
                            .as_ref()
                            .unwrap()
                            .operation_id
                            != id
                })
            {
                return Err(invalid_response());
            }
            value.project()
        }
    };
    Ok(Outcome::success(value))
}
