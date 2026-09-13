use crate::{
    args::policy::{PolicyArgs, PolicyCommand, PolicyKind},
    config::ResolvedConfig,
    error::Failure,
    input,
    operation::Operation,
};
use latent_policy::capability as domain;
use latent_rpc::control::v1 as proto;
use prost::Message;
mod execute;
pub use execute::execute;

pub enum PolicyOperation {
    Apply(proto::ApplyPolicyRequest),
    Get(proto::GetPolicyRequest),
    List(proto::ListPoliciesRequest),
    Revoke(proto::DeletePolicyRequest),
    Outcome(proto::GetPolicyOperationRequest),
    Explain(proto::EvaluatePolicyRequest),
}
impl PolicyOperation {
    pub fn encoded_len(&self) -> usize {
        match self {
            Self::Apply(v) => v.encoded_len(),
            Self::Get(v) => v.encoded_len(),
            Self::List(v) => v.encoded_len(),
            Self::Revoke(v) => v.encoded_len(),
            Self::Outcome(v) => v.encoded_len(),
            Self::Explain(v) => v.encoded_len(),
        }
    }
    pub fn recovery(&self) -> Option<serde_json::Value> {
        match self {
            Self::Apply(v) => Some(
                serde_json::json!({"family":"policy","operationId":v.operation_id,"policyId":v.policy.as_ref().map(|v|&v.id),"expectedGeneration":v.expected_generation.map(|v|v.to_string())}),
            ),
            Self::Revoke(v) => Some(
                serde_json::json!({"family":"policy","operationId":v.operation_id,"policyId":v.id,"expectedGeneration":v.expected_generation.map(|v|v.to_string())}),
            ),
            _ => None,
        }
    }
}
pub fn prepare(args: &PolicyArgs, config: &ResolvedConfig) -> Result<Operation, Failure> {
    let kind = match args.kind {
        PolicyKind::Policy => proto::CapabilityPolicyRecordKind::Policy,
        PolicyKind::ProviderBinding => proto::CapabilityPolicyRecordKind::ProviderBinding,
    };
    let operation = match &args.command {
        PolicyCommand::Apply {
            id,
            file,
            operation_id,
            expected_generation,
        } => {
            let bytes = input::read(file, domain::MAX_DOCUMENT_BYTES, "policy")?;
            let (document, language, tenant) = parse_document(args.kind, &bytes)?;
            if tenant != config.tenant {
                return Err(invalid());
            }
            PolicyOperation::Apply(proto::ApplyPolicyRequest {
                policy: Some(proto::Policy {
                    id: id.clone(),
                    metadata: Some(proto::ObjectMetadata {
                        name: id.clone(),
                        tenant: Some(tenant),
                        ..proto::ObjectMetadata::default()
                    }),
                    document,
                    generation: 0,
                    language: language.into(),
                    record_kind: kind as i32,
                    content_digest: String::new(),
                    revoked: false,
                }),
                expected_generation: Some(*expected_generation),
                operation_id: operation_id.clone(),
            })
        }
        PolicyCommand::Get { id } => PolicyOperation::Get(proto::GetPolicyRequest {
            id: id.clone(),
            record_kind: kind as i32,
        }),
        PolicyCommand::List {
            page_size,
            page_token,
        } => PolicyOperation::List(proto::ListPoliciesRequest {
            record_kind: kind as i32,
            page: Some(proto::PageRequest {
                page_size: *page_size,
                page_token: page_token.clone(),
            }),
        }),
        PolicyCommand::Revoke {
            id,
            operation_id,
            expected_generation,
        } => PolicyOperation::Revoke(proto::DeletePolicyRequest {
            id: id.clone(),
            operation_id: operation_id.clone(),
            expected_generation: Some(*expected_generation),
            record_kind: kind as i32,
        }),
        PolicyCommand::Operation { operation_id } => {
            PolicyOperation::Outcome(proto::GetPolicyOperationRequest {
                operation_id: operation_id.clone(),
            })
        }
        PolicyCommand::Explain {
            id,
            provider_binding,
            service,
            publication_id,
            capability,
            operation,
            resource,
            additional_policy,
        } => {
            let bytes = input::read(resource, 4096, "policy-resource")?;
            domain::ResourceRequest::parse(&bytes).map_err(|_| invalid())?;
            if publication_id
                .parse::<latent_core::PublicationId>()
                .is_err()
            {
                return Err(invalid());
            }
            PolicyOperation::Explain(proto::EvaluatePolicyRequest {
                policy_id: id.clone(),
                service: service.clone(),
                publication_id: publication_id.clone(),
                capability: capability.clone(),
                operation: operation.clone(),
                resource_document: String::from_utf8(bytes).map_err(|_| invalid())?,
                provider_binding_id: provider_binding.clone(),
                additional_policy_ids: additional_policy.clone(),
                ..proto::EvaluatePolicyRequest::default()
            })
        }
    };
    Ok(Operation::Policy(Box::new(operation)))
}
fn invalid() -> Failure {
    Failure::local(
        "invalid-capability-policy",
        "The policy input does not match the supported scope and document profile.",
    )
}

fn parse_document(
    kind: PolicyKind,
    bytes: &[u8],
) -> Result<(String, &'static str, String), Failure> {
    let (document, language, tenant) = match kind {
        PolicyKind::Policy => {
            let v = domain::CapabilityPolicy::parse(bytes).map_err(|_| invalid())?;
            (
                v.canonical().to_vec(),
                domain::LANGUAGE,
                v.tenant().to_owned(),
            )
        }
        PolicyKind::ProviderBinding => {
            let v = domain::ProviderBinding::parse(bytes).map_err(|_| invalid())?;
            (
                v.canonical().to_vec(),
                domain::PROVIDER_BINDING_LANGUAGE,
                v.tenant().to_owned(),
            )
        }
    };
    Ok((
        String::from_utf8(document).map_err(|_| invalid())?,
        language,
        tenant,
    ))
}
