use latent_capabilities::namespace::{CallerScope, RecoverySelection};
use latent_commit::atomic::{
    inspect, AdmissionDecision, AtomicError, CompleteEnvelope, Outcome, PreparedAdmission,
};
use latent_core::{InvocationPrincipal, Metadata, PrincipalKind, TenantId};
use latent_state::{
    embedded::Family,
    session::{SessionLimits, StateMode, StateScope, StateSession},
};

use super::{fixture::*, poll, waiting};
use crate::command_waiters::*;

#[test]
fn current_caller_and_result_authorization_precede_every_notification_observation() {
    let fixture = Fixture::new();
    let registry = CommandWaiterRegistry::new(CommandWaiterConfig::default()).unwrap();
    let claim = fixture.claim("permission");
    let owner = registry.register(&claim).unwrap();
    let record = fixture.lookup("permission").0;
    let before = registry.snapshot().unwrap();
    assert!(matches!(
        registry.attach(&record, |_| Err(AtomicError::PermissionDenied)),
        Err(CommandWaiterError::Authorization(
            AtomicError::PermissionDenied
        ))
    ));
    assert_eq!(registry.snapshot().unwrap(), before);
    let mut waiter = waiting(registry.attach(&record, authorize).unwrap());
    fixture.commit(claim, false);
    owner.notify_reload();
    assert!(poll(&mut waiter, std::task::Waker::noop()).is_ready());
    // An already accepted delivery notification never grants cached-result access.
    assert!(matches!(
        inspect(
            &fixture.store.snapshot().unwrap(),
            record.key(),
            time(102),
            |_, _| Err(AtomicError::PermissionDenied)
        ),
        Err(AtomicError::PermissionDenied)
    ));
    let terminal = fixture.lookup("permission").0;
    assert!(matches!(
        registry.attach(&terminal, |_| Err(AtomicError::PermissionDenied)),
        Err(CommandWaiterError::Authorization(
            AtomicError::PermissionDenied
        ))
    ));
    assert!(matches!(
        registry.attach(&terminal, authorize).unwrap(),
        CommandWaiterDecision::ReloadDurableState
    ));
    assert_eq!(registry.snapshot().unwrap().waiters, 0);
}

#[test]
fn stable_subject_token_rotation_and_explicit_shared_scope_do_not_bypass_current_auth() {
    let principal = |subject: &str, token: &str, tenant: &str| InvocationPrincipal {
        subject: subject.into(),
        kind: PrincipalKind::User,
        tenant: Some(TenantId(tenant.into())),
        service: None,
        claims: Metadata::from([("transport-token".into(), token.into())]),
    };
    let original = CallerScope::derive(
        &principal("alice", "first", "tenant"),
        &RecoverySelection::OriginalCaller,
    )
    .unwrap();
    let rotated = CallerScope::derive(
        &principal("alice", "rotated", "tenant"),
        &RecoverySelection::OriginalCaller,
    )
    .unwrap();
    let bob = CallerScope::derive(
        &principal("bob", "second", "tenant"),
        &RecoverySelection::OriginalCaller,
    )
    .unwrap();
    let foreign = CallerScope::derive(
        &principal("alice", "first", "foreign"),
        &RecoverySelection::OriginalCaller,
    )
    .unwrap();
    assert_eq!(original.scope, rotated.scope);
    assert_ne!(original.scope, bob.scope);
    assert_ne!(original.scope, foreign.scope);
    let fixture = Fixture::new();
    let registry = CommandWaiterRegistry::new(CommandWaiterConfig::default()).unwrap();
    let mut source = input("stable-caller");
    source.key.recovery_scope.clone_from(&original.scope);
    let claim = fixture.claim_input(source);
    let owner = registry.register(&claim).unwrap();
    let record = claim.record().clone();
    let auth = |scope: &CallerScope, grant: bool| {
        if grant && scope.scope == record.key().recovery_scope && scope.owner_kind == "user" {
            Ok(())
        } else {
            Err(AtomicError::PermissionDenied)
        }
    };
    let waiter = waiting(registry.attach(&record, |_| auth(&rotated, true)).unwrap());
    for scope in [&bob, &foreign] {
        assert!(matches!(
            registry.attach(&record, |_| auth(scope, true)),
            Err(CommandWaiterError::Authorization(
                AtomicError::PermissionDenied
            ))
        ));
    }
    let shared = RecoverySelection::Shared {
        name: "reviewed-team".into(),
    };
    let alice_shared =
        CallerScope::derive(&principal("alice", "first", "tenant"), &shared).unwrap();
    let bob_shared = CallerScope::derive(&principal("bob", "second", "tenant"), &shared).unwrap();
    assert_eq!(alice_shared.scope, bob_shared.scope);
    // Equal descriptive scopes do not replace an explicit current sharing grant.
    assert!(matches!(
        registry.attach(&record, |_| auth(&bob_shared, false)),
        Err(CommandWaiterError::Authorization(
            AtomicError::PermissionDenied
        ))
    ));
    drop(waiter);
    drop(owner);
    drop(claim);
    assert_eq!(registry.snapshot().unwrap().waiters, 0);
}

#[test]
fn lost_commit_reopens_exact_original_source_without_a_second_claim_or_effect() {
    let fixture = Fixture::new();
    let registry = CommandWaiterRegistry::new(CommandWaiterConfig::default()).unwrap();
    let claim = fixture.claim("lost-response");
    let owner = registry.register(&claim).unwrap();
    let waiter = waiting(registry.attach(claim.record(), authorize).unwrap());
    let committed = fixture.commit(claim, true);
    // Lost transport destroys its own delivery slot, after durable commitment.
    drop(waiter);
    drop(owner);
    let path = fixture.dir.path().join("state.redb");
    drop(fixture.store);
    let reopened = open(&path);
    let view = reopened.snapshot().unwrap();
    let (record, result) = inspect(&view, committed.key(), time(102), permission).unwrap();
    assert_eq!(record, committed);
    assert_eq!(result.unwrap().value().unwrap().bytes, b"original-result");
    let mut rolled = input("lost-response");
    rolled.source.revision = "revision-2".into();
    rolled.source.route_generation = 2;
    let AdmissionDecision::Existing(existing) =
        PreparedAdmission::prepare(&view, rolled, time(103), permission).unwrap()
    else {
        panic!("compatible rollout must return the first source")
    };
    assert_eq!(existing.source().revision, "revision-1");
    assert_eq!(existing.effect_ids(), &[existing.effect_id(0)]);
    assert_eq!(
        view.scan(Family::Outbox, b"", 32, 1024 * 1024)
            .unwrap()
            .len(),
        1
    );
    assert!(matches!(
        registry.attach(&existing, authorize).unwrap(),
        CommandWaiterDecision::ReloadDurableState
    ));
}

#[test]
fn durable_rejection_and_expired_result_never_become_new_work() {
    let fixture = Fixture::new();
    let registry = CommandWaiterRegistry::new(CommandWaiterConfig::default()).unwrap();
    let claim = fixture.claim("rejection");
    let owner = registry.register(&claim).unwrap();
    let envelope = CompleteEnvelope::rejection(
        &fixture.store.snapshot().unwrap(),
        claim,
        "out-of-stock".into(),
        value(b"original-rejection"),
        time(101),
    )
    .unwrap();
    let rejected = fixture.publish(envelope);
    drop(owner);
    let change = fixture.claim("deliberate-state-change");
    let view = fixture.store.snapshot().unwrap();
    let scope = StateScope {
        tenant: TenantId("tenant".into()),
        namespace: latent_core::StateNamespaceId("namespace".into()),
        incarnation: 1,
        state_schema: change.record().source().state_schema.clone(),
        entity: None,
        mode: StateMode::Command,
    };
    let mut session =
        StateSession::open(&view, scope, SessionLimits::default(), |_, _| Ok(())).unwrap();
    session
        .put(&view, b"inventory".to_vec(), value(b"available"), |_, _| {
            Ok(())
        })
        .unwrap();
    let plan = session.seal(&view, |_, _| Ok(())).unwrap();
    fixture.publish(
        CompleteEnvelope::success(
            &view,
            change,
            Some(plan),
            vec![],
            value(b"changed"),
            &fixture.effects,
            time(102),
        )
        .unwrap(),
    );
    let (record, result) = fixture.lookup("rejection");
    assert_eq!(record.outcome(), Outcome::Rejected);
    assert_eq!(
        result.unwrap().value().unwrap().bytes,
        b"original-rejection"
    );
    assert!(matches!(
        registry.attach(&record, authorize).unwrap(),
        CommandWaiterDecision::ReloadDurableState
    ));
    let (protected, body) = inspect(
        &fixture.store.snapshot().unwrap(),
        rejected.key(),
        time(1100),
        permission,
    )
    .unwrap();
    assert!(body.is_none());
    assert_eq!(protected.id(), rejected.id());
    assert_eq!(protected.outcome(), Outcome::Rejected);
    assert!(matches!(
        registry.attach(&protected, authorize).unwrap(),
        CommandWaiterDecision::ReloadDurableState
    ));
    assert!(fixture
        .store
        .snapshot()
        .unwrap()
        .scan(Family::Outbox, b"", 32, 1024 * 1024)
        .unwrap()
        .is_empty());
}

#[test]
fn explicit_retry_generation_isolated_from_late_previous_notifications() {
    let fixture = Fixture::new();
    let registry = CommandWaiterRegistry::new(CommandWaiterConfig::default()).unwrap();
    let claim = fixture.claim("retry");
    let previous_notification = registry.register(&claim).unwrap();
    let retirement = claim.retirement();
    let work = claim.physical_work().unwrap();
    let mut old_waiter = waiting(registry.attach(claim.record(), authorize).unwrap());
    drop(claim);
    work.retire();
    let envelope = CompleteEnvelope::technical_abort(
        &fixture.store.snapshot().unwrap(),
        retirement.proven_noncommit().unwrap(),
        "conflict".into(),
        time(101),
    )
    .unwrap();
    let aborted = fixture.publish(envelope);
    let request = crate::transaction_runtime::command_completion::CommandRetry::new(
        "explicit-retry".into(),
        latent_core::transaction_contract::AbortFence {
            command_id: aborted.id().hex(),
            attempt_id: aborted.attempt_id().hex(),
            transaction_id: aborted.transaction_id().hex(),
            owner_fence: aborted.abort_proof().unwrap().bytes().to_vec(),
        },
    )
    .unwrap();
    let view = fixture.store.snapshot().unwrap();
    let AdmissionDecision::New(prepared) = request
        .prepare(&view, &input("retry"), time(102), permission)
        .unwrap()
    else {
        panic!("explicit proven-abort retry obtains one new claim")
    };
    let claim = prepared.publish(&fixture.store, || Ok(())).unwrap();
    assert_eq!(claim.record().attempt(), 2);
    let current_notification = registry.register(&claim).unwrap();
    let mut current_waiter = waiting(registry.attach(claim.record(), authorize).unwrap());
    let AdmissionDecision::Existing(duplicate) = request
        .prepare(
            &fixture.store.snapshot().unwrap(),
            &input("retry"),
            time(102),
            permission,
        )
        .unwrap()
    else {
        panic!("duplicate explicit retry cannot schedule twice")
    };
    assert_eq!(duplicate.attempt_id(), claim.record().attempt_id());
    previous_notification.notify_reload();
    assert_eq!(
        poll(&mut old_waiter, std::task::Waker::noop()),
        std::task::Poll::Ready(Ok(CommandNotification::ReloadDurableState))
    );
    assert!(poll(&mut current_waiter, std::task::Waker::noop()).is_pending());
    // Finish the new attempt with its current time; the late hint has not changed it.
    let envelope = CompleteEnvelope::success(
        &fixture.store.snapshot().unwrap(),
        claim,
        None,
        vec![],
        value(b"retry-result"),
        &fixture.effects,
        time(103),
    )
    .unwrap();
    let committed = fixture.publish(envelope);
    current_notification.notify_reload();
    assert!(poll(&mut current_waiter, std::task::Waker::noop()).is_ready());
    assert_eq!(committed.attempt(), 2);
    assert_eq!(committed.outcome(), Outcome::Committed);
    assert!(committed.effect_ids().is_empty());
    assert_eq!(registry.snapshot().unwrap().waiters, 0);
}

#[test]
fn reopened_pending_and_unproven_clock_never_authorize_a_new_driver_or_result() {
    let fixture = Fixture::new();
    let claim = fixture.claim("interrupted");
    let identity = claim.record().clone();
    drop(claim);
    let path = fixture.dir.path().join("state.redb");
    drop(fixture.store);
    let reopened = open(&path);
    let registry = CommandWaiterRegistry::new(CommandWaiterConfig::default()).unwrap();
    let view = reopened.snapshot().unwrap();
    let (record, result) = inspect(&view, identity.key(), time(102), permission).unwrap();
    assert_eq!(record.outcome(), Outcome::Pending);
    assert!(result.is_none());
    assert!(matches!(
        registry.attach(&record, authorize).unwrap(),
        CommandWaiterDecision::RecoveryRequired
    ));
    let AdmissionDecision::Existing(existing) =
        PreparedAdmission::prepare(&view, input("interrupted"), time(102), permission).unwrap()
    else {
        panic!("recovery must not create another executor claim")
    };
    assert_eq!(existing.attempt_id(), identity.attempt_id());
    for uncertain in [
        latent_commit::atomic::CommandTime {
            unix_millis: 102,
            continuity_proven: false,
        },
        time(99),
    ] {
        assert!(matches!(
            inspect(&view, identity.key(), uncertain, permission),
            Err(AtomicError::RecoveryRequired)
        ));
    }
    assert_eq!(registry.snapshot().unwrap().owners, 0);
    assert!(view
        .scan(Family::Outbox, b"", 32, 1024 * 1024)
        .unwrap()
        .is_empty());
}

#[test]
fn expired_body_with_pending_effect_retains_original_identity_and_never_notifies_a_retry() {
    let fixture = Fixture::new();
    let registry = CommandWaiterRegistry::new(CommandWaiterConfig::default()).unwrap();
    let claim = fixture.claim("pending-effect");
    let owner = registry.register(&claim).unwrap();
    let committed = fixture.commit(claim, true);
    owner.notify_reload();
    let view = fixture.store.snapshot().unwrap();
    let (record, result) = inspect(&view, committed.key(), time(2000), permission).unwrap();
    assert!(result.is_none());
    assert_eq!(record.effect_ids(), &[committed.effect_id(0)]);
    assert_eq!(record.identity_expires(), 2100);
    assert_eq!(
        view.scan(Family::Outbox, b"", 32, 1024 * 1024)
            .unwrap()
            .len(),
        1
    );
    assert!(matches!(
        registry.attach(&record, authorize).unwrap(),
        CommandWaiterDecision::ReloadDurableState
    ));
    let AdmissionDecision::Existing(existing) =
        PreparedAdmission::prepare(&view, input("pending-effect"), time(2000), permission).unwrap()
    else {
        panic!("body expiry never releases a protected command identity")
    };
    assert_eq!(existing.id(), committed.id());
    assert_eq!(existing.outcome(), Outcome::Committed);
    assert_eq!(registry.snapshot().unwrap().owners, 0);
}
