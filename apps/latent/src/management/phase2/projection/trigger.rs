use super::{invalid_response, json, proto, Failure, Project, Tree, Value};
use crate::management::canonical_digest;

impl Project for proto::TriggerOperationReceipt {
    fn validate(&self, tree: &mut Tree) -> Result<(), Failure> {
        tree.message::<Self>()?;
        for value in [
            &self.tenant,
            &self.operation_id,
            &self.trigger_id,
            &self.deployment_id,
        ] {
            tree.text(value, 128)?;
            if value.is_empty() {
                return Err(invalid_response());
            }
        }
        for value in [
            &self.request_digest,
            &self.manifest_digest,
            &self.component_digest,
            &self.receipt_digest,
        ] {
            tree.text(value, 71)?;
            if !canonical_digest(value) {
                return Err(invalid_response());
            }
        }
        tree.text(&self.revision, 128)?;
        let actor = self.actor.as_ref().ok_or_else(invalid_response)?;
        actor.validate(tree)?;
        let publication = self.publication.as_ref().ok_or_else(invalid_response)?;
        publication.validate(tree)?;
        if self.format_version != 1
            || publication.tenant != self.tenant
            || self.expected_generation.checked_add(1) != Some(self.object_generation)
            || self.expected_state_version.checked_add(1) != Some(self.state_version)
            || self.route_generation == 0
            || self.deployment_generation == 0
            || !self
                .revision
                .strip_prefix("revision-v1:")
                .is_some_and(canonical_digest)
            || !matches!(
                proto::TriggerOperationAction::try_from(self.action),
                Ok(proto::TriggerOperationAction::Apply | proto::TriggerOperationAction::Delete)
            )
        {
            return Err(invalid_response());
        }
        Ok(())
    }

    fn project(self) -> Value {
        json!({"formatVersion":self.format_version,"tenant":self.tenant,
            "actor":self.actor.map(Project::project),"operationId":self.operation_id,
            "action":proto::TriggerOperationAction::try_from(self.action).expect("validated action").as_str_name(),
            "triggerId":self.trigger_id,"requestDigest":self.request_digest,
            "expectedStateVersion":self.expected_state_version.to_string(),
            "expectedGeneration":self.expected_generation.to_string(),
            "objectGeneration":self.object_generation.to_string(),"stateVersion":self.state_version.to_string(),
            "routeGeneration":self.route_generation.to_string(),"manifestDigest":self.manifest_digest,
            "publication":self.publication.map(Project::project),"componentDigest":self.component_digest,
            "deploymentId":self.deployment_id,"deploymentGeneration":self.deployment_generation.to_string(),
            "revision":self.revision,"completedAtUnixMillis":self.completed_at_unix_millis.to_string(),
            "receiptDigest":self.receipt_digest})
    }
}
