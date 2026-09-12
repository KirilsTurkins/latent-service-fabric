//! Diagnostics after checked persistent lookup, outside eligibility fences.
use crate::aot::AotCompatibilityKey;
use latent_artifacts::LifecycleScope;
use latent_audit::{
    AuditActorIdentity, AuditActorKind, AuditCacheKind, AuditHandle, AuditIdentities,
    AuditObservation, AuditOutcome, AuditReason, AuditScope, Phase2AuditEventKind,
};
use latent_core::ReleaseDigest;

#[derive(Clone, Copy)]
pub(super) enum Event {
    Hit,
    Miss,
    Corrupt,
}

pub(super) fn capture(handle: Option<&AuditHandle>, key: &AotCompatibilityKey, event: Event) {
    let Some(handle) = handle else { return };
    // The input key is private-constructor provenance from the exact catalog
    // source. No cache filename or unverified receipt contributes identities.
    // Admission is fail-fast and lossy; its result cannot change preparation.
    let _ = handle.try_capture(&observation(key, event));
}

fn observation(key: &AotCompatibilityKey, event: Event) -> AuditObservation {
    let (kind, outcome, reason) = match event {
        Event::Hit => (
            Phase2AuditEventKind::CacheHit,
            AuditOutcome::Succeeded,
            AuditReason::CacheHit,
        ),
        Event::Miss => (
            Phase2AuditEventKind::CacheMiss,
            AuditOutcome::Succeeded,
            AuditReason::CacheMiss,
        ),
        Event::Corrupt => (
            Phase2AuditEventKind::CacheCorruption,
            AuditOutcome::Failed,
            AuditReason::CacheCorruption,
        ),
    };
    AuditObservation {
        scope: match key.scope() {
            LifecycleScope::Tenant(tenant) => AuditScope::Tenant(tenant.clone()),
            LifecycleScope::LocalUnscoped => AuditScope::Node,
        },
        actor: AuditActorIdentity {
            kind: AuditActorKind::Host,
            subject: "native-aot-cache".into(),
        },
        kind,
        outcome,
        identities: AuditIdentities {
            component: Some(ReleaseDigest(key.component().as_str().into())),
            package: key.package().cloned(),
            ..AuditIdentities::default()
        },
        reason,
        cache_kind: Some(AuditCacheKind::Native),
        occurred_at_unix_millis: std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .ok()
            .and_then(|duration| u64::try_from(duration.as_millis()).ok())
            .unwrap_or(0),
    }
}

#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
mod tests;
