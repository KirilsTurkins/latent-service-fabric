use super::PolicyOperation;
use crate::{client::Session, error::Failure, output::Outcome};
use latent_policy::capability as domain;
use latent_rpc::control::v1::{self as proto, policy_service_client::PolicyServiceClient};
use prost::Message;
use serde_json::{json, Value};
mod validation;
use validation::{invalid, receipt, record};

macro_rules! call {
    ($session:ident,$method:ident,$request:expr) => {{
        let mut client = PolicyServiceClient::new($session.channel())
            .max_decoding_message_size($session.max_response_bytes().min(1024 * 1024))
            .max_encoding_message_size(128 * 1024);
        let response = $session
            .call(client.$method($session.request($request)?))
            .await?
            .into_inner();
        if response.encoded_len() > $session.max_response_bytes().min(1024 * 1024) {
            return Err(invalid());
        }
        response
    }};
}
pub async fn execute(operation: PolicyOperation, session: &Session) -> Result<Outcome, Failure> {
    match operation {
        PolicyOperation::Apply(request) => {
            let expected = request.policy.as_ref().ok_or_else(invalid)?.clone();
            let id = request.operation_id.clone();
            let previous = request.expected_generation.ok_or_else(invalid)?;
            let response = call!(session, apply_policy, request);
            let actual = response.policy.ok_or_else(invalid)?;
            let observed = record(
                &actual,
                session.tenant(),
                expected.record_kind,
                Some(&expected.id),
            )?;
            if actual.revoked
                || actual.document != expected.document
                || actual.generation <= previous
            {
                return Err(invalid());
            }
            let outcome = response.receipt.ok_or_else(invalid)?;
            let result = receipt(&outcome, session.tenant(), Some(&id))?;
            if outcome.id != actual.id
                || outcome.record_kind != actual.record_kind
                || outcome.generation != actual.generation
                || outcome.content_digest != actual.content_digest
                || outcome.revoked
            {
                return Err(invalid());
            }
            Ok(Outcome::success(
                json!({"policy":observed,"receipt":result}),
            ))
        }
        PolicyOperation::Get(request) => {
            let id = request.id.clone();
            let kind = request.record_kind;
            let response = call!(session, get_policy, request);
            match response.policy {
                Some(value) => Ok(Outcome::success(
                    json!({"policy":record(&value,session.tenant(),kind,Some(&id))?}),
                )),
                None => Ok(Outcome::not_found(json!({"id":id,"found":false}))),
            }
        }
        PolicyOperation::List(request) => {
            let expected = request.page.as_ref().ok_or_else(invalid)?;
            let count = expected.page_size as usize;
            let previous = expected.page_token.clone();
            let kind = request.record_kind;
            let response = call!(session, list_policies, request);
            if response.policies.len() > count
                || response.policies.len() > 32
                || response.catalog_generation == 0
            {
                return Err(invalid());
            }
            let page = response.page.ok_or_else(invalid)?;
            if page
                .next_page_token
                .as_ref()
                .is_some_and(|v| v.len() != 117 || !v.is_ascii() || previous.as_ref() == Some(v))
            {
                return Err(invalid());
            }
            let mut ids = std::collections::BTreeSet::new();
            let mut records = Vec::new();
            for value in response.policies {
                if !ids.insert(value.id.clone()) || value.generation > response.catalog_generation {
                    return Err(invalid());
                }
                records.push(record(&value, session.tenant(), kind, None)?);
            }
            Ok(Outcome::success(
                json!({"policies":records,"catalogGeneration":response.catalog_generation.to_string(),"nextPageToken":page.next_page_token}),
            ))
        }
        PolicyOperation::Revoke(request) => {
            let id = request.id.clone();
            let operation = request.operation_id.clone();
            call!(session, delete_policy, request);
            Ok(Outcome::success(
                json!({"id":id,"operationId":operation,"revocationAcknowledged":true}),
            ))
        }
        PolicyOperation::Outcome(request) => {
            let operation = request.operation_id.clone();
            let response = call!(session, get_policy_operation, request);
            outcome(response, session.tenant(), &operation)
        }
        PolicyOperation::Explain(request) => explain(&call!(session, evaluate_policy, request)),
    }
}
fn explain(value: &proto::EvaluatePolicyResponse) -> Result<Outcome, Failure> {
    let reason = value.reasons.first().ok_or_else(invalid)?;
    let code = match value.decision.as_str() {
        "allow" => "policy-rules-match",
        "deny" => "policy-rules-deny",
        "indeterminate" => "policy-authority-unavailable",
        _ => return Err(invalid()),
    };
    if value.reasons.len() != 1
        || reason.code != code
        || !reason.attributes.is_empty()
        || !value.obligations.is_empty()
        || value.policy_version != domain::LANGUAGE
        || reason.message != "Read-only policy observation; not execution permission"
    {
        return Err(invalid());
    }
    Ok(Outcome::success(
        json!({"decision":value.decision,"reason":code,"executionPermission":false}),
    ))
}

fn outcome(
    response: proto::GetPolicyOperationResponse,
    tenant: &str,
    operation: &str,
) -> Result<Outcome, Failure> {
    if let Some(value) = response.receipt {
        return Ok(Outcome::success(
            json!({"receipt":receipt(&value,tenant,Some(operation))?}),
        ));
    }
    let mut result = Outcome::not_found(
        json!({"operationId":operation,"retained":false,"mutationOutcome":"unknown"}),
    );
    result.outcome_known = false;
    Ok(result)
}
