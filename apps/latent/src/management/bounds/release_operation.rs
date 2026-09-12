//! Bound additive receipts even while the full lifecycle CLI remains separate.
use super::{invalid_response, proto, Bounds, Check, Failure};

impl Check for proto::ReleaseActor {
    fn check(&self, b: &mut Bounds) -> Result<(), Failure> {
        b.id(&self.subject)?;
        if self.kind == 0 || proto::ReleaseActorKind::try_from(self.kind).is_err() {
            return Err(invalid_response());
        }
        Ok(())
    }
}
impl Check for proto::ReleasePolicyIdentity {
    fn check(&self, b: &mut Bounds) -> Result<(), Failure> {
        b.id(&self.scope)?;
        b.digest(&self.digest)?;
        if self.generation == 0 {
            return Err(invalid_response());
        }
        Ok(())
    }
}
impl Check for proto::ReleaseLifecycleRecord {
    fn check(&self, b: &mut Bounds) -> Result<(), Failure> {
        b.id(&self.tenant)?;
        b.digest(&self.component_digest)?;
        operation_id(&self.operation_id, b)?;
        optional_digest(self.package_digest.as_deref(), b)?;
        optional_digest(self.evidence_revision_digest.as_deref(), b)?;
        self.actor.as_ref().ok_or_else(invalid_response)?.check(b)?;
        if let Some(policy) = &self.policy {
            policy.check(b)?;
        }
        if self.generation == 0
            || self.state == 0
            || proto::ReleaseLifecycleState::try_from(self.state).is_err()
            || self.reason == 0
            || proto::ReleaseLifecycleReason::try_from(self.reason).is_err()
        {
            return Err(invalid_response());
        }
        Ok(())
    }
}
impl Check for proto::ReleaseOperationReceipt {
    fn check(&self, b: &mut Bounds) -> Result<(), Failure> {
        operation_id(&self.operation_id, b)?;
        b.digest(&self.request_digest)?;
        b.id(&self.tenant)?;
        self.actor.as_ref().ok_or_else(invalid_response)?.check(b)?;
        optional_digest(self.component_digest.as_deref(), b)?;
        optional_digest(self.package_manifest_digest.as_deref(), b)?;
        if let Some(policy) = &self.policy {
            policy.check(b)?;
        }
        if let Some(record) = &self.record {
            record.check(b)?;
            if record.tenant != self.tenant
                || self.component_digest.as_deref() != Some(&record.component_digest)
            {
                return Err(invalid_response());
            }
        }
        if self.action == 0
            || proto::ReleaseLifecycleAction::try_from(self.action).is_err()
            || self.disposition == 0
            || proto::ReleaseOperationDisposition::try_from(self.disposition).is_err()
            || self.reason == 0
            || proto::ReleaseLifecycleReason::try_from(self.reason).is_err()
            || (self.disposition == proto::ReleaseOperationDisposition::Committed as i32
                && self.record.is_none())
        {
            return Err(invalid_response());
        }
        Ok(())
    }
}
fn optional_digest(value: Option<&str>, b: &mut Bounds) -> Result<(), Failure> {
    value.map_or(Ok(()), |value| b.digest(value))
}
fn operation_id(value: &str, b: &mut Bounds) -> Result<(), Failure> {
    b.id(value)?;
    if value.len() > 128 || value.chars().any(char::is_whitespace) {
        return Err(invalid_response());
    }
    Ok(())
}
