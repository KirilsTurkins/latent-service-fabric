//! Explicit single-call Phase 4 operations on the existing credential/channel.
mod execute;
mod prepare;
mod projection;
#[cfg(test)]
mod tests;
pub use execute::execute;
pub use prepare::{prepare_state, prepare_transaction};

use crate::error::Failure;
pub(super) fn invalid() -> Failure {
    Failure::local(
        "invalid-phase4-request",
        "The exact Phase 4 request or bounded configuration is invalid.",
    )
}

pub(crate) fn recovery(request: &latent_rpc::phase4::Request) -> Option<serde_json::Value> {
    use latent_rpc::phase4::Request;
    use serde_json::json;
    match request {
        Request::MutateNamespace(value) => Some(
            json!({"family":"namespace","operationId":value.operation_id,
            "namespace":value.namespace.as_ref().and_then(|v|v.namespace.as_ref()).map(projection::namespace),
            "authorizationPublication":value.namespace.as_ref().and_then(|v|v.authorization_publication.as_ref()).map(|v|json!({"id":v.id,"tenant":v.tenant})),
            "expectedGeneration":value.expected_generation.map(|v|v.to_string())}),
        ),
        Request::MutateState(value) => {
            Some(json!({"family":"state","operationId":value.operation_id,
            "namespace":value.namespace.as_ref().and_then(|v|v.namespace.as_ref()).map(projection::namespace),
            "expectedVersion":projection::bytes(&value.expected_version),"expectedPolicyDigest":value.expected_policy_digest}))
        }
        Request::InvokeCommand(value) => Some(
            json!({"family":"command","command":value.command.as_ref().map(projection::selector),
            "retryRequestId":value.retry_attempt.as_ref().map(|v|&v.request_id),"automaticRetry":false}),
        ),
        Request::CancelCommand(value) => Some(
            json!({"family":"command","command":value.command.as_ref().and_then(|v|v.command.as_ref()).map(projection::selector),
            "attemptId":value.command.as_ref().and_then(|v|v.attempt_id.as_ref()),"automaticRetry":false}),
        ),
        _ => None,
    }
}
