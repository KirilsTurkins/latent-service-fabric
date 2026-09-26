use super::{response, TriggerOperation};
use crate::{
    client::Session,
    error::Failure,
    management::{
        invalid_response,
        phase2::{
            audit_metadata,
            projection::{self, Project},
        },
    },
    output::Outcome,
};
use latent_rpc::control::v1::{self as proto, trigger_service_client::TriggerServiceClient};
use prost::Message;
use serde_json::json;

fn client(session: &Session) -> TriggerServiceClient<tonic::transport::Channel> {
    TriggerServiceClient::new(session.channel())
        .max_decoding_message_size(session.max_response_bytes().min(512 * 1024))
        .max_encoding_message_size(session.max_request_bytes().min(64 * 1024))
}

fn check<T: Message>(value: &T, session: &Session) -> Result<(), Failure> {
    if value.encoded_len() > session.max_response_bytes().min(512 * 1024) {
        return Err(invalid_response());
    }
    Ok(())
}

pub async fn execute(operation: TriggerOperation, session: &Session) -> Result<Outcome, Failure> {
    match operation {
        TriggerOperation::Apply(request) => apply(*request, session).await,
        TriggerOperation::Delete(request) => delete(request, session).await,
        TriggerOperation::Get(request) => get(request, session).await,
        TriggerOperation::List(request) => {
            let page = request.page.as_ref().ok_or_else(invalid_response)?;
            let maximum = page.page_size as usize;
            let previous = page.page_token.clone();
            let service = request.target_service.clone();
            let value = session
                .call(client(session).list_triggers(session.request(request)?))
                .await?
                .into_inner();
            check(&value, session)?;
            let next = value.page.ok_or_else(invalid_response)?.next_page_token;
            response::page(next.as_ref(), previous.as_ref(), 128)?;
            if value.triggers.len() > maximum || (next.is_some() && value.triggers.is_empty()) {
                return Err(invalid_response());
            }
            let mut ids = std::collections::BTreeSet::new();
            let mut entries = Vec::new();
            for entry in value.triggers {
                if !ids.insert(entry.id.clone())
                    || service.as_ref().is_some_and(|expected| {
                        entry
                            .target
                            .as_ref()
                            .is_none_or(|target| &target.service != expected)
                    })
                {
                    return Err(invalid_response());
                }
                entries.push(response::trigger(entry, session.tenant(), None)?);
            }
            Ok(Outcome::success(
                json!({"triggers":entries, "stateVersion":value.state_version.to_string(),
                "routeGeneration":value.route_generation.to_string(), "nextPageToken":next}),
            ))
        }
        TriggerOperation::Lookup(request) => {
            let id = request.operation_id.clone();
            let value = session
                .call(client(session).get_trigger_operation(session.request(request)?))
                .await?
                .into_inner();
            check(&value, session)?;
            let disposition =
                match proto::TriggerOperationLookupDisposition::try_from(value.disposition) {
                    Ok(proto::TriggerOperationLookupDisposition::Found)
                        if value.receipt.is_some() =>
                    {
                        "found"
                    }
                    Ok(proto::TriggerOperationLookupDisposition::Unknown)
                        if value.receipt.is_none() =>
                    {
                        "unknown"
                    }
                    Ok(proto::TriggerOperationLookupDisposition::Uncertain)
                        if value.receipt.is_none() =>
                    {
                        "uncertain"
                    }
                    _ => return Err(invalid_response()),
                };
            if value.retained_floor > value.high_watermark {
                return Err(invalid_response());
            }
            if let Some(receipt) = &value.receipt {
                response::receipt_scope(receipt, session.tenant(), &id, None)?;
            }
            let mut output = Outcome::success(json!({"disposition":disposition,
                "receipt":value.receipt.map(Project::project), "retainedFloor":value.retained_floor.to_string(),
                "highWatermark":value.high_watermark.to_string(), "executionPermission":false}));
            output.outcome_known = disposition == "found";
            Ok(output)
        }
    }
}

async fn get(request: proto::GetTriggerRequest, session: &Session) -> Result<Outcome, Failure> {
    let id = request.id.clone();
    let value = session
        .call(client(session).get_trigger(session.request(request)?))
        .await?
        .into_inner();
    check(&value, session)?;
    let durability = response::durability(value.durability)?;
    let trigger = value
        .trigger
        .map(|entry| response::trigger(entry, session.tenant(), Some(&id)))
        .transpose()?;
    let found = trigger.is_some();
    let data = json!({"trigger":trigger, "stateVersion":value.state_version.to_string(),
        "routeGeneration":value.route_generation.to_string(), "durability":durability});
    let mut output = if found {
        Outcome::success(data)
    } else {
        Outcome::not_found(data)
    };
    output.outcome_known = durability == "confirmed";
    Ok(output)
}

async fn apply(request: proto::ApplyTriggerRequest, session: &Session) -> Result<Outcome, Failure> {
    let expected = request
        .trigger
        .as_ref()
        .ok_or_else(invalid_response)?
        .clone();
    let operation = request
        .operation
        .as_ref()
        .ok_or_else(invalid_response)?
        .clone();
    let generation = request.expected_generation;
    let value = session
        .call(client(session).apply_trigger(session.request(request)?))
        .await?
        .into_inner();
    check(&value, session)?;
    let receipt = value.receipt.as_ref().ok_or_else(invalid_response)?;
    response::receipt_scope(
        receipt,
        session.tenant(),
        &operation.operation_id,
        Some(&expected.id),
    )?;
    let trigger = value.trigger.as_ref().ok_or_else(invalid_response)?;
    let mut actual = trigger.clone();
    actual.generation = 0;
    let target = expected.target.as_ref().ok_or_else(invalid_response)?;
    if actual != expected
        || trigger.generation != receipt.object_generation
        || receipt.action != proto::TriggerOperationAction::Apply as i32
        || Some(receipt.expected_generation) != generation
        || Some(receipt.expected_state_version) != operation.expected_state_version
        || !response::target_matches(receipt, target)
        || !value.warnings.is_empty()
    {
        return Err(invalid_response());
    }
    let ack = value.audit_ack.ok_or_else(invalid_response)?;
    projection::checked(&ack, session.max_response_bytes())?;
    let durability = response::durability(value.durability)?;
    let mut output = Outcome::success(json!({
        "trigger":response::trigger(value.trigger.ok_or_else(invalid_response)?, session.tenant(), Some(&expected.id))?,
        "receipt":value.receipt.map(Project::project), "auditAck":ack.project(),
        "replayed":value.replayed, "durability":durability
    }));
    output.outcome_known = durability == "confirmed";
    Ok(output)
}

async fn delete(
    request: proto::DeleteTriggerRequest,
    session: &Session,
) -> Result<Outcome, Failure> {
    let operation = request
        .operation
        .as_ref()
        .ok_or_else(invalid_response)?
        .clone();
    let expected = request.expected_generation.ok_or_else(invalid_response)?;
    let id = request.id.clone();
    let value = session
        .call(client(session).delete_trigger(session.request(request)?))
        .await?;
    let data = response::deletion(value.metadata(), &operation, expected, &id)?;
    let audit = audit_metadata(value.metadata())?.ok_or_else(invalid_response)?;
    let known = data["durability"] == "confirmed";
    let mut output = Outcome::success(data);
    output.data["auditAck"] = audit;
    output.outcome_known = known;
    Ok(output)
}
