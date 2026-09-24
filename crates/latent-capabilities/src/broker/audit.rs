//! Typed audit production by the actual sealed broker/provider owners.
mod capture;
mod recovery;
use super::{denied, error, session::SessionCore, ActivationCapabilityBroker, PlatformError};
pub(super) use capture::request_digest;
use latent_audit::{
    AuditAttempt, AuditHandle, AuditIdentities, AuditObservation, AuditOperationAttempt,
    AuditOperationConclusion, AuditOperationResult, AuditOutcome, AuditProviderOutcome,
    AuditReason, Phase2AuditEventKind,
};
use latent_core::PlatformErrorCode;
pub use recovery::reconcile_capability_audit;
use sha2::{Digest, Sha256};
use std::{
    sync::Arc,
    time::{Duration, Instant},
};

/// A bounded trusted typed adapter hashes actual fields in canonical order,
/// including length boundaries. This value never grants permission by itself.
#[derive(Debug, Clone, Copy)]
pub struct CapabilityRequestDigest(pub(super) [u8; 32]);
impl CapabilityRequestDigest {
    /// Bind additional typed metadata without exposing the original request.
    pub fn with_context(self, context: &[u8]) -> Result<Self, PlatformError> {
        Self::from_parts(&[b"lsf-typed-request-context-v1", &self.0, context])
    }
    pub fn from_parts(parts: &[&[u8]]) -> Result<Self, PlatformError> {
        if parts.len() > 256 {
            return Err(super::capacity());
        }
        let mut total = 0usize;
        let mut digest = Sha256::new();
        digest.update(b"lsf-capability-typed-request-v1\0");
        for part in parts {
            total = total.checked_add(part.len()).ok_or_else(super::capacity)?;
            if total > 1024 * 1024 {
                return Err(super::capacity());
            }
            digest.update((part.len() as u64).to_le_bytes());
            digest.update(part);
        }
        Ok(Self(digest.finalize().into()))
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum CapabilityAuditDurability {
    #[default]
    NotRequired,
    Durable {
        sequence: u64,
    },
    OutcomeUnknown,
}
pub(super) struct Configuration {
    pub handle: AuditHandle,
    pub observations: bool,
    pub dropped: std::sync::atomic::AtomicU64,
}
impl Configuration {
    pub fn note_dropped(&self) {
        let _ = self.dropped.fetch_update(
            std::sync::atomic::Ordering::Relaxed,
            std::sync::atomic::Ordering::Relaxed,
            |v| Some(v.saturating_add(1)),
        );
    }
}
pub(super) fn observe_grant(
    core: &SessionCore,
    capability: &str,
    operation: &str,
    resource: latent_policy::capability::ResourceTarget<'_>,
    result: Result<(), &PlatformError>,
) {
    let Some(configuration) = core.owner.audit.as_ref().filter(|audit| audit.observations) else {
        return;
    };
    if operation.len() > 64 || !capture::bounded_resource(resource) {
        configuration.note_dropped();
        return;
    }
    let Some(index) = core
        .plan
        .bindings
        .iter()
        .position(|b| b.provider.capability == capability)
    else {
        configuration.note_dropped();
        return;
    };
    let Ok(_metadata) = core.owner.counters.acquire(super::Kind::Metadata, 16384) else {
        configuration.note_dropped();
        return;
    };
    let Ok(mut record) = capture::attempt(
        core,
        index,
        operation,
        resource,
        request_digest(operation, resource, &[], None),
        false,
        0,
    ) else {
        configuration.note_dropped();
        return;
    };
    let context = record
        .identities
        .capability
        .as_mut()
        .expect("captured context");
    context.request.as_mut().expect("captured request").scope =
        latent_audit::AuditCapabilityDigestScope::ResourceSelection;
    let (kind, outcome, reason) = match result {
        Ok(_) => (
            Phase2AuditEventKind::CapabilityGrantAllowed,
            AuditOutcome::Succeeded,
            AuditReason::Admitted,
        ),
        Err(failure) => (
            Phase2AuditEventKind::CapabilityGrantDenied,
            AuditOutcome::Denied,
            match failure.code {
                PlatformErrorCode::ResourceExhausted => AuditReason::Capacity,
                PlatformErrorCode::Unavailable => AuditReason::Unavailable,
                _ => AuditReason::PolicyDenied,
            },
        ),
    };
    let _ = configuration.handle.try_capture(&AuditObservation {
        scope: record.scope,
        actor: record.actor,
        identities: record.identities,
        kind,
        outcome,
        reason,
        cache_kind: None,
        occurred_at_unix_millis: now(),
    });
}
impl ActivationCapabilityBroker {
    /// Configure the shared journal before installing providers/plans/sessions.
    /// Optional diagnostic capture is lossy; required policy is always enforced.
    pub fn with_audit(
        mut self,
        handle: AuditHandle,
        observations: bool,
    ) -> Result<Self, PlatformError> {
        let owner = Arc::get_mut(&mut self.inner).ok_or_else(denied)?;
        if owner.audit.is_some() {
            return Err(denied());
        }
        owner.audit = Some(Configuration {
            handle,
            observations,
            dropped: std::sync::atomic::AtomicU64::new(0),
        });
        Ok(self)
    }
    #[must_use]
    pub fn audit_owner_matches(&self, handle: &AuditHandle) -> bool {
        self.inner
            .audit
            .as_ref()
            .is_some_and(|audit| audit.handle.same_owner(handle))
    }
    #[must_use]
    pub fn has_audit(&self) -> bool {
        self.inner.audit.is_some()
    }
}

pub(super) struct CallAudit {
    handle: AuditHandle,
    record: AuditOperationAttempt,
    attempt: Option<AuditAttempt>,
    required: bool,
    observations: bool,
    outcome: AuditProviderOutcome,
    durability: CapabilityAuditDurability,
    finished: bool,
}
impl CallAudit {
    pub fn prepare(
        core: &SessionCore,
        binding: usize,
        operation: &str,
        resource: latent_policy::capability::ResourceTarget<'_>,
        digest: latent_core::ArtifactBlobDigest,
        required: bool,
        id: u64,
    ) -> Result<Option<Box<Self>>, PlatformError> {
        let Some(configuration) = &core.owner.audit else {
            return if required {
                Err(error(
                    PlatformErrorCode::ResourceExhausted,
                    "capability-audit-unavailable",
                ))
            } else {
                Ok(None)
            };
        };
        if !required && !configuration.observations {
            return Ok(None);
        }
        let record =
            match capture::attempt(core, binding, operation, resource, digest, required, id) {
                Ok(record) => record,
                Err(failure) if required => return Err(failure),
                Err(_) => {
                    let _ = configuration.dropped.fetch_update(
                        std::sync::atomic::Ordering::Relaxed,
                        std::sync::atomic::Ordering::Relaxed,
                        |v| Some(v.saturating_add(1)),
                    );
                    return Ok(None);
                }
            };
        Ok(Some(Box::new(Self {
            handle: configuration.handle.clone(),
            record,
            attempt: None,
            required,
            observations: configuration.observations,
            outcome: AuditProviderOutcome::NotStarted,
            durability: if required {
                CapabilityAuditDurability::OutcomeUnknown
            } else {
                CapabilityAuditDurability::NotRequired
            },
            finished: false,
        })))
    }
    pub async fn begin(
        &mut self,
        core: &SessionCore,
        deadline: Instant,
    ) -> Result<(), PlatformError> {
        if !self.required {
            return Ok(());
        }
        // Preflight every possible terminal variant before reserving or dispatch.
        for outcome in [
            AuditProviderOutcome::NotStarted,
            AuditProviderOutcome::LocalDispatchAccepted,
            AuditProviderOutcome::HttpResponseReceived,
            AuditProviderOutcome::BrokerAcknowledged,
            AuditProviderOutcome::BlobSealed,
            AuditProviderOutcome::SecretResolved,
            AuditProviderOutcome::HostCompleted,
            AuditProviderOutcome::Rejected,
            AuditProviderOutcome::Unknown,
        ] {
            if !self
                .record
                .identities
                .capability
                .as_ref()
                .expect("captured context")
                .accepts_outcome(outcome)
            {
                continue;
            }
            self.handle
                .preflight_conclusion(&self.record, &self.conclusion(outcome))?;
        }
        let ticket = self
            .handle
            .try_reserve_critical(&self.record)?
            .begin()
            .wait();
        tokio::pin!(ticket);
        loop {
            core.check()?;
            if core.owner.clock.monotonic_now() >= deadline {
                return Err(error(
                    PlatformErrorCode::DeadlineExceeded,
                    "capability-audit-deadline",
                ));
            }
            tokio::select! {
                result = &mut ticket => { self.attempt = Some(result?); return Ok(()); }
                () = tokio::time::sleep(Duration::from_millis(10)) => {}
            }
        }
    }
    /// Called outside all authority fences, immediately before their final
    /// recheck. A rejected final check is recorded as `NotStarted` by this owner.
    pub fn arm(&mut self) -> Result<(), PlatformError> {
        if let Some(attempt) = &mut self.attempt {
            attempt.mutation_started()?;
        }
        Ok(())
    }
    pub fn dispatched(&mut self) {
        self.outcome = AuditProviderOutcome::Unknown;
    }
    /// Trusted adapter evidence remains recordable after timeout/revocation.
    /// Recording a fact never extends an operation's execution permission.
    pub fn record_outcome(&mut self, outcome: AuditProviderOutcome) -> Result<(), PlatformError> {
        let valid = self
            .record
            .identities
            .capability
            .as_ref()
            .expect("captured context")
            .accepts_outcome(outcome)
            && outcome != AuditProviderOutcome::NotStarted;
        if !valid
            || self.finished
            || (self.outcome != AuditProviderOutcome::Unknown && self.outcome != outcome)
        {
            return Err(denied());
        }
        self.outcome = outcome;
        Ok(())
    }
    pub fn outcome(&self) -> AuditProviderOutcome {
        self.outcome
    }
    pub fn durability(&self) -> CapabilityAuditDurability {
        self.durability
    }
    fn conclusion(&self, outcome: AuditProviderOutcome) -> AuditOperationConclusion {
        let mut identities = self.record.identities.clone();
        identities
            .capability
            .as_mut()
            .expect("captured context")
            .provider_outcome = Some(outcome);
        let (result, reason) = match outcome {
            AuditProviderOutcome::NotStarted => {
                (AuditOperationResult::NotStarted, AuditReason::NotStarted)
            }
            AuditProviderOutcome::Unknown => (
                AuditOperationResult::Unknown,
                AuditReason::MutationUncertain,
            ),
            AuditProviderOutcome::Rejected => {
                (AuditOperationResult::Rejected, AuditReason::Rejected)
            }
            _ => (AuditOperationResult::Committed, AuditReason::Committed),
        };
        AuditOperationConclusion {
            canary_decision: None,
            result,
            reason,
            receipt_digest: None,
            identities,
            replay: false,
            occurred_at_unix_millis: now(),
        }
    }
    pub async fn finish(&mut self, deadline: Instant) -> CapabilityAuditDurability {
        if self.finished {
            return self.durability;
        }
        self.finished = true;
        let conclusion = self.conclusion(self.outcome);
        if let Some(attempt) = self.attempt.take() {
            let ticket = attempt.finish(conclusion).wait();
            self.durability = match tokio::time::timeout_at(deadline.into(), ticket).await {
                Ok(Ok(ack)) => CapabilityAuditDurability::Durable {
                    sequence: ack.sequence,
                },
                _ => CapabilityAuditDurability::OutcomeUnknown,
            };
        } else if self.observations && !self.required {
            self.observe(conclusion.identities);
        }
        self.durability
    }
    fn observe(&self, identities: AuditIdentities) {
        let _ = self.handle.try_capture(&AuditObservation {
            scope: self.record.scope.clone(),
            actor: self.record.actor.clone(),
            kind: Phase2AuditEventKind::CapabilityProviderOutcome,
            outcome: match self.outcome {
                AuditProviderOutcome::Rejected | AuditProviderOutcome::NotStarted => {
                    AuditOutcome::Denied
                }
                AuditProviderOutcome::Unknown => AuditOutcome::Failed,
                _ => AuditOutcome::Succeeded,
            },
            identities,
            reason: self.conclusion(self.outcome).reason,
            cache_kind: None,
            occurred_at_unix_millis: now(),
        });
    }
}
impl Drop for CallAudit {
    fn drop(&mut self) {
        if self.finished {
            return;
        }
        let conclusion = self.conclusion(self.outcome);
        if let Some(attempt) = self.attempt.take() {
            // The worker owns a prepaid terminal record after enqueue. Dropping
            // its acknowledgement future cannot remove accepted provider work.
            drop(attempt.finish(conclusion));
        } else if self.observations && !self.required {
            self.observe(conclusion.identities);
        }
    }
}
fn now() -> u64 {
    latent_core::ClockSample::system_now().unix_millis()
}
#[cfg(test)]
std::thread_local! {
    static AFTER_BEGIN: std::cell::RefCell<Option<Box<dyn FnOnce()>>> = const { std::cell::RefCell::new(None) };
}
#[cfg(test)]
pub(super) fn set_after_begin(action: impl FnOnce() + 'static) {
    AFTER_BEGIN.with(|hook| {
        assert!(hook.borrow_mut().replace(Box::new(action)).is_none());
    });
}
#[cfg(test)]
pub(super) fn after_begin() {
    let action = AFTER_BEGIN.with(|hook| hook.borrow_mut().take());
    if let Some(action) = action {
        action();
    }
}
