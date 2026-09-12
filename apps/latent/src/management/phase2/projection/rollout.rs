//! Closed typed projection; all protobuf u64 fields remain decimal strings.
use super::{invalid_response, json, proto, Failure, Project, Tree, Value};

impl Project for proto::CanaryAssessment {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        if self.verdict == 0 || proto::CanaryVerdict::try_from(self.verdict).is_err() {
            return Err(invalid_response());
        }
        if self.reason == 0 || proto::CanaryDecisionReason::try_from(self.reason).is_err() {
            return Err(invalid_response());
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "verdict": json!(proto::CanaryVerdict::try_from(self.verdict).expect("validated enum").as_str_name()),
        "reason": json!(proto::CanaryDecisionReason::try_from(self.reason).expect("validated enum").as_str_name()),
        "selected": json!(self.selected.to_string()),
        "admittedTerminal": json!(self.admitted_terminal.to_string()),
        "successes": json!(self.successes.to_string()),
        "failures": json!(self.failures.to_string()),
        "slow": json!(self.slow.to_string()),
        })
    }
}

impl Project for proto::CanaryEvaluationReport {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        b.text(&self.rollout_id, 4096)?;
        b.text(&self.policy_digest, 4096)?;
        b.text(&self.candidate_revision, 4096)?;
        if let Some(value) = &self.observation {
            value.validate(b)?;
        }
        if let Some(value) = &self.assessment {
            value.validate(b)?;
        }
        b.sequence(&self.revisions, 64)?;
        for value in &self.revisions {
            value.validate(b)?;
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "rolloutId": json!(self.rollout_id),
        "revision": json!(self.revision.to_string()),
        "step": json!(self.step),
        "routeGeneration": json!(self.route_generation.to_string()),
        "policyDigest": json!(self.policy_digest),
        "windowEpoch": self.window_epoch.map(|value| json!(value.to_string())),
        "candidateRevision": json!(self.candidate_revision),
        "durationMillis": json!(self.duration_millis.to_string()),
        "observation": self.observation.map(Project::project),
        "assessment": self.assessment.map(Project::project),
        "starts": json!(self.starts.to_string()),
        "selected": json!(self.selected.to_string()),
        "admitted": json!(self.admitted.to_string()),
        "terminal": json!(self.terminal.to_string()),
        "live": json!(self.live.to_string()),
        "revisions": self.revisions.into_iter().map(Project::project).collect::<Vec<_>>(),
        "unattributed": json!(self.unattributed.to_string()),
        "abandoned": json!(self.abandoned.to_string()),
        })
    }
}

impl Project for proto::CanaryRevisionReport {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        b.text(&self.revision, 4096)?;
        b.text(&self.component_digest, 4096)?;
        if let Some(value) = &self.package_digest {
            b.text(value, 4096)?;
        }
        if let Some(value) = &self.counters {
            value.validate(b)?;
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "revision": json!(self.revision),
        "componentDigest": json!(self.component_digest),
        "packageDigest": self.package_digest.map(|value| json!(value)),
        "counters": self.counters.map(Project::project),
        })
    }
}

impl Project for proto::ChangeRolloutResponse {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        if let Some(value) = &self.receipt {
            value.validate(b)?;
        }
        if let Some(value) = &self.audit_ack {
            value.validate(b)?;
        }
        if self.durability == 0 || proto::RolloutDurability::try_from(self.durability).is_err() {
            return Err(invalid_response());
        }
        if let Some(value) = &self.observation {
            value.validate(b)?;
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "receipt": self.receipt.map(Project::project),
        "auditAck": self.audit_ack.map(Project::project),
        "replayed": json!(self.replayed),
        "durability": json!(proto::RolloutDurability::try_from(self.durability).expect("validated enum").as_str_name()),
        "observation": self.observation.map(Project::project),
        })
    }
}

impl Project for proto::EvaluateRolloutResponse {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        if let Some(value) = &self.report {
            value.validate(b)?;
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "report": self.report.map(Project::project),
        })
    }
}

impl Project for proto::GetRolloutOperationResponse {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        if self.disposition == 0
            || proto::RolloutOperationLookupDisposition::try_from(self.disposition).is_err()
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
        "disposition": json!(proto::RolloutOperationLookupDisposition::try_from(self.disposition).expect("validated enum").as_str_name()),
        "receipt": self.receipt.map(Project::project),
        })
    }
}

impl Project for proto::GetRolloutResponse {
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

impl Project for proto::ListRolloutsResponse {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        b.sequence(&self.rollouts, 128)?;
        for value in &self.rollouts {
            value.validate(b)?;
        }
        if let Some(value) = &self.page {
            value.validate(b)?;
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "rollouts": self.rollouts.into_iter().map(Project::project).collect::<Vec<_>>(),
        "page": self.page.map(Project::project),
        "stateVersion": json!(self.state_version.to_string()),
        })
    }
}

impl Project for proto::RolloutCanaryCounters {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        b.sequence(&self.latency_buckets, 9)?;
        if self.latency_buckets.len() != 9 {
            return Err(invalid_response());
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "selected": json!(self.selected.to_string()),
        "admitted": json!(self.admitted.to_string()),
        "admittedTerminal": json!(self.admitted_terminal.to_string()),
        "success": json!(self.success.to_string()),
        "domainError": json!(self.domain_error.to_string()),
        "platformError": json!(self.platform_error.to_string()),
        "deadlineExceeded": json!(self.deadline_exceeded.to_string()),
        "cancelled": json!(self.cancelled.to_string()),
        "latencyBuckets": self.latency_buckets.into_iter().map(|value| json!(value.to_string())).collect::<Vec<_>>(),
        })
    }
}

impl Project for proto::RolloutCanaryDecision {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        b.text(&self.policy_digest, 4096)?;
        b.text(&self.control_digest, 4096)?;
        b.text(&self.evidence_digest, 4096)?;
        if let Some(value) = &self.candidate {
            value.validate(b)?;
        }
        if let Some(value) = &self.baseline {
            value.validate(b)?;
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "formatVersion": json!(self.format_version),
        "policyDigest": json!(self.policy_digest),
        "controlDigest": json!(self.control_digest),
        "evidenceDigest": json!(self.evidence_digest),
        "windowEpoch": json!(self.window_epoch.to_string()),
        "observedMillis": json!(self.observed_millis.to_string()),
        "candidate": self.candidate.map(Project::project),
        "baseline": self.baseline.map(Project::project),
        })
    }
}

impl Project for proto::RolloutCanaryPolicy {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "formatVersion": json!(self.format_version),
        "observationMillis": json!(self.observation_millis.to_string()),
        "minimumCandidateSamples": json!(self.minimum_candidate_samples.to_string()),
        "maximumFailureBasisPoints": self.maximum_failure_basis_points.map(|value| json!(value)),
        "latencyThresholdMicros": json!(self.latency_threshold_micros.to_string()),
        "maximumSlowBasisPoints": self.maximum_slow_basis_points.map(|value| json!(value)),
        })
    }
}

impl Project for proto::RolloutObjectVersion {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        b.text(&self.deployment_id, 4096)?;
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "deploymentId": json!(self.deployment_id),
        "generation": json!(self.generation.to_string()),
        })
    }
}

impl Project for proto::RolloutObservation {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        if self.state == 0 || proto::RolloutObservationState::try_from(self.state).is_err() {
            return Err(invalid_response());
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "state": json!(proto::RolloutObservationState::try_from(self.state).expect("validated enum").as_str_name()),
        "windowEpoch": self.window_epoch.map(|value| json!(value.to_string())),
        })
    }
}

impl Project for proto::RolloutOperationReceipt {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        b.text(&self.rollout_id, 4096)?;
        b.text(&self.tenant, 4096)?;
        b.text(&self.operation_id, 4096)?;
        b.text(&self.request_digest, 4096)?;
        if let Some(value) = &self.actor {
            value.validate(b)?;
        }
        if self.action == 0 || proto::RolloutAction::try_from(self.action).is_err() {
            return Err(invalid_response());
        }
        if self.outcome == 0 || proto::RolloutOperationOutcome::try_from(self.outcome).is_err() {
            return Err(invalid_response());
        }
        if self.reason == 0 || proto::RolloutReason::try_from(self.reason).is_err() {
            return Err(invalid_response());
        }
        if self.state == 0 || proto::RolloutState::try_from(self.state).is_err() {
            return Err(invalid_response());
        }
        b.text(&self.plan_digest, 4096)?;
        b.text(&self.receipt_digest, 4096)?;
        if let Some(value) = &self.canary_decision {
            value.validate(b)?;
        }
        if let Some(value) = &self.rollback_target {
            value.validate(b)?;
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "rolloutId": json!(self.rollout_id),
        "tenant": json!(self.tenant),
        "operationId": json!(self.operation_id),
        "requestDigest": json!(self.request_digest),
        "actor": self.actor.map(Project::project),
        "action": json!(proto::RolloutAction::try_from(self.action).expect("validated enum").as_str_name()),
        "expectedRevision": json!(self.expected_revision.to_string()),
        "revision": json!(self.revision.to_string()),
        "outcome": json!(proto::RolloutOperationOutcome::try_from(self.outcome).expect("validated enum").as_str_name()),
        "reason": json!(proto::RolloutReason::try_from(self.reason).expect("validated enum").as_str_name()),
        "stateVersion": json!(self.state_version.to_string()),
        "routeGeneration": json!(self.route_generation.to_string()),
        "state": json!(proto::RolloutState::try_from(self.state).expect("validated enum").as_str_name()),
        "step": json!(self.step),
        "planDigest": json!(self.plan_digest),
        "completedAtUnixMillis": json!(self.completed_at_unix_millis.to_string()),
        "receiptDigest": json!(self.receipt_digest),
        "canaryDecision": self.canary_decision.map(Project::project),
        "rollbackTarget": self.rollback_target.map(Project::project),
        })
    }
}

impl Project for proto::RolloutRelease {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        b.text(&self.deployment_id, 4096)?;
        b.text(&self.component_digest, 4096)?;
        if let Some(value) = &self.package_digest {
            b.text(value, 4096)?;
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "deploymentId": json!(self.deployment_id),
        "componentDigest": json!(self.component_digest),
        "packageDigest": self.package_digest.map(|value| json!(value)),
        })
    }
}

impl Project for proto::RolloutRollbackTarget {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        b.text(&self.manifest_digest, 4096)?;
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "formatVersion": json!(self.format_version),
        "historicalRouteGeneration": json!(self.historical_route_generation.to_string()),
        "manifestDigest": json!(self.manifest_digest),
        })
    }
}

impl Project for proto::RolloutStatus {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        b.text(&self.id, 4096)?;
        b.text(&self.tenant, 4096)?;
        b.text(&self.service, 4096)?;
        if self.state == 0 || proto::RolloutState::try_from(self.state).is_err() {
            return Err(invalid_response());
        }
        if self.reason == 0 || proto::RolloutReason::try_from(self.reason).is_err() {
            return Err(invalid_response());
        }
        b.sequence(&self.candidate_weights, 64)?;
        if let Some(value) = &self.base {
            value.validate(b)?;
        }
        if let Some(value) = &self.candidate {
            value.validate(b)?;
        }
        b.sequence(&self.objects, 64)?;
        for value in &self.objects {
            value.validate(b)?;
        }
        b.text(&self.plan_digest, 4096)?;
        if let Some(value) = &self.canary_policy {
            value.validate(b)?;
        }
        if let Some(value) = &self.rollback_target {
            value.validate(b)?;
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "id": json!(self.id),
        "tenant": json!(self.tenant),
        "service": json!(self.service),
        "revision": json!(self.revision.to_string()),
        "state": json!(proto::RolloutState::try_from(self.state).expect("validated enum").as_str_name()),
        "reason": json!(proto::RolloutReason::try_from(self.reason).expect("validated enum").as_str_name()),
        "currentStep": json!(self.current_step),
        "candidateWeights": self.candidate_weights.into_iter().map(|value| json!(value)).collect::<Vec<_>>(),
        "base": self.base.map(Project::project),
        "candidate": self.candidate.map(Project::project),
        "objects": self.objects.into_iter().map(Project::project).collect::<Vec<_>>(),
        "routeGeneration": json!(self.route_generation.to_string()),
        "stateVersion": json!(self.state_version.to_string()),
        "planDigest": json!(self.plan_digest),
        "previousRouteGeneration": json!(self.previous_route_generation.to_string()),
        "createdAtUnixMillis": json!(self.created_at_unix_millis.to_string()),
        "updatedAtUnixMillis": json!(self.updated_at_unix_millis.to_string()),
        "retainedOperationFloor": json!(self.retained_operation_floor.to_string()),
        "canaryPolicy": self.canary_policy.map(Project::project),
        "rollbackTarget": self.rollback_target.map(Project::project),
        })
    }
}

impl Project for proto::StartRolloutResponse {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        if let Some(value) = &self.receipt {
            value.validate(b)?;
        }
        if let Some(value) = &self.audit_ack {
            value.validate(b)?;
        }
        if self.durability == 0 || proto::RolloutDurability::try_from(self.durability).is_err() {
            return Err(invalid_response());
        }
        if let Some(value) = &self.observation {
            value.validate(b)?;
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({
        "receipt": self.receipt.map(Project::project),
        "auditAck": self.audit_ack.map(Project::project),
        "replayed": json!(self.replayed),
        "durability": json!(proto::RolloutDurability::try_from(self.durability).expect("validated enum").as_str_name()),
        "observation": self.observation.map(Project::project),
        })
    }
}
