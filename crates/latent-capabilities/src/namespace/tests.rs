use super::*;
use latent_core::{InvocationPrincipal, Metadata, PrincipalKind, ServiceId};

#[cfg(target_os = "linux")]
mod authority;

fn principal(subject: &str) -> InvocationPrincipal {
    InvocationPrincipal {
        subject: subject.into(),
        kind: PrincipalKind::User,
        tenant: Some(TenantId("a".into())),
        service: None,
        claims: Metadata::new(),
    }
}

#[test]
fn stable_caller_identity_ignores_token_rotation_and_rejects_claimed_shared_scope() {
    let mut actor = principal("alice");
    let scope = CallerScope::derive(&actor, &RecoverySelection::OriginalCaller).unwrap();
    actor.claims.insert("token-id".into(), "rotated".into());
    actor
        .claims
        .insert("recovery-scope".into(), "shared-admin".into());
    actor.claims.insert("tenant".into(), "b".into());
    assert_eq!(
        CallerScope::derive(&actor, &RecoverySelection::OriginalCaller).unwrap(),
        scope
    );
    assert_ne!(
        CallerScope::derive(&principal("bob"), &RecoverySelection::OriginalCaller)
            .unwrap()
            .scope,
        scope.scope
    );
    actor.tenant = Some(TenantId("b".into()));
    assert_ne!(
        CallerScope::derive(&actor, &RecoverySelection::OriginalCaller)
            .unwrap()
            .scope,
        scope.scope
    );
    actor.kind = PrincipalKind::Anonymous;
    assert!(CallerScope::derive(
        &actor,
        &RecoverySelection::Shared {
            name: "admin".into()
        }
    )
    .is_err());
}

#[test]
fn delegation_service_and_shared_domains_require_explicit_distinct_policy_tuples() {
    let actor = principal("alice");
    assert!(CallerScope::derive(&actor, &RecoverySelection::ServiceIntegration).is_err());
    let caller = CallerScope::derive(&actor, &RecoverySelection::OriginalCaller).unwrap();
    let delegated = CallerScope::derive(
        &actor,
        &RecoverySelection::Delegated {
            delegation: "grant-1".into(),
            service: "integration".into(),
        },
    )
    .unwrap();
    let replaced = CallerScope::derive(
        &actor,
        &RecoverySelection::Delegated {
            delegation: "grant-2".into(),
            service: "integration".into(),
        },
    )
    .unwrap();
    let shared = CallerScope::derive(
        &actor,
        &RecoverySelection::Shared {
            name: "team".into(),
        },
    )
    .unwrap();
    assert_ne!(caller.scope, delegated.scope);
    assert_ne!(delegated.scope, replaced.scope);
    assert_ne!(delegated.scope, shared.scope);
    assert_eq!(
        shared.scope,
        CallerScope::derive(
            &principal("bob"),
            &RecoverySelection::Shared {
                name: "team".into()
            }
        )
        .unwrap()
        .scope
    );
    let mut service = actor;
    service.kind = PrincipalKind::Service;
    service.service = Some(ServiceId("integration".into()));
    assert_ne!(
        CallerScope::derive(&service, &RecoverySelection::ServiceIntegration)
            .unwrap()
            .scope,
        caller.scope
    );
}

#[test]
fn cancellation_control_keeps_its_actual_owner_and_never_revives_a_closed_gate() {
    let gate = gate::Gate::new();
    let control = CommitCancellation {
        gate: Arc::clone(&gate),
    };
    assert!(control.request());
    assert!(gate.check().is_err());
    assert!(!control.request());
    let other = gate::Gate::new();
    assert!(other.check().is_ok());
    assert!(CommitCancellation { gate: other }.request());
}
