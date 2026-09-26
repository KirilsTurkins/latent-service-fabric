#[cfg(test)]
mod tests;

use crate::{
    args::phase3::CapabilityCommand,
    client::Session,
    error::Failure,
    input,
    management::{
        invalid_response,
        phase2::projection::{self, Project},
        triggers::response::page,
    },
    operation::Operation,
    output::Outcome,
};
use latent_rpc::control::v1::{self as proto, capability_service_client::CapabilityServiceClient};
use prost::Message;

pub enum CapabilityOperation {
    List(proto::ListCapabilitiesRequest),
    Explain(proto::ExplainCapabilityGrantRequest),
}

impl CapabilityOperation {
    pub fn encoded_len(&self) -> usize {
        match self {
            Self::List(request) => request.encoded_len(),
            Self::Explain(request) => request.encoded_len(),
        }
    }
}

pub fn prepare(command: &CapabilityCommand) -> Result<Operation, Failure> {
    command.validate()?;
    let operation = match command {
        CapabilityCommand::List {
            deployment,
            provider,
            contract_prefix,
            include_node_usage,
            page_size,
            page_token,
        } => CapabilityOperation::List(proto::ListCapabilitiesRequest {
            deployment_id: deployment.clone(),
            provider: provider.clone(),
            contract_prefix: contract_prefix.clone(),
            include_node_usage: *include_node_usage,
            page: Some(proto::PageRequest {
                page_size: *page_size,
                page_token: page_token.clone(),
            }),
        }),
        CapabilityCommand::Explain {
            deployment,
            capability,
            operation,
            resource,
        } => {
            let bytes = input::read(resource, 4096, "capability-resource")?;
            latent_wire::management::parse_inspection_resource(&bytes).map_err(|_| invalid())?;
            CapabilityOperation::Explain(proto::ExplainCapabilityGrantRequest {
                deployment_id: deployment.clone(),
                capability_id: capability.clone(),
                operation: operation.clone(),
                resource_document: String::from_utf8(bytes).map_err(|_| invalid())?,
                ..Default::default()
            })
        }
    };
    if operation.encoded_len() > 8 * 1024 {
        return Err(invalid());
    }
    Ok(Operation::Capability(Box::new(operation)))
}

fn invalid() -> Failure {
    Failure::local(
        "invalid-capability-inspection",
        "A supported resource and one bounded deployment-scoped inspection are required.",
    )
}

fn client(session: &Session) -> CapabilityServiceClient<tonic::transport::Channel> {
    CapabilityServiceClient::new(session.channel())
        .max_decoding_message_size(session.max_response_bytes().min(128 * 1024))
        .max_encoding_message_size(session.max_request_bytes().min(8 * 1024))
}

pub async fn execute(
    operation: CapabilityOperation,
    session: &Session,
) -> Result<Outcome, Failure> {
    match operation {
        CapabilityOperation::List(request) => {
            let deployment = request.deployment_id.clone();
            let requested = request.page.as_ref().ok_or_else(invalid_response)?;
            let maximum = requested.page_size as usize;
            let previous = requested.page_token.clone();
            let node_usage = request.include_node_usage;
            let provider = request.provider.clone();
            let prefix = request.contract_prefix.clone();
            let value = session
                .call(client(session).list_capabilities(session.request(request)?))
                .await?
                .into_inner();
            projection::checked(&value, session.max_response_bytes().min(128 * 1024))?;
            if value
                .revision
                .as_ref()
                .is_none_or(|revision| revision.deployment_id != deployment)
                || value.capabilities.len() > maximum
                || value.node_usage.is_some() != node_usage
                || value.capabilities.iter().any(|entry| {
                    provider
                        .as_ref()
                        .is_some_and(|expected| &entry.provider != expected)
                        || prefix
                            .as_ref()
                            .is_some_and(|expected| !entry.contract.starts_with(expected))
                })
            {
                return Err(invalid_response());
            }
            let next = &value
                .page
                .as_ref()
                .ok_or_else(invalid_response)?
                .next_page_token;
            page(next.as_ref(), previous.as_ref(), 160)?;
            if next.is_some() && value.capabilities.is_empty() {
                return Err(invalid_response());
            }
            Ok(Outcome::success(value.project()))
        }
        CapabilityOperation::Explain(request) => {
            let deployment = request.deployment_id.clone();
            let value = session
                .call(client(session).explain_capability_grant(session.request(request)?))
                .await?
                .into_inner();
            projection::checked(&value, session.max_response_bytes().min(128 * 1024))?;
            if value
                .revision
                .as_ref()
                .is_none_or(|revision| revision.deployment_id != deployment)
            {
                return Err(invalid_response());
            }
            Ok(Outcome::success(value.project()))
        }
    }
}
