mod status;

use super::{invalid_response, json, proto, Failure, Project, Tree, Value};

fn text(value: &String, maximum: usize, tree: &mut Tree) -> Result<(), Failure> {
    tree.text(value, maximum)?;
    if value.is_empty() || value.chars().any(char::is_whitespace) {
        return Err(invalid_response());
    }
    Ok(())
}

fn digest(value: &String, tree: &mut Tree) -> Result<(), Failure> {
    tree.text(value, 71)?;
    if !crate::management::canonical_digest(value) {
        return Err(invalid_response());
    }
    Ok(())
}

fn actor(value: Option<&proto::ReleaseActor>, tree: &mut Tree) -> Result<(), Failure> {
    let value = value.ok_or_else(invalid_response)?;
    text(&value.subject, 256, tree)?;
    value.validate(tree)
}

fn transition(action: i32, reason: i32, generation: u64) -> Result<(), Failure> {
    use proto::{ReleaseLifecycleAction as Action, ReleaseLifecycleReason as Reason};
    let valid = match (Action::try_from(action), Reason::try_from(reason)) {
        (Ok(Action::Publish), Ok(Reason::Admitted)) => generation == 0,
        (Ok(Action::RenewEvidence), Ok(Reason::EvidenceRenewed))
        | (
            Ok(Action::Revoke),
            Ok(Reason::OperatorRevocation | Reason::SecurityIncident | Reason::CorruptContent),
        )
        | (
            Ok(Action::Retire),
            Ok(Reason::OperatorRetirement | Reason::Superseded | Reason::EndOfSupport),
        ) => generation > 0,
        _ => false,
    };
    if valid {
        Ok(())
    } else {
        Err(invalid_response())
    }
}

impl Project for proto::PrepareWebPublicationResponse {
    fn validate(&self, tree: &mut Tree) -> Result<(), Failure> {
        tree.message::<Self>()?;
        self.publication
            .as_ref()
            .ok_or_else(invalid_response)?
            .validate(tree)?;
        digest(&self.component_digest, tree)?;
        if self.lifecycle_generation == 0 || !self.prepared {
            return Err(invalid_response());
        }
        Ok(())
    }

    fn project(self) -> Value {
        json!({
            "publication": self.publication.map(Project::project),
            "lifecycleGeneration": self.lifecycle_generation.to_string(),
            "componentDigest": self.component_digest,
            "prepared": self.prepared,
            "executionAuthorized": false,
        })
    }
}

impl Project for proto::WebOperationReceipt {
    fn validate(&self, tree: &mut Tree) -> Result<(), Failure> {
        tree.message::<Self>()?;
        self.publication
            .as_ref()
            .ok_or_else(invalid_response)?
            .validate(tree)?;
        text(&self.operation_id, 128, tree)?;
        digest(&self.request_digest, tree)?;
        actor(self.actor.as_ref(), tree)?;
        transition(self.action, self.reason, self.expected_generation)?;
        if self.format_version != 1
            || self.disposition != proto::ReleaseOperationDisposition::Committed as i32
            || self.expected_generation.checked_add(1) != Some(self.resulting_generation)
        {
            return Err(invalid_response());
        }
        Ok(())
    }

    fn project(self) -> Value {
        json!({
            "formatVersion": self.format_version,
            "publication": self.publication.map(Project::project),
            "operationId": self.operation_id,
            "requestDigest": self.request_digest,
            "actor": self.actor.map(Project::project),
            "action": proto::ReleaseLifecycleAction::try_from(self.action).expect("validated action").as_str_name(),
            "reason": proto::ReleaseLifecycleReason::try_from(self.reason).expect("validated reason").as_str_name(),
            "disposition": proto::ReleaseOperationDisposition::try_from(self.disposition).expect("validated disposition").as_str_name(),
            "expectedGeneration": self.expected_generation.to_string(),
            "resultingGeneration": self.resulting_generation.to_string(),
            "replayed": self.replayed,
        })
    }
}

impl Project for proto::WebMutationResponse {
    fn validate(&self, tree: &mut Tree) -> Result<(), Failure> {
        tree.message::<Self>()?;
        self.operation
            .as_ref()
            .ok_or_else(invalid_response)?
            .validate(tree)?;
        if let Some(ack) = &self.audit_ack {
            ack.validate(tree)?;
        }
        Ok(())
    }

    fn project(self) -> Value {
        json!({"operation": self.operation.map(Project::project), "auditAck": self.audit_ack.map(Project::project)})
    }
}

impl Project for proto::GetWebOperationResponse {
    fn validate(&self, tree: &mut Tree) -> Result<(), Failure> {
        tree.message::<Self>()?;
        text(&self.tenant, 512, tree)?;
        match proto::ReleaseOperationLookupDisposition::try_from(self.disposition) {
            Ok(proto::ReleaseOperationLookupDisposition::Found) => {
                let receipt = self.operation.as_ref().ok_or_else(invalid_response)?;
                receipt.validate(tree)?;
                if receipt
                    .publication
                    .as_ref()
                    .is_none_or(|reference| reference.tenant != self.tenant)
                {
                    return Err(invalid_response());
                }
            }
            Ok(
                proto::ReleaseOperationLookupDisposition::Unknown
                | proto::ReleaseOperationLookupDisposition::Uncertain,
            ) if self.operation.is_none() => {}
            _ => return Err(invalid_response()),
        }
        Ok(())
    }

    fn project(self) -> Value {
        json!({
            "tenant": self.tenant,
            "disposition": proto::ReleaseOperationLookupDisposition::try_from(self.disposition).expect("validated disposition").as_str_name(),
            "operation": self.operation.map(Project::project),
        })
    }
}
