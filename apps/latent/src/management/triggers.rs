mod execute;
pub(super) mod response;
#[cfg(test)]
mod tests;

use crate::{
    args::phase3::{TriggerCommand, TriggerMutation},
    config::ResolvedConfig,
    error::Failure,
    input,
    operation::Operation,
};
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use latent_rpc::control::v1 as proto;
use prost::Message;
use serde_json::{json, Value};

pub use execute::execute;

pub enum TriggerOperation {
    Apply(Box<proto::ApplyTriggerRequest>),
    Get(proto::GetTriggerRequest),
    List(proto::ListTriggersRequest),
    Delete(proto::DeleteTriggerRequest),
    Lookup(proto::GetTriggerOperationRequest),
}

impl TriggerOperation {
    pub fn encoded_len(&self) -> usize {
        match self {
            Self::Apply(request) => request.encoded_len(),
            Self::Get(request) => request.encoded_len(),
            Self::List(request) => request.encoded_len(),
            Self::Delete(request) => request.encoded_len(),
            Self::Lookup(request) => request.encoded_len(),
        }
    }

    pub fn recovery(&self) -> Option<Value> {
        let (operation, generation, id, publication) = match self {
            Self::Apply(request) => (
                request.operation.as_ref()?,
                request.expected_generation?,
                request.trigger.as_ref()?.id.as_str(),
                request
                    .trigger
                    .as_ref()?
                    .target
                    .as_ref()?
                    .publication
                    .as_ref(),
            ),
            Self::Delete(request) => (
                request.operation.as_ref()?,
                request.expected_generation?,
                request.id.as_str(),
                None,
            ),
            _ => return None,
        };
        Some(json!({
            "family":"trigger", "operationId":operation.operation_id,
            "triggerId":id, "expectedGeneration":generation.to_string(),
            "expectedStateVersion":operation.expected_state_version.map(|value| value.to_string()),
            "publication":publication.map(|value| json!({"id":value.id,"tenant":value.tenant}))
        }))
    }
}

fn operation(value: &TriggerMutation) -> proto::TriggerOperationPrecondition {
    proto::TriggerOperationPrecondition {
        operation_id: value.operation_id.clone(),
        expected_state_version: Some(value.expected_state_version),
    }
}

pub fn prepare(command: &TriggerCommand, config: &ResolvedConfig) -> Result<Operation, Failure> {
    command.validate()?;
    let request = match command {
        TriggerCommand::Apply { file, mutation } => {
            let bytes = input::read(
                file,
                latent_control_store::http_routes::MAX_DEFINITION_BYTES,
                "trigger",
            )?;
            let manifest = JsonManifestCodec::default()
                .decode_trigger(&bytes)
                .map_err(|_| invalid())?;
            if manifest
                .metadata
                .tenant
                .as_ref()
                .map(|value| value.0.as_str())
                != Some(&config.tenant)
            {
                return Err(invalid());
            }
            let trigger = latent_wire::management::http_trigger_to_proto(manifest, 0)
                .map_err(|_| invalid())?;
            TriggerOperation::Apply(Box::new(proto::ApplyTriggerRequest {
                trigger: Some(trigger),
                expected_generation: Some(mutation.expected_generation),
                operation: Some(operation(mutation)),
            }))
        }
        TriggerCommand::Get { id } => {
            TriggerOperation::Get(proto::GetTriggerRequest { id: id.clone() })
        }
        TriggerCommand::List {
            service,
            page_size,
            page_token,
        } => TriggerOperation::List(proto::ListTriggersRequest {
            kind: Some("HttpTrigger".into()),
            target_service: service.clone(),
            page: Some(proto::PageRequest {
                page_size: *page_size,
                page_token: page_token.clone(),
            }),
        }),
        TriggerCommand::Delete { id, mutation } => {
            TriggerOperation::Delete(proto::DeleteTriggerRequest {
                id: id.clone(),
                expected_generation: Some(mutation.expected_generation),
                operation: Some(operation(mutation)),
            })
        }
        TriggerCommand::Operation { operation_id } => {
            TriggerOperation::Lookup(proto::GetTriggerOperationRequest {
                operation_id: operation_id.clone(),
            })
        }
    };
    if request.encoded_len() > 64 * 1024 {
        return Err(invalid());
    }
    Ok(Operation::Trigger(Box::new(request)))
}

fn invalid() -> Failure {
    Failure::local(
        "invalid-http-trigger",
        "An exact tenant-scoped buffered HTTP trigger and explicit preconditions are required.",
    )
}
