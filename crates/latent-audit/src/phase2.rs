use std::collections::{BTreeMap, VecDeque};
use std::sync::Mutex;

use latent_core::{
    AuditEventId, PackageDigest, PlatformError, PlatformErrorCode, PolicyId, ReleaseDigest,
    RevisionId, RouteGeneration, TenantId,
};

use crate::{AuditActor, AuditOutcome};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Phase2AuditEventKind {
    VerificationAccepted,
    VerificationRejected,
    ReleaseRevoked,
    ReleaseRetired,
    CacheHit,
    CacheMiss,
    CacheCorruption,
    RolloutStarted,
    RolloutStageChanged,
    RolloutPaused,
    RolloutAborted,
    PromotionAccepted,
    PromotionRejected,
    RollbackAccepted,
    RollbackRejected,
}

impl Phase2AuditEventKind {
    #[must_use]
    pub const fn wire_name(self) -> &'static str {
        match self {
            Self::VerificationAccepted => "verification-accepted",
            Self::VerificationRejected => "verification-rejected",
            Self::ReleaseRevoked => "release-revoked",
            Self::ReleaseRetired => "release-retired",
            Self::CacheHit => "cache-hit",
            Self::CacheMiss => "cache-miss",
            Self::CacheCorruption => "cache-corruption",
            Self::RolloutStarted => "rollout-started",
            Self::RolloutStageChanged => "rollout-stage-changed",
            Self::RolloutPaused => "rollout-paused",
            Self::RolloutAborted => "rollout-aborted",
            Self::PromotionAccepted => "promotion-accepted",
            Self::PromotionRejected => "promotion-rejected",
            Self::RollbackAccepted => "rollback-accepted",
            Self::RollbackRejected => "rollback-rejected",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Phase2AuditIdentity {
    pub tenant: TenantId,
    pub operation_id: String,
    pub package: Option<PackageDigest>,
    pub component: Option<ReleaseDigest>,
    pub policy: Option<PolicyId>,
    pub rollout_id: Option<String>,
    pub revision: Option<RevisionId>,
    pub generation: Option<RouteGeneration>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Phase2AuditEvent {
    pub id: AuditEventId,
    pub actor: AuditActor,
    pub kind: Phase2AuditEventKind,
    pub identity: Phase2AuditIdentity,
    pub outcome: AuditOutcome,
    pub occurred_at_unix_millis: u64,
    /// Stable bounded reason code. Do not put raw registry responses, credentials,
    /// signature bytes, keys or arbitrary external error bodies here.
    pub reason_code: Option<String>,
    pub attributes: BTreeMap<String, String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Phase2AuditLimits {
    pub max_events: usize,
    pub max_query_events: usize,
    pub max_attributes: usize,
    pub max_string_bytes: usize,
}

impl Default for Phase2AuditLimits {
    fn default() -> Self {
        Self {
            max_events: 4096,
            max_query_events: 256,
            max_attributes: 32,
            max_string_bytes: 512,
        }
    }
}

impl Phase2AuditLimits {
    fn validate(self) -> Result<(), PlatformError> {
        if self.max_events == 0
            || self.max_query_events == 0
            || self.max_attributes == 0
            || self.max_string_bytes == 0
        {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid-phase2-audit-limits",
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct Phase2AuditCursor(pub u64);

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Phase2AuditPage {
    pub events: Vec<Phase2AuditEvent>,
    pub next_cursor: Option<Phase2AuditCursor>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Phase2AuditSnapshot {
    pub retained_events: usize,
    pub capacity: usize,
    pub rejected_overflow_events: u64,
    pub next_sequence: u64,
}

#[derive(Debug)]
pub struct BoundedPhase2AuditJournal {
    limits: Phase2AuditLimits,
    state: Mutex<JournalState>,
}

#[derive(Debug)]
struct JournalState {
    entries: VecDeque<StoredEvent>,
    next_sequence: u64,
    rejected_overflow_events: u64,
}

#[derive(Debug, Clone)]
struct StoredEvent {
    sequence: u64,
    event: Phase2AuditEvent,
}

impl BoundedPhase2AuditJournal {
    pub fn new(limits: Phase2AuditLimits) -> Result<Self, PlatformError> {
        limits.validate()?;
        Ok(Self {
            limits,
            state: Mutex::new(JournalState {
                entries: VecDeque::with_capacity(limits.max_events.min(1024)),
                next_sequence: 1,
                rejected_overflow_events: 0,
            }),
        })
    }

    pub fn append(&self, event: Phase2AuditEvent) -> Result<Phase2AuditCursor, PlatformError> {
        validate_event(&event, self.limits)?;
        let mut state = self.lock_state()?;
        if state.entries.len() >= self.limits.max_events {
            state.rejected_overflow_events = state.rejected_overflow_events.saturating_add(1);
            return Err(error(
                PlatformErrorCode::ResourceExhausted,
                "phase2-audit-capacity-exhausted",
            ));
        }
        let sequence = state.next_sequence;
        state.next_sequence = state
            .next_sequence
            .checked_add(1)
            .ok_or_else(|| error(PlatformErrorCode::ResourceExhausted, "phase2-audit-sequence-exhausted"))?;
        state.entries.push_back(StoredEvent { sequence, event });
        Ok(Phase2AuditCursor(sequence))
    }

    /// Returns only records for the caller-authorized tenant. The cursor is an
    /// opaque journal position, not an authorization capability.
    pub fn query_tenant(
        &self,
        tenant: &TenantId,
        after: Option<Phase2AuditCursor>,
        limit: usize,
    ) -> Result<Phase2AuditPage, PlatformError> {
        if limit == 0 || limit > self.limits.max_query_events {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid-phase2-audit-query-limit",
            ));
        }
        validate_string(&tenant.0, self.limits, "invalid-phase2-audit-tenant")?;
        let state = self.lock_state()?;
        let after = after.map_or(0, |cursor| cursor.0);
        let mut matching = state
            .entries
            .iter()
            .filter(|stored| {
                stored.sequence > after && &stored.event.identity.tenant == tenant
            });
        let mut selected = Vec::with_capacity(limit);
        let mut last_sequence = None;
        for stored in matching.by_ref().take(limit) {
            selected.push(stored.event.clone());
            last_sequence = Some(stored.sequence);
        }
        let has_more = matching.next().is_some();
        Ok(Phase2AuditPage {
            events: selected,
            next_cursor: if has_more {
                last_sequence.map(Phase2AuditCursor)
            } else {
                None
            },
        })
    }

    pub fn snapshot(&self) -> Result<Phase2AuditSnapshot, PlatformError> {
        let state = self.lock_state()?;
        Ok(Phase2AuditSnapshot {
            retained_events: state.entries.len(),
            capacity: self.limits.max_events,
            rejected_overflow_events: state.rejected_overflow_events,
            next_sequence: state.next_sequence,
        })
    }

    fn lock_state(&self) -> Result<std::sync::MutexGuard<'_, JournalState>, PlatformError> {
        self.state.lock().map_err(|_| {
            error(
                PlatformErrorCode::Internal,
                "phase2-audit-journal-poisoned",
            )
        })
    }
}

fn validate_event(event: &Phase2AuditEvent, limits: Phase2AuditLimits) -> Result<(), PlatformError> {
    validate_string(&event.id.0, limits, "invalid-phase2-audit-event-id")?;
    validate_string(&event.identity.tenant.0, limits, "invalid-phase2-audit-tenant")?;
    validate_string(
        &event.identity.operation_id,
        limits,
        "invalid-phase2-audit-operation-id",
    )?;
    validate_optional_string(
        event.identity.rollout_id.as_deref(),
        limits,
        "invalid-phase2-audit-rollout-id",
    )?;
    validate_optional_string(
        event.reason_code.as_deref(),
        limits,
        "invalid-phase2-audit-reason-code",
    )?;
    validate_string(&event.actor.subject, limits, "invalid-phase2-audit-actor")?;
    validate_string(
        &event.actor.actor_type,
        limits,
        "invalid-phase2-audit-actor-type",
    )?;
    if event
        .actor
        .tenant
        .as_ref()
        .is_some_and(|tenant| tenant != &event.identity.tenant)
    {
        return Err(error(
            PlatformErrorCode::PermissionDenied,
            "phase2-audit-actor-tenant-mismatch",
        ));
    }
    validate_metadata(&event.actor.attributes, limits)?;
    validate_metadata(&event.attributes, limits)?;
    Ok(())
}

fn validate_metadata(
    metadata: &BTreeMap<String, String>,
    limits: Phase2AuditLimits,
) -> Result<(), PlatformError> {
    if metadata.len() > limits.max_attributes {
        return Err(error(
            PlatformErrorCode::ResourceExhausted,
            "phase2-audit-attribute-limit",
        ));
    }
    for (key, value) in metadata {
        validate_string(key, limits, "invalid-phase2-audit-attribute")?;
        validate_string(value, limits, "invalid-phase2-audit-attribute")?;
        if sensitive_key(key) {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "sensitive-phase2-audit-attribute",
            ));
        }
    }
    Ok(())
}

fn sensitive_key(key: &str) -> bool {
    let lowered = key.to_ascii_lowercase();
    [
        "authorization",
        "credential",
        "password",
        "private-key",
        "secret",
        "signing-key",
        "token",
    ]
    .iter()
    .any(|marker| lowered.contains(marker))
}

fn validate_string(
    value: &str,
    limits: Phase2AuditLimits,
    reason: &'static str,
) -> Result<(), PlatformError> {
    if value.is_empty() || value.len() > limits.max_string_bytes || value.contains('\0') {
        return Err(error(PlatformErrorCode::InvalidArgument, reason));
    }
    Ok(())
}

fn validate_optional_string(
    value: Option<&str>,
    limits: Phase2AuditLimits,
    reason: &'static str,
) -> Result<(), PlatformError> {
    if let Some(value) = value {
        validate_string(value, limits, reason)?;
    }
    Ok(())
}

fn error(code: PlatformErrorCode, message: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use latent_core::{
        AuditEventId, PackageDigest, PlatformErrorCode, PolicyId, ReleaseDigest, RevisionId,
        RouteGeneration, TenantId,
    };

    use crate::{AuditActor, AuditOutcome};

    use super::{
        BoundedPhase2AuditJournal, Phase2AuditEvent, Phase2AuditEventKind, Phase2AuditIdentity,
        Phase2AuditLimits,
    };

    fn event(id: &str, tenant: &str) -> Phase2AuditEvent {
        let tenant = TenantId(tenant.to_owned());
        Phase2AuditEvent {
            id: AuditEventId(id.to_owned()),
            actor: AuditActor {
                subject: "operator:test".to_owned(),
                actor_type: "operator".to_owned(),
                tenant: Some(tenant.clone()),
                attributes: BTreeMap::new(),
            },
            kind: Phase2AuditEventKind::VerificationAccepted,
            identity: Phase2AuditIdentity {
                tenant,
                operation_id: format!("op-{id}"),
                package: Some(package_digest('a')),
                component: Some(ReleaseDigest("sha256:component".to_owned())),
                policy: Some(PolicyId("policy-1".to_owned())),
                rollout_id: Some("rollout-1".to_owned()),
                revision: Some(RevisionId("revision-1".to_owned())),
                generation: Some(RouteGeneration(7)),
            },
            outcome: AuditOutcome::Succeeded,
            occurred_at_unix_millis: 1234,
            reason_code: None,
            attributes: BTreeMap::from([("cache-disposition".to_owned(), "miss".to_owned())]),
        }
    }

    fn package_digest(byte: char) -> PackageDigest {
        format!("sha256:{}", byte.to_string().repeat(64))
            .parse()
            .unwrap()
    }

    #[test]
    fn tenant_queries_are_isolated_and_paginated() {
        let journal = BoundedPhase2AuditJournal::new(Phase2AuditLimits {
            max_events: 8,
            max_query_events: 2,
            ..Phase2AuditLimits::default()
        })
        .unwrap();
        journal.append(event("1", "a")).unwrap();
        journal.append(event("2", "b")).unwrap();
        journal.append(event("3", "a")).unwrap();
        journal.append(event("4", "a")).unwrap();

        let first = journal
            .query_tenant(&TenantId("a".to_owned()), None, 2)
            .unwrap();
        assert_eq!(first.events.len(), 2);
        assert_eq!(first.events[0].id.0, "1");
        assert_eq!(first.events[1].id.0, "3");
        let cursor = first.next_cursor.unwrap();

        let second = journal
            .query_tenant(&TenantId("a".to_owned()), Some(cursor), 2)
            .unwrap();
        assert_eq!(second.events.len(), 1);
        assert_eq!(second.events[0].id.0, "4");
        assert_eq!(second.next_cursor, None);
    }

    #[test]
    fn capacity_rejects_new_events_without_evicting_existing_audit_history() {
        let journal = BoundedPhase2AuditJournal::new(Phase2AuditLimits {
            max_events: 2,
            ..Phase2AuditLimits::default()
        })
        .unwrap();
        journal.append(event("1", "a")).unwrap();
        journal.append(event("2", "a")).unwrap();

        let error = journal.append(event("3", "a")).unwrap_err();
        assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
        assert_eq!(error.message, "phase2-audit-capacity-exhausted");

        let snapshot = journal.snapshot().unwrap();
        assert_eq!(snapshot.retained_events, 2);
        assert_eq!(snapshot.rejected_overflow_events, 1);
    }

    #[test]
    fn sensitive_and_cross_tenant_actor_metadata_fail_closed() {
        let journal = BoundedPhase2AuditJournal::new(Phase2AuditLimits::default()).unwrap();
        let mut sensitive = event("1", "a");
        sensitive
            .attributes
            .insert("registry-token".to_owned(), "do-not-log".to_owned());
        let error = journal.append(sensitive).unwrap_err();
        assert_eq!(error.code, PlatformErrorCode::InvalidArgument);
        assert_eq!(error.message, "sensitive-phase2-audit-attribute");

        let mut mismatched = event("2", "a");
        mismatched.actor.tenant = Some(TenantId("b".to_owned()));
        let error = journal.append(mismatched).unwrap_err();
        assert_eq!(error.code, PlatformErrorCode::PermissionDenied);
        assert_eq!(error.message, "phase2-audit-actor-tenant-mismatch");
    }

    #[test]
    fn event_kind_wire_names_are_fixed_low_cardinality_values() {
        let kinds = [
            Phase2AuditEventKind::VerificationAccepted,
            Phase2AuditEventKind::VerificationRejected,
            Phase2AuditEventKind::ReleaseRevoked,
            Phase2AuditEventKind::ReleaseRetired,
            Phase2AuditEventKind::CacheHit,
            Phase2AuditEventKind::CacheMiss,
            Phase2AuditEventKind::CacheCorruption,
            Phase2AuditEventKind::RolloutStarted,
            Phase2AuditEventKind::RolloutStageChanged,
            Phase2AuditEventKind::RolloutPaused,
            Phase2AuditEventKind::RolloutAborted,
            Phase2AuditEventKind::PromotionAccepted,
            Phase2AuditEventKind::PromotionRejected,
            Phase2AuditEventKind::RollbackAccepted,
            Phase2AuditEventKind::RollbackRejected,
        ];
        let names = kinds.map(Phase2AuditEventKind::wire_name);
        let unique = names.into_iter().collect::<std::collections::BTreeSet<_>>();
        assert_eq!(unique.len(), kinds.len());
        assert!(unique.iter().all(|name| !name.contains(' ')));
    }
}
