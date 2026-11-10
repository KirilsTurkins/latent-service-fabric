use super::*;
use latent_state::{
    embedded::ExpectedRow,
    inbox_scope::{InboxScope, PreparedInboxScope},
};

fn scope() -> InboxScope {
    InboxScope {
        tenant: "tenant".into(),
        namespace: "aggregate".into(),
        incarnation: 1,
        processing_scope: "primary".into(),
        provider: "input".into(),
        stream: "orders".into(),
        stream_created: "2026-01-01T00:00:00Z".into(),
    }
}

fn request(scope: &InboxScope) -> AdmissionInput {
    let mut request = input("inbox-fenced");
    request.inbox = Some(InboxIdentity {
        provider: scope.provider.clone(),
        binding: scope.input_binding().unwrap(),
        message: "1".into(),
        payload_digest: Identity::derive(b"input", &[b"message"]),
    });
    request
}

fn install(store: &EmbeddedStore, scope: &InboxScope) -> ExpectedRow {
    let view = store.snapshot().unwrap();
    let plan = PreparedInboxScope::prepare(&view, scope).unwrap();
    drop(view);
    store.apply(plan.into_batch()).unwrap();
    latent_state::inbox_scope::require_existing(&store.snapshot().unwrap(), scope).unwrap()
}

fn damage(store: &EmbeddedStore, expected: &ExpectedRow) {
    store
        .apply(AtomicBatch {
            expectations: vec![expected.clone()],
            mutations: vec![RowMutation {
                key: expected.key.clone(),
                value: Some(b"damaged".to_vec()),
            }],
        })
        .unwrap();
}

#[test]
fn duplicate_recovery_refuses_a_view_expired_during_clock_or_authorization() {
    for delay_authorization in [false, true] {
        let (dir, store, _effects) = accounted::setup(8);
        drop(store);
        let store = open_limited(
            &dir.path().join("state.redb"),
            StoreLimits {
                maximum_view_age: std::time::Duration::from_secs(1),
                ..StoreLimits::default()
            },
        );
        let scope = scope();
        install(&store, &scope);
        let view = store.snapshot().unwrap();
        let AdmissionDecision::New(first) =
            PreparedAdmission::prepare(&view, request(&scope), time(100), permission).unwrap()
        else {
            panic!("new")
        };
        let AdmissionDecision::New(second) =
            PreparedAdmission::prepare(&view, request(&scope), time(100), permission).unwrap()
        else {
            panic!("new")
        };
        let first = first.fence_inbox_scope(&view, &scope).unwrap();
        let second = second.fence_inbox_scope(&view, &scope).unwrap();
        drop(view);
        let claim = first.publish(&store, || Ok(())).unwrap();
        match second.publish_or_existing(
            &store,
            || {
                if !delay_authorization {
                    std::thread::sleep(std::time::Duration::from_millis(1100));
                }
                Ok(time(101))
            },
            || Ok(()),
            |access, record| {
                if delay_authorization {
                    std::thread::sleep(std::time::Duration::from_millis(1100));
                }
                permission(access, record)
            },
        ) {
            Err(error) => assert_eq!(error, AtomicError::Expired),
            Ok(PublishedAdmission::Existing(_)) => {
                panic!("expired view returned an existing claim")
            }
            Ok(PublishedAdmission::New(_)) => panic!("conflicting claim was published"),
        }
        drop(claim);
    }
}

#[test]
fn missing_or_changed_source_cannot_publish_pending_or_recover_a_cas_winner() {
    let (_dir, store, _effects) = accounted::setup(8);
    let scope = scope();
    let view = store.snapshot().unwrap();
    let initial = request(&scope);
    assert!(matches!(
        verify_inbox_scope(&view, &initial.key, initial.inbox.as_ref().unwrap(), &scope),
        Err(AtomicError::Conflict)
    ));
    drop(view);
    let source = install(&store, &scope);
    let view = store.snapshot().unwrap();
    let AdmissionDecision::New(first) =
        PreparedAdmission::prepare(&view, request(&scope), time(100), permission).unwrap()
    else {
        panic!("new")
    };
    let AdmissionDecision::New(second) =
        PreparedAdmission::prepare(&view, request(&scope), time(100), permission).unwrap()
    else {
        panic!("new")
    };
    let first = first.fence_inbox_scope(&view, &scope).unwrap();
    let second = second.fence_inbox_scope(&view, &scope).unwrap();
    drop(view);
    let claim = first.publish(&store, || Ok(())).unwrap();
    damage(&store, &source);
    assert!(matches!(
        second.publish_or_existing(&store, || Ok(time(101)), || Ok(()), permission),
        Err(AtomicError::Conflict)
    ));
    let view = store.snapshot().unwrap();
    assert!(matches!(
        verify_inbox_scope(
            &view,
            &request(&scope).key,
            request(&scope).inbox.as_ref().unwrap(),
            &scope
        ),
        Err(AtomicError::Corrupt)
    ));
    drop(claim);
}

#[test]
fn disposition_writer_rechecks_original_source_in_its_atomic_envelope() {
    let (_dir, store, _effects) = accounted::setup(8);
    let scope = scope();
    let source = install(&store, &scope);
    let view = store.snapshot().unwrap();
    let AdmissionDecision::New(prepared) =
        PreparedAdmission::prepare(&view, request(&scope), time(100), permission).unwrap()
    else {
        panic!("new")
    };
    let prepared = prepared.fence_inbox_scope(&view, &scope).unwrap();
    drop(view);
    let claim = prepared.publish(&store, || Ok(())).unwrap();
    let view = store.snapshot().unwrap();
    let envelope =
        CompleteEnvelope::rejection(&view, claim, "rejected".into(), value(b"no"), time(101))
            .unwrap();
    drop(view);
    damage(&store, &source);
    assert!(matches!(
        envelope.publish(&store, |_| Ok(())),
        PreparedDisposition::KnownNotCommitted {
            reason: AtomicError::Conflict,
            ..
        }
    ));
    let view = store.snapshot().unwrap();
    let (record, result) = inspect(&view, &request(&scope).key, time(102), permission).unwrap();
    assert_eq!(record.outcome(), Outcome::Pending);
    assert!(result.is_none());
}

#[test]
fn physical_retirement_preserves_the_source_fence_for_technical_abort() {
    let (_dir, store, _effects) = accounted::setup(8);
    let scope = scope();
    let source = install(&store, &scope);
    let view = store.snapshot().unwrap();
    let AdmissionDecision::New(prepared) =
        PreparedAdmission::prepare(&view, request(&scope), time(100), permission).unwrap()
    else {
        panic!("new")
    };
    let prepared = prepared.fence_inbox_scope(&view, &scope).unwrap();
    drop(view);
    let claim = prepared.publish(&store, || Ok(())).unwrap();
    let retirement = claim.retirement();
    drop(claim);
    let retired = retirement.proven_noncommit().unwrap();
    damage(&store, &source);
    let view = store.snapshot().unwrap();
    assert!(matches!(
        CompleteEnvelope::technical_abort(&view, retired, "transient".into(), time(101)),
        Err(AtomicError::Conflict)
    ));
}
