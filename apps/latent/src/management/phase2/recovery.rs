use crate::{error::Failure, operation::Operation, output::Outcome};
use serde_json::{json, Value};
use tonic::metadata::MetadataMap;

/// Compact caller selectors only; never retains request bytes or credentials.
pub(crate) struct RecoveryContext(Value);
impl RecoveryContext {
    pub(crate) fn from_operation(operation: &Operation, tenant: &str) -> Self {
        let selected = match operation {
            Operation::PublishRelease(value) => value.operation.as_ref().map(|op|json!({"family":"release","operationId":op.operation_id,"expectedGeneration":op.expected_generation.map(|v|v.to_string())})),
            Operation::ChangeReleaseLifecycle(value) => value.operation.as_ref().map(|op|json!({"family":"release","operationId":op.operation_id,"componentDigest":value.digest,"expectedGeneration":op.expected_generation.map(|v|v.to_string())})),
            Operation::RenewReleaseEvidence(value) => value.operation.as_ref().map(|op|json!({"family":"release","operationId":op.operation_id,"componentDigest":value.digest,"packageDigest":value.package_digest,"expectedGeneration":op.expected_generation.map(|v|v.to_string())})),
            Operation::ApplyDeployment(value) => value.operation.as_ref().map(|op|json!({"family":"deployment","operationId":op.operation_id,"deploymentId":value.deployment.as_ref().map(|v|&v.id),"expectedGeneration":value.expected_generation.map(|v|v.to_string()),"expectedStateVersion":op.expected_state_version.map(|v|v.to_string())})),
            Operation::DeleteDeployment(value) => value.operation.as_ref().map(|op|json!({"family":"deployment","operationId":op.operation_id,"deploymentId":value.id,"expectedGeneration":value.expected_generation.map(|v|v.to_string()),"expectedStateVersion":op.expected_state_version.map(|v|v.to_string())})),
            Operation::StartRollout(value) => value.operation.as_ref().map(|op|json!({"family":"rollout","operationId":op.operation_id,"rolloutId":value.id,"expectedRevision":op.expected_revision.map(|v|v.to_string())})),
            Operation::ChangeRollout(value) => value.operation.as_ref().map(|op|json!({"family":"rollout","operationId":op.operation_id,"rolloutId":value.id,"expectedRevision":op.expected_revision.map(|v|v.to_string()),"targetGeneration":match &value.command {Some(super::proto::change_rollout_request::Command::Rollback(v))=>Some(v.target_generation.to_string()),_=>None}})),
            _ => None,
        };
        let mut data = selected.unwrap_or(Value::Null);
        if data.is_object() {
            data["tenant"] = json!(tenant);
        }
        Self(data)
    }
    pub(crate) fn failure(&self, value: &mut Failure) {
        if !self.0.is_null() {
            value.data["recovery"] = self.0.clone();
        }
    }
    pub(crate) fn outcome(&self, value: &mut Outcome) {
        if !self.0.is_null() {
            value.data["recovery"] = self.0.clone();
        }
    }
}

pub(crate) fn audit_metadata(metadata: &MetadataMap) -> Result<Option<Value>, Failure> {
    let state = metadata.get("latent-audit-status");
    let sequence = metadata.get("latent-audit-attempt");
    let Some(state) = state else {
        if sequence.is_some() {
            return Err(super::invalid_response());
        }
        return Ok(None);
    };
    let state = state.to_str().map_err(|_| super::invalid_response())?;
    if !matches!(
        state,
        "durable" | "outcome-unknown" | "audit-unavailable" | "disabled"
    ) {
        return Err(super::invalid_response());
    }
    let sequence = sequence
        .map(|value| {
            let value = value.to_str().map_err(|_| super::invalid_response())?;
            let number = value
                .parse::<u64>()
                .map_err(|_| super::invalid_response())?;
            if number == 0 || number.to_string() != value {
                return Err(super::invalid_response());
            }
            Ok(number.to_string())
        })
        .transpose()?;
    if matches!(state, "durable" | "outcome-unknown") && sequence.is_none() {
        return Err(super::invalid_response());
    }
    Ok(Some(json!({"status":state,"attemptSequence":sequence})))
}
