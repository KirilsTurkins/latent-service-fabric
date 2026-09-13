//! Closed typed projection; all protobuf u64 fields remain decimal strings.
use super::{invalid_response, json, proto, Failure, Project, Tree, Value};

impl Project for proto::ChangeReleaseLifecycleResponse {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        if let Some(value) = &self.operation {
            value.validate(b)?;
        }
        if let Some(value) = &self.audit_ack {
            value.validate(b)?;
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "operation": self.operation.map(Project::project),
        "auditAck": self.audit_ack.map(Project::project),
        })
    }
}

impl Project for proto::GetReleaseLifecycleResponse {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        if let Some(value) = &self.status {
            value.validate(b)?;
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "status": self.status.map(Project::project),
        })
    }
}

impl Project for proto::GetReleaseOperationResponse {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        if self.lookup == 0
            || proto::ReleaseOperationLookupDisposition::try_from(self.lookup).is_err()
        {
            return Err(invalid_response());
        }
        if let Some(value) = &self.receipt {
            value.validate(b)?;
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "lookup": json!(proto::ReleaseOperationLookupDisposition::try_from(self.lookup).expect("validated enum").as_str_name()),
        "receipt": self.receipt.map(Project::project),
        })
    }
}

impl Project for proto::ReleaseActor {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        b.text(&self.subject, 4096)?;
        if self.kind == 0 || proto::ReleaseActorKind::try_from(self.kind).is_err() {
            return Err(invalid_response());
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "subject": json!(self.subject),
        "kind": json!(proto::ReleaseActorKind::try_from(self.kind).expect("validated enum").as_str_name()),
        })
    }
}

impl Project for proto::ReleaseLifecycleRecord {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        b.text(&self.tenant, 4096)?;
        b.text(&self.component_digest, 4096)?;
        if let Some(value) = &self.package_digest {
            b.text(value, 4096)?;
        }
        if self.state == 0 || proto::ReleaseLifecycleState::try_from(self.state).is_err() {
            return Err(invalid_response());
        }
        if let Some(value) = &self.actor {
            value.validate(b)?;
        }
        if self.reason == 0 || proto::ReleaseLifecycleReason::try_from(self.reason).is_err() {
            return Err(invalid_response());
        }
        b.text(&self.operation_id, 4096)?;
        if let Some(value) = &self.policy {
            value.validate(b)?;
        }
        if let Some(value) = &self.evidence_revision_digest {
            b.text(value, 4096)?;
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "tenant": json!(self.tenant),
        "componentDigest": json!(self.component_digest),
        "packageDigest": self.package_digest.map(|value| json!(value)),
        "state": json!(proto::ReleaseLifecycleState::try_from(self.state).expect("validated enum").as_str_name()),
        "generation": json!(self.generation.to_string()),
        "actor": self.actor.map(Project::project),
        "reason": json!(proto::ReleaseLifecycleReason::try_from(self.reason).expect("validated enum").as_str_name()),
        "operationId": json!(self.operation_id),
        "policy": self.policy.map(Project::project),
        "observedAtUnixMillis": self.observed_at_unix_millis.map(|value| json!(value.to_string())),
        "evidenceRevisionDigest": self.evidence_revision_digest.map(|value| json!(value)),
        })
    }
}

impl Project for proto::ReleaseLifecycleStatus {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        if let Some(value) = &self.record {
            value.validate(b)?;
        }
        if self.eligibility == 0
            || proto::ReleaseLiveEligibility::try_from(self.eligibility).is_err()
        {
            return Err(invalid_response());
        }
        if self.eligibility_reason == 0
            || proto::ReleaseEligibilityReason::try_from(self.eligibility_reason).is_err()
        {
            return Err(invalid_response());
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "record": self.record.map(Project::project),
        "eligibility": json!(proto::ReleaseLiveEligibility::try_from(self.eligibility).expect("validated enum").as_str_name()),
        "eligibilityReason": json!(proto::ReleaseEligibilityReason::try_from(self.eligibility_reason).expect("validated enum").as_str_name()),
        })
    }
}

impl Project for proto::ReleaseOperationReceipt {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        b.text(&self.operation_id, 4096)?;
        b.text(&self.request_digest, 4096)?;
        b.text(&self.tenant, 4096)?;
        if let Some(value) = &self.actor {
            value.validate(b)?;
        }
        if self.action == 0 || proto::ReleaseLifecycleAction::try_from(self.action).is_err() {
            return Err(invalid_response());
        }
        if self.disposition == 0
            || proto::ReleaseOperationDisposition::try_from(self.disposition).is_err()
        {
            return Err(invalid_response());
        }
        if self.reason == 0 || proto::ReleaseLifecycleReason::try_from(self.reason).is_err() {
            return Err(invalid_response());
        }
        if let Some(value) = &self.component_digest {
            b.text(value, 4096)?;
        }
        if let Some(value) = &self.package_manifest_digest {
            b.text(value, 4096)?;
        }
        if let Some(value) = &self.record {
            value.validate(b)?;
        }
        if let Some(value) = &self.policy {
            value.validate(b)?;
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "operationId": json!(self.operation_id),
        "requestDigest": json!(self.request_digest),
        "tenant": json!(self.tenant),
        "actor": self.actor.map(Project::project),
        "action": json!(proto::ReleaseLifecycleAction::try_from(self.action).expect("validated enum").as_str_name()),
        "disposition": json!(proto::ReleaseOperationDisposition::try_from(self.disposition).expect("validated enum").as_str_name()),
        "reason": json!(proto::ReleaseLifecycleReason::try_from(self.reason).expect("validated enum").as_str_name()),
        "componentDigest": self.component_digest.map(|value| json!(value)),
        "packageManifestDigest": self.package_manifest_digest.map(|value| json!(value)),
        "expectedGeneration": self.expected_generation.map(|value| json!(value.to_string())),
        "record": self.record.map(Project::project),
        "policy": self.policy.map(Project::project),
        "observedAtUnixMillis": self.observed_at_unix_millis.map(|value| json!(value.to_string())),
        })
    }
}

impl Project for proto::ReleasePolicyIdentity {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        b.text(&self.scope, 4096)?;
        b.text(&self.digest, 4096)?;
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "scope": json!(self.scope),
        "generation": json!(self.generation.to_string()),
        "digest": json!(self.digest),
        })
    }
}

impl Project for proto::RenewReleaseEvidenceResponse {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        if let Some(value) = &self.operation {
            value.validate(b)?;
        }
        if let Some(value) = &self.audit_ack {
            value.validate(b)?;
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "operation": self.operation.map(Project::project),
        "auditAck": self.audit_ack.map(Project::project),
        })
    }
}
