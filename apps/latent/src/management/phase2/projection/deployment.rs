//! Closed typed projection; all protobuf u64 fields remain decimal strings.
use super::{invalid_response, json, proto, Failure, Project, Tree, Value};

impl Project for proto::DeploymentOperationReceipt {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        b.text(&self.tenant, 4096)?;
        if let Some(value) = &self.actor {
            value.validate(b)?;
        }
        b.text(&self.operation_id, 4096)?;
        if self.action == 0 || proto::DeploymentOperationAction::try_from(self.action).is_err() {
            return Err(invalid_response());
        }
        b.text(&self.deployment_id, 4096)?;
        b.text(&self.request_digest, 4096)?;
        b.text(&self.manifest_digest, 4096)?;
        b.text(&self.component_digest, 4096)?;
        b.text(&self.receipt_digest, 4096)?;
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "formatVersion": json!(self.format_version),
        "tenant": json!(self.tenant),
        "actor": self.actor.map(Project::project),
        "operationId": json!(self.operation_id),
        "action": json!(proto::DeploymentOperationAction::try_from(self.action).expect("validated enum").as_str_name()),
        "deploymentId": json!(self.deployment_id),
        "requestDigest": json!(self.request_digest),
        "expectedStateVersion": json!(self.expected_state_version.to_string()),
        "expectedGeneration": json!(self.expected_generation.to_string()),
        "objectGeneration": json!(self.object_generation.to_string()),
        "routeGeneration": json!(self.route_generation.to_string()),
        "stateVersion": json!(self.state_version.to_string()),
        "manifestDigest": json!(self.manifest_digest),
        "componentDigest": json!(self.component_digest),
        "completedAtUnixMillis": json!(self.completed_at_unix_millis.to_string()),
        "receiptDigest": json!(self.receipt_digest),
        })
    }
}

impl Project for proto::GetDeploymentOperationResponse {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        if self.disposition == 0
            || proto::DeploymentOperationLookupDisposition::try_from(self.disposition).is_err()
        {
            return Err(invalid_response());
        }
        if let Some(value) = &self.receipt {
            value.validate(b)?;
        }
        if let Some(value) = &self.durability {
            if *value == 0 || proto::DeploymentDurability::try_from(*value).is_err() {
                return Err(invalid_response());
            }
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "disposition": json!(proto::DeploymentOperationLookupDisposition::try_from(self.disposition).expect("validated enum").as_str_name()),
        "receipt": self.receipt.map(Project::project),
        "durability": self.durability.map(|value| json!(proto::DeploymentDurability::try_from(value).expect("validated enum").as_str_name())),
        "retainedFloor": json!(self.retained_floor.to_string()),
        "highWatermark": json!(self.high_watermark.to_string()),
        })
    }
}
