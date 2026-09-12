use super::*;

pub(super) fn identity(value: &LifecycleIdentity, enforced: bool) -> Result<(), PlatformError> {
    value.scope.validate()?;
    if value.release.0.capacity() > 71 {
        return Err(exhausted());
    }
    value
        .release
        .0
        .parse::<ArtifactBlobDigest>()
        .map_err(|_| invalid())?;
    if enforced && (value.package.is_none() || value.scope.tenant().is_none()) {
        return Err(invalid());
    }
    if !enforced && value.package.is_some() {
        return Err(invalid());
    }
    Ok(())
}
fn policy(value: &Option<ReleasePolicyIdentity>) -> Result<(), PlatformError> {
    if let Some(value) = value {
        if value.scope.capacity() > 128 {
            return Err(exhausted());
        }
        model::token(&value.scope, 128)?;
        if value.generation == 0 {
            return Err(invalid());
        }
    }
    Ok(())
}
pub(super) fn record(
    value: &ReleaseLifecycleRecord,
    limits: LifecycleLimits,
) -> Result<(), PlatformError> {
    value.scope.validate()?;
    value.actor.validate()?;
    if value.operation_id.capacity() > 128 || value.release.0.capacity() > 71 {
        return Err(exhausted());
    }
    model::token(&value.operation_id, 128)?;
    policy(&value.policy)?;
    value
        .release
        .0
        .parse::<ArtifactBlobDigest>()
        .map_err(|_| invalid())?;
    if value.generation == 0 {
        return Err(invalid());
    }
    let reason_matches = match value.state {
        ReleaseLifecycleState::Admitted => matches!(
            value.reason,
            ReleaseLifecycleReason::Admitted | ReleaseLifecycleReason::EvidenceRenewed
        ),
        ReleaseLifecycleState::Revoked => matches!(
            value.reason,
            ReleaseLifecycleReason::OperatorRevocation
                | ReleaseLifecycleReason::SecurityIncident
                | ReleaseLifecycleReason::CorruptContent
        ),
        ReleaseLifecycleState::Retired => matches!(
            value.reason,
            ReleaseLifecycleReason::Superseded
                | ReleaseLifecycleReason::EndOfSupport
                | ReleaseLifecycleReason::OperatorRetirement
        ),
    };
    if !reason_matches {
        return Err(invalid());
    }
    if value.package.is_none()
        && (value.policy.is_some() || value.evidence_revision_digest.is_some())
    {
        return Err(invalid());
    }
    encode(value, limits.max_record_bytes)?;
    Ok(())
}
pub(super) fn receipt(
    value: &ReleaseOperationReceipt,
    limits: LifecycleLimits,
) -> Result<(), PlatformError> {
    value.scope.validate()?;
    value.actor.validate()?;
    if value.operation_id.capacity() > 128
        || value
            .component_digest
            .as_ref()
            .is_some_and(|value| value.0.capacity() > 71)
    {
        return Err(exhausted());
    }
    model::token(&value.operation_id, 128)?;
    policy(&value.policy)?;
    if let Some(release) = &value.component_digest {
        release
            .0
            .parse::<ArtifactBlobDigest>()
            .map_err(|_| invalid())?;
    }
    if let Some(row) = &value.record {
        record(row, limits)?;
        if row.scope != value.scope || Some(&row.release) != value.component_digest.as_ref() {
            return Err(invalid());
        }
    }
    encode(value, limits.max_receipt_bytes)?;
    Ok(())
}
pub(super) fn transition(
    state: &State,
    receipt: &ReleaseOperationReceipt,
    new_identity: Option<&LifecycleIdentity>,
    enforced: bool,
    limits: LifecycleLimits,
) -> Result<(), PlatformError> {
    let old = receipt
        .component_digest
        .as_ref()
        .and_then(|release| state.entries.get(release));
    if old.is_some_and(|entry| entry.stored.record.scope != receipt.scope) {
        return Err(invalid());
    }
    if receipt.disposition == ReleaseOperationDisposition::Rejected {
        if new_identity.is_some() {
            return Err(invalid());
        }
        if receipt.record.as_ref() != old.map(|entry| &entry.stored.record) {
            return Err(invalid());
        }
        return quota(state, receipt, None, limits);
    }
    let row = receipt.record.as_ref().ok_or_else(invalid)?;
    if receipt.action == ReleaseLifecycleAction::Publish {
        if let Some(old) = old {
            if old.stored.record.state != ReleaseLifecycleState::Admitted
                || *row != old.stored.record
                || new_identity.is_some_and(|identity| *identity != old.stored.identity)
                || receipt
                    .expected_generation
                    .is_some_and(|generation| generation != old.stored.record.generation)
            {
                return Err(conflict());
            }
            return quota(state, receipt, Some(&old.stored.identity), limits);
        }
    }
    if row.actor != receipt.actor
        || row.operation_id != receipt.operation_id
        || row.reason != receipt.reason
        || row.policy != receipt.policy
        || row.observed_at_unix_millis != receipt.observed_at_unix_millis
    {
        return Err(invalid());
    }
    let identity = new_identity
        .or_else(|| old.map(|entry| &entry.stored.identity))
        .ok_or_else(invalid)?;
    self::identity(identity, enforced)?;
    if identity.scope != row.scope
        || identity.release != row.release
        || identity.package != row.package
    {
        return Err(invalid());
    }
    if receipt
        .package_manifest_digest
        .as_ref()
        .map(ArtifactBlobDigest::as_str)
        != row.package.as_ref().map(PackageDigest::as_str)
    {
        return Err(invalid());
    }
    if let Some(old) = old {
        if old.stored.identity != *identity {
            return Err(conflict());
        }
        if receipt.expected_generation != Some(old.stored.record.generation) {
            return Err(conflict());
        }
        if row.generation
            != old
                .stored
                .record
                .generation
                .checked_add(1)
                .ok_or_else(exhausted)?
        {
            return Err(conflict());
        }
        let old_state = old.stored.record.state;
        let allowed = match receipt.action {
            ReleaseLifecycleAction::Publish => false,
            ReleaseLifecycleAction::Revoke => {
                old_state == ReleaseLifecycleState::Admitted
                    && row.state == ReleaseLifecycleState::Revoked
                    && matches!(
                        row.reason,
                        ReleaseLifecycleReason::OperatorRevocation
                            | ReleaseLifecycleReason::SecurityIncident
                            | ReleaseLifecycleReason::CorruptContent
                    )
            }
            ReleaseLifecycleAction::Retire => {
                old_state != ReleaseLifecycleState::Retired
                    && row.state == ReleaseLifecycleState::Retired
                    && matches!(
                        row.reason,
                        ReleaseLifecycleReason::OperatorRetirement
                            | ReleaseLifecycleReason::Superseded
                            | ReleaseLifecycleReason::EndOfSupport
                    )
            }
            ReleaseLifecycleAction::RenewEvidence => {
                old_state == ReleaseLifecycleState::Admitted
                    && row.state == ReleaseLifecycleState::Admitted
                    && row.package.is_some()
                    && row.reason == ReleaseLifecycleReason::EvidenceRenewed
                    && row.evidence_revision_digest.is_some()
                    && row.evidence_revision_digest != old.stored.record.evidence_revision_digest
            }
        };
        if !allowed {
            return Err(conflict());
        }
        if receipt.action != ReleaseLifecycleAction::RenewEvidence
            && row.evidence_revision_digest != old.stored.record.evidence_revision_digest
        {
            return Err(invalid());
        }
    } else {
        if receipt.action != ReleaseLifecycleAction::Publish
            || !matches!(receipt.expected_generation, None | Some(0))
            || row.generation != 1
            || row.state != ReleaseLifecycleState::Admitted
            || row.reason != ReleaseLifecycleReason::Admitted
            || row.evidence_revision_digest.is_some()
        {
            return Err(conflict());
        }
    }
    quota(state, receipt, Some(identity), limits)
}
fn quota(
    state: &State,
    receipt: &ReleaseOperationReceipt,
    identity: Option<&LifecycleIdentity>,
    limits: LifecycleLimits,
) -> Result<(), PlatformError> {
    let mut count = state.head.rows;
    let mut bytes = state.head.row_bytes;
    if receipt.disposition == ReleaseOperationDisposition::Committed {
        let row = receipt.record.as_ref().ok_or_else(invalid)?;
        let stored = StoredRow {
            identity: identity.ok_or_else(invalid)?.clone(),
            record: row.clone(),
        };
        let size = encode(&stored, limits.max_record_bytes)?.len();
        if let Some(old) = state.entries.get(&row.release) {
            bytes = bytes.checked_sub(old.bytes).ok_or_else(corrupt)?;
        } else {
            count = count.checked_add(1).ok_or_else(exhausted)?;
        }
        bytes = bytes.checked_add(size).ok_or_else(exhausted)?;
    }
    retention(count, bytes, limits)
}
pub(super) fn retention(
    count: usize,
    bytes: usize,
    limits: LifecycleLimits,
) -> Result<(), PlatformError> {
    let fixed = limits
        .max_recent_operations
        .checked_mul(limits.max_receipt_bytes + 256)
        .and_then(|value| value.checked_add(limits.max_intent_bytes + 4096))
        .ok_or_else(exhausted)?;
    // Include tree nodes, Arc control blocks and compact per-release capability
    // rows in retained metadata, rather than counting only JSON on disk.
    let retained = bytes
        .checked_mul(3)
        .and_then(|value| value.checked_add(count.checked_mul(1024)?))
        .and_then(|value| value.checked_add(fixed))
        .ok_or_else(exhausted)?;
    if count > limits.max_records || retained > limits.max_total_metadata_bytes {
        return Err(exhausted());
    }
    Ok(())
}
pub(super) fn recovered_quota(state: &State, limits: LifecycleLimits) -> Result<(), PlatformError> {
    retention(state.head.rows, state.head.row_bytes, limits)
}
