//! Closed typed projection; all protobuf u64 fields remain decimal strings.
use super::{invalid_response, json, proto, Failure, Project, Tree, Value};

impl Project for proto::AuditActorIdentity {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        if self.kind == 0 || proto::AuditActorKind::try_from(self.kind).is_err() {
            return Err(invalid_response());
        }
        b.text(&self.subject, 4096)?;
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "kind": json!(proto::AuditActorKind::try_from(self.kind).expect("validated enum").as_str_name()),
        "subject": json!(self.subject),
        })
    }
}

impl Project for proto::AuditCanaryDecision {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        if self.verdict == 0 || proto::AuditCanaryVerdict::try_from(self.verdict).is_err() {
            return Err(invalid_response());
        }
        if self.reason == 0 || proto::AuditCanaryReason::try_from(self.reason).is_err() {
            return Err(invalid_response());
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "verdict": json!(proto::AuditCanaryVerdict::try_from(self.verdict).expect("validated enum").as_str_name()),
        "reason": json!(proto::AuditCanaryReason::try_from(self.reason).expect("validated enum").as_str_name()),
        "observationMillis": json!(self.observation_millis.to_string()),
        "minimumCandidateSamples": json!(self.minimum_candidate_samples.to_string()),
        "maximumFailureBasisPoints": json!(self.maximum_failure_basis_points),
        "latencyThresholdMicros": json!(self.latency_threshold_micros.to_string()),
        "maximumSlowBasisPoints": json!(self.maximum_slow_basis_points),
        "selected": json!(self.selected.to_string()),
        "admittedTerminal": json!(self.admitted_terminal.to_string()),
        "successes": json!(self.successes.to_string()),
        "failures": json!(self.failures.to_string()),
        "slow": json!(self.slow.to_string()),
        })
    }
}

impl Project for proto::AuditIdentities {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        if let Some(value) = &self.package_digest {
            b.text(value, 4096)?;
        }
        if let Some(value) = &self.component_digest {
            b.text(value, 4096)?;
        }
        b.sequence(&self.policies, 64)?;
        for value in &self.policies {
            value.validate(b)?;
        }
        if let Some(value) = &self.rollout {
            b.text(value, 4096)?;
        }
        if let Some(value) = &self.revision {
            b.text(value, 4096)?;
        }
        if let Some(value) = &self.received_manifest_digest {
            b.text(value, 4096)?;
        }
        if let Some(value) = &self.evidence_revision_digest {
            b.text(value, 4096)?;
        }
        if let Some(value) = &self.deployment {
            b.text(value, 4096)?;
        }
        if let Some(value) = &self.canary_evidence_digest {
            b.text(value, 4096)?;
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "packageDigest": self.package_digest.map(|value| json!(value)),
        "componentDigest": self.component_digest.map(|value| json!(value)),
        "policies": self.policies.into_iter().map(Project::project).collect::<Vec<_>>(),
        "rollout": self.rollout.map(|value| json!(value)),
        "revision": self.revision.map(|value| json!(value)),
        "routeGeneration": self.route_generation.map(|value| json!(value.to_string())),
        "lifecycleGeneration": self.lifecycle_generation.map(|value| json!(value.to_string())),
        "receivedManifestDigest": self.received_manifest_digest.map(|value| json!(value)),
        "evidenceRevisionDigest": self.evidence_revision_digest.map(|value| json!(value)),
        "deployment": self.deployment.map(|value| json!(value)),
        "deploymentGeneration": self.deployment_generation.map(|value| json!(value.to_string())),
        "rolloutRevision": self.rollout_revision.map(|value| json!(value.to_string())),
        "rolloutStep": self.rollout_step.map(|value| json!(value)),
        "stateVersion": self.state_version.map(|value| json!(value.to_string())),
        "canaryWindowEpoch": self.canary_window_epoch.map(|value| json!(value.to_string())),
        "canaryEvidenceDigest": self.canary_evidence_digest.map(|value| json!(value)),
        "rollbackTargetGeneration": self.rollback_target_generation.map(|value| json!(value.to_string())),
        })
    }
}

impl Project for proto::AuditPolicyIdentity {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        if self.role == 0 || proto::AuditPolicyRole::try_from(self.role).is_err() {
            return Err(invalid_response());
        }
        b.text(&self.scope, 4096)?;
        b.text(&self.digest, 4096)?;
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "role": json!(proto::AuditPolicyRole::try_from(self.role).expect("validated enum").as_str_name()),
        "scope": json!(self.scope),
        "generation": json!(self.generation.to_string()),
        "digest": json!(self.digest),
        })
    }
}

impl Project for proto::AuditQueryCoverage {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        b.text(&self.epoch, 4096)?;
        if self.stop == 0 || proto::AuditPageStop::try_from(self.stop).is_err() {
            return Err(invalid_response());
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "epoch": json!(self.epoch),
        "retainedFloor": json!(self.retained_floor.to_string()),
        "highWatermark": json!(self.high_watermark.to_string()),
        "scanned": json!(self.scanned.to_string()),
        "stop": json!(proto::AuditPageStop::try_from(self.stop).expect("validated enum").as_str_name()),
        "droppedObservations": json!(self.dropped_observations.to_string()),
        "unknownOutcomes": json!(self.unknown_outcomes.to_string()),
        "previousSessionLossUnknown": json!(self.previous_session_loss_unknown),
        })
    }
}

impl Project for proto::AuditQueryScope {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        if self.kind == 0 || proto::AuditScopeKind::try_from(self.kind).is_err() {
            return Err(invalid_response());
        }
        if let Some(value) = &self.tenant {
            b.text(value, 4096)?;
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "kind": json!(proto::AuditScopeKind::try_from(self.kind).expect("validated enum").as_str_name()),
        "tenant": self.tenant.map(|value| json!(value)),
        })
    }
}

impl Project for proto::Phase2AuditAttempt {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        b.text(&self.operation_id, 4096)?;
        b.text(&self.request_digest, 4096)?;
        if self.action == 0 || proto::AuditControlAction::try_from(self.action).is_err() {
            return Err(invalid_response());
        }
        if let Some(value) = &self.identities {
            value.validate(b)?;
        }
        if let Some(value) = &self.preview_receipt_digest {
            b.text(value, 4096)?;
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "operationId": json!(self.operation_id),
        "requestDigest": json!(self.request_digest),
        "action": json!(proto::AuditControlAction::try_from(self.action).expect("validated enum").as_str_name()),
        "identities": self.identities.map(Project::project),
        "expectedGeneration": self.expected_generation.map(|value| json!(value.to_string())),
        "occurredAtUnixMillis": json!(self.occurred_at_unix_millis.to_string()),
        "replay": json!(self.replay),
        "expectedDeploymentGeneration": self.expected_deployment_generation.map(|value| json!(value.to_string())),
        "previewReceiptDigest": self.preview_receipt_digest.map(|value| json!(value)),
        "expectedRolloutRevision": self.expected_rollout_revision.map(|value| json!(value.to_string())),
        "expectedRollbackTargetGeneration": self.expected_rollback_target_generation.map(|value| json!(value.to_string())),
        "expectedStateVersion": self.expected_state_version.map(|value| json!(value.to_string())),
        })
    }
}

impl Project for proto::Phase2AuditObservation {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        if self.kind == 0 || proto::Phase2AuditEventKind::try_from(self.kind).is_err() {
            return Err(invalid_response());
        }
        if self.outcome == 0 || proto::AuditObservationOutcome::try_from(self.outcome).is_err() {
            return Err(invalid_response());
        }
        if let Some(value) = &self.identities {
            value.validate(b)?;
        }
        b.text(&self.reason, 4096)?;
        if let Some(value) = &self.cache_kind {
            if *value == 0 || proto::AuditCacheKind::try_from(*value).is_err() {
                return Err(invalid_response());
            }
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "kind": json!(proto::Phase2AuditEventKind::try_from(self.kind).expect("validated enum").as_str_name()),
        "outcome": json!(proto::AuditObservationOutcome::try_from(self.outcome).expect("validated enum").as_str_name()),
        "identities": self.identities.map(Project::project),
        "reason": json!(self.reason),
        "cacheKind": self.cache_kind.map(|value| json!(proto::AuditCacheKind::try_from(value).expect("validated enum").as_str_name())),
        "occurredAtUnixMillis": json!(self.occurred_at_unix_millis.to_string()),
        })
    }
}

impl Project for proto::Phase2AuditOutcome {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        if self.result == 0 || proto::AuditOperationResult::try_from(self.result).is_err() {
            return Err(invalid_response());
        }
        b.text(&self.reason, 4096)?;
        if let Some(value) = &self.receipt_digest {
            b.text(value, 4096)?;
        }
        if let Some(value) = &self.identities {
            value.validate(b)?;
        }
        if let Some(value) = &self.canary_decision {
            value.validate(b)?;
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "attemptSequence": json!(self.attempt_sequence.to_string()),
        "result": json!(proto::AuditOperationResult::try_from(self.result).expect("validated enum").as_str_name()),
        "reason": json!(self.reason),
        "receiptDigest": self.receipt_digest.map(|value| json!(value)),
        "identities": self.identities.map(Project::project),
        "replay": json!(self.replay),
        "occurredAtUnixMillis": json!(self.occurred_at_unix_millis.to_string()),
        "canaryDecision": self.canary_decision.map(Project::project),
        })
    }
}

impl Project for proto::Phase2AuditRecord {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        b.text(&self.epoch, 4096)?;
        b.text(&self.previous_digest, 4096)?;
        if let Some(value) = &self.scope {
            value.validate(b)?;
        }
        if let Some(value) = &self.actor {
            value.validate(b)?;
        }
        match self.data.as_ref().ok_or_else(invalid_response)? {
            proto::phase2_audit_record::Data::Observation(value) => value.validate(b)?,
            proto::phase2_audit_record::Data::Attempt(value) => value.validate(b)?,
            proto::phase2_audit_record::Data::Outcome(value) => value.validate(b)?,
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "formatVersion": json!(self.format_version),
        "epoch": json!(self.epoch),
        "sequence": json!(self.sequence.to_string()),
        "previousDigest": json!(self.previous_digest),
        "acceptedAtUnixMillis": json!(self.accepted_at_unix_millis.to_string()),
        "scope": self.scope.map(Project::project),
        "actor": self.actor.map(Project::project),
        "data": match self.data.expect("validated data") {
        proto::phase2_audit_record::Data::Observation(value) => json!({"observation": value.project()}),
        proto::phase2_audit_record::Data::Attempt(value) => json!({"attempt": value.project()}),
        proto::phase2_audit_record::Data::Outcome(value) => json!({"outcome": value.project()}),
        },
        })
    }
}

impl Project for proto::QueryPhase2AuditResponse {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        b.sequence(&self.records, 128)?;
        for value in &self.records {
            value.validate(b)?;
        }
        if let Some(value) = &self.page {
            value.validate(b)?;
        }
        if let Some(value) = &self.coverage {
            value.validate(b)?;
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "records": self.records.into_iter().map(Project::project).collect::<Vec<_>>(),
        "page": self.page.map(Project::project),
        "coverage": self.coverage.map(Project::project),
        })
    }
}
