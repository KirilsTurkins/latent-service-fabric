use super::{
    plan::{self, Plan},
    RetentionAction, RetentionAudit, RetentionProgress, RetentionRequest,
};
use crate::atomic::{
    record::{attempt_row_key, command_row_key, result_row_key},
    retention::ExpiredResult,
    writer::{fenced_error, Usage},
    AtomicError, CommandRecord, DurableResult, MaintenanceClock, Outcome, ResultMaintenanceOwner,
};
use latent_effects::{
    authority::EffectTime, dispatch::Disposition, dispatch_store::DispatchCatalog,
};
use latent_state::{
    embedded::{EmbeddedStore, ExpectedRow, ReadView},
    namespace::NamespaceRecord,
    reservation::reservation_key,
};

pub(super) struct Captured {
    pub record: CommandRecord,
    pub bytes: Vec<u8>,
    pub audit: Option<RetentionAudit>,
    pub audit_bytes: Option<Vec<u8>>,
    pub namespace: NamespaceRecord,
    pub plan: Plan,
}
impl Captured {
    pub fn publish_audit(&mut self, audit: &RetentionAudit) -> Result<(), AtomicError> {
        self.record.retention_review = audit.encode()?;
        let bytes = self.record.encode()?;
        self.plan
            .mutation(command_row_key(self.record.id), Some(bytes.clone()))?;
        self.plan.mutation(
            attempt_row_key(self.record.id, self.record.attempt),
            Some(bytes),
        )
    }
    pub fn read(view: &ReadView, request: &RetentionRequest) -> Result<Self, AtomicError> {
        let key = command_row_key(crate::atomic::command_identity(&request.key)?);
        let bytes = view.get(&key)?.ok_or(AtomicError::NotFound)?;
        if super::RetiredCommand::is_present(&bytes) {
            super::RetiredCommand::decode(&bytes)?.verify_key(&request.key)?;
            return Err(AtomicError::Expired);
        }
        let record = CommandRecord::decode(&bytes)?;
        if !record.accounted {
            return Err(AtomicError::UnsupportedFormat);
        }
        if record.key != request.key {
            return Err(AtomicError::Conflict);
        }
        let mut plan = Plan::default();
        let readiness = latent_state::recovery::maintenance::namespace_expectations(
            view,
            &latent_core::TenantId(record.key.tenant.clone()),
            &latent_core::StateNamespaceId(record.key.namespace.clone()),
            crate::atomic::incarnation(&record.key)?,
        )?;
        let namespace =
            NamespaceRecord::decode(readiness[1].value.as_deref().ok_or(AtomicError::Corrupt)?)
                .map_err(|_| AtomicError::Corrupt)?;
        for row in readiness {
            plan.expect(row)?;
        }
        plan.expect(ExpectedRow {
            key,
            value: Some(bytes.clone()),
        })?;
        let attempt_key = attempt_row_key(record.id, record.attempt);
        let attempt = view.get(&attempt_key)?.ok_or(AtomicError::Corrupt)?;
        if attempt != bytes {
            return Err(AtomicError::Corrupt);
        }
        plan.expect(ExpectedRow {
            key: attempt_key,
            value: Some(attempt),
        })?;
        let audit_bytes =
            (!record.retention_review.is_empty()).then(|| record.retention_review.clone());
        let audit = audit_bytes
            .as_deref()
            .map(RetentionAudit::decode)
            .transpose()?;
        if let Some(audit) = &audit {
            audit.verify(&record)?;
            audit.matches(request)?;
        }
        Ok(Self {
            record,
            bytes,
            audit,
            audit_bytes,
            namespace,
            plan,
        })
    }
}

impl ResultMaintenanceOwner {
    /// Explicit current-policy review; never automatic expiry of an uncertain
    /// command. Advance at most one original effect with its bounded histories.
    /// The original provider receipt, input/source/schema and payload survive.
    pub fn terminalize(
        &self,
        store: &EmbeddedStore,
        request: &RetentionRequest,
        clock: MaintenanceClock,
        mut authorize: impl FnMut(
            RetentionAction,
            &RetentionRequest,
            Option<&CommandRecord>,
        ) -> Result<(), AtomicError>,
    ) -> Result<RetentionProgress, AtomicError> {
        let _physical_step = self.enter()?;
        authorize(RetentionAction::Terminalize, request, None)?;
        let view = store.snapshot()?;
        let (progress, progress_fence) = plan::progress(&view, &request.key, clock)?;
        let mut captured = Captured::read(&view, request)?;
        if let Some(fence) = progress_fence {
            captured.plan.expect(fence)?;
        }
        authorize(
            RetentionAction::Terminalize,
            request,
            Some(&captured.record),
        )?;
        clock.time.check(captured.record.clock_floor)?;
        if captured.record.outcome == Outcome::Pending {
            return Err(AtomicError::RecoveryRequired);
        }
        if clock.time.unix_millis < captured.record.identity_expires {
            return Err(AtomicError::Expired);
        }
        if captured.audit.as_ref().is_some_and(|audit| audit.purging) {
            return Err(AtomicError::Conflict);
        }
        let mut audit = start(&mut captured, request, clock)?;
        if captured.audit.is_some() && audit.terminalized == audit.effect_count {
            return Ok(audit.progress(&captured.record, RetentionAction::Terminalize));
        }
        expire_one(
            &view,
            &mut captured.plan,
            &captured.record,
            &mut audit,
            clock,
        )?;
        let (mut usage, usage_key, usage_bytes) = account(&view, &mut captured, &audit)?;
        captured.publish_audit(&audit)?;
        plan::advance(&mut usage, progress, clock, 0, false)?;
        captured
            .plan
            .replace(usage_key, usage_bytes, Some(usage.encode()?))?;
        let result = audit.progress(&captured.record, RetentionAction::Terminalize);
        drop(view);
        store
            .apply_fenced(captured.plan.batch, || {
                authorize(RetentionAction::Terminalize, request, None)?;
                authorize(
                    RetentionAction::Terminalize,
                    request,
                    Some(&captured.record),
                )
            })
            .map_err(fenced_error)?;
        Ok(result)
    }
}

fn start(
    captured: &mut Captured,
    request: &RetentionRequest,
    clock: MaintenanceClock,
) -> Result<RetentionAudit, AtomicError> {
    if let Some(audit) = &captured.audit {
        return Ok(audit.clone());
    }
    request.validate(&captured.record, clock.time.unix_millis)?;
    captured.record.clock_floor = clock.time.unix_millis;
    Ok(RetentionAudit {
        command: captured.record.id,
        attempt: captured.record.attempt,
        command_digest: RetentionRequest::command_digest(&captured.record)?,
        request_digest: request.expected_command_digest,
        actor: request.actor.clone(),
        operation_id: request.operation_id.clone(),
        policy: request.policy.clone(),
        reviewed_at: clock.time.unix_millis,
        retain_until: request.retain_until_millis,
        inbox_expires: request.inbox_expires_at_millis,
        terminalized: 0,
        effect_count: captured.record.effects.len() as u64,
        purged: 0,
        purged_attempts: 0,
        purging: false,
        effect_before_bytes: 0,
        effect_after_bytes: 0,
    })
}

fn expire_one(
    view: &ReadView,
    plan: &mut Plan,
    record: &CommandRecord,
    audit: &mut RetentionAudit,
    clock: MaintenanceClock,
) -> Result<(), AtomicError> {
    let Some(effect) = record
        .effects
        .get(usize::try_from(audit.terminalized).map_err(|_| AtomicError::Limit)?)
    else {
        return Ok(());
    };
    let key = latent_effects::dispatch_store::effect_row_key(&effect.hex())?;
    let bytes = view.get(&key)?.ok_or(AtomicError::Corrupt)?;
    if latent_effects::dispatch::EffectRecord::decode(&bytes)?.disposition()
        == Disposition::Dispatching
    {
        return Err(AtomicError::InProgress);
    }
    let mut closure = DispatchCatalog::retention_rows(view, &effect.hex())?;
    verify_effect(record, &closure.record.authority()?, *effect)?;
    closure.record.expire_retired(EffectTime {
        unix_millis: clock.time.unix_millis,
        continuity_proven: clock.time.continuity_proven,
    })?;
    let new = closure.record.encode()?;
    audit.effect_before_bytes = audit
        .effect_before_bytes
        .checked_add(bytes.len() as u64)
        .ok_or(AtomicError::Limit)?;
    audit.effect_after_bytes = audit
        .effect_after_bytes
        .checked_add(new.len() as u64)
        .ok_or(AtomicError::Limit)?;
    audit.growth()?;
    for row in closure.expectations {
        plan.expect(row)?;
    }
    plan.mutation(key, Some(new))?;
    if let Some(due) = closure.due {
        plan.mutation(due, None)?;
    }
    audit.terminalized = audit
        .terminalized
        .checked_add(1)
        .ok_or(AtomicError::Limit)?;
    Ok(())
}

fn account(
    view: &ReadView,
    captured: &mut Captured,
    audit: &RetentionAudit,
) -> Result<(Usage, latent_state::embedded::RowKey, Option<Vec<u8>>), AtomicError> {
    let (mut usage, key, bytes) = Usage::read(view, &captured.record.key)?;
    let reserve_key = reservation_key(&captured.record.id.bytes())?;
    let old = view.get(&reserve_key)?;
    if old.is_some() {
        return Err(AtomicError::Corrupt);
    }
    let previous = captured.audit.as_ref().map_or(
        Ok(super::super::AUDIT_RESERVED_BYTES),
        RetentionAudit::reservation,
    )?;
    if !usage.accounted || !captured.record.accounted {
        return Err(AtomicError::Corrupt);
    }
    let next = audit.reservation()?;
    let old_audit = captured.audit_bytes.as_ref().map_or(0, Vec::len) as u64 * 2;
    let new_audit = audit.encode()?.len() as u64 * 2;
    usage.reserved = usage
        .reserved
        .checked_sub(previous)
        .and_then(|value| value.checked_add(next))
        .ok_or(AtomicError::Corrupt)?;
    usage.recovery_reserved = usage
        .recovery_reserved
        .checked_sub(previous)
        .and_then(|value| value.checked_add(next))
        .ok_or(AtomicError::Corrupt)?;
    usage.result_bytes = usage
        .result_bytes
        .checked_sub(previous)
        .and_then(|value| value.checked_sub(old_audit))
        .and_then(|value| value.checked_add(next))
        .and_then(|value| value.checked_add(new_audit))
        .ok_or(AtomicError::Corrupt)?;
    retire_body(view, captured, &mut usage)?;
    usage.check(&captured.namespace)?;
    captured.plan.expect(ExpectedRow {
        key: reserve_key,
        value: None,
    })?;
    Ok((usage, key, bytes))
}

pub(super) fn verify_effect(
    record: &CommandRecord,
    authority: &latent_effects::authority::DurableEffectAuthority,
    effect: crate::atomic::Identity,
) -> Result<(), AtomicError> {
    if authority.link().command != record.id.hex()
        || authority.link().attempt != record.attempt
        || authority.link().commit != record.disposition_id().hex()
        || authority.link().effect != effect.hex()
        || authority.link().caller_scope != record.key.recovery_scope
        || authority.scope().tenant != record.key.tenant
        || authority.scope().namespace != record.key.namespace
        || authority.scope().incarnation != crate::atomic::incarnation(&record.key)?
    {
        return Err(AtomicError::Corrupt);
    }
    Ok(())
}

fn retire_body(
    view: &ReadView,
    captured: &mut Captured,
    usage: &mut Usage,
) -> Result<(), AtomicError> {
    let key = result_row_key(captured.record.id, captured.record.attempt);
    let bytes = view.get(&key)?.ok_or(AtomicError::Corrupt)?;
    if bytes.starts_with(b"LCE\0") {
        ExpiredResult::decode(&bytes)?.verify(&captured.record)?;
        captured.plan.expect(ExpectedRow {
            key,
            value: Some(bytes),
        })?;
        return Ok(());
    }
    DurableResult::decode(&bytes)?.verify(&captured.record)?;
    let marker = ExpiredResult::new(&captured.record, captured.record.clock_floor)?.encode();
    let reclaimed = bytes
        .len()
        .checked_sub(marker.len())
        .ok_or(AtomicError::Corrupt)? as u64;
    usage.result_bytes = usage
        .result_bytes
        .checked_sub(reclaimed)
        .ok_or(AtomicError::Corrupt)?;
    captured.plan.replace(key, Some(bytes), Some(marker))
}
