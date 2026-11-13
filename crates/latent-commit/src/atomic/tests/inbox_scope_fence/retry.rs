//! Explicit retry preserves source custody and the original physical abort fence.
use super::*;
use latent_state::embedded::ReadView;

fn settle(
    envelope: CompleteEnvelope,
    store: &EmbeddedStore,
    effects: &EffectAuthorityOwner,
    now: u64,
) -> CommandRecord {
    match envelope.publish(store, |authorities| {
        let fence = effects.commit_fence(
            authorities,
            EffectTime {
                unix_millis: now,
                continuity_proven: true,
            },
        )?;
        permission(CommandAccess::FinalDisposition, None)?;
        drop(fence);
        Ok(())
    }) {
        PreparedDisposition::Confirmed { command, .. } => *command,
        _ => panic!("expected a durable disposition"),
    }
}

fn aborted(
    store: &EmbeddedStore,
    effects: &EffectAuthorityOwner,
    scope: &InboxScope,
) -> CommandRecord {
    let view = store.snapshot().unwrap();
    let AdmissionDecision::New(plan) =
        PreparedAdmission::prepare(&view, request(scope), time(100), permission).unwrap()
    else {
        panic!("first input was already admitted");
    };
    let plan = plan.fence_inbox_scope(&view, scope).unwrap();
    drop(view);
    let claim = plan.publish(store, || Ok(())).unwrap();
    let retirement = claim.retirement();
    let physical = claim.physical_work().unwrap();
    drop(claim);
    assert!(retirement.proven_noncommit().is_err());
    physical.retire();
    let proof = retirement.proven_noncommit().unwrap();
    let view = store.snapshot().unwrap();
    let envelope =
        CompleteEnvelope::technical_abort(&view, proof, "transient".into(), time(101)).unwrap();
    drop(view);
    let command = settle(envelope, store, effects, 101);
    assert_eq!(command.outcome(), Outcome::Aborted);
    assert!(command.abort_proof().is_some());
    let inbox = command.inbox_identity().unwrap();
    let key = inbox.row_key(command.key()).unwrap();
    assert!(store.snapshot().unwrap().get(&key).unwrap().is_none());
    command
}

fn retry_request(original: &CommandRecord, id: &str) -> RetryRequest {
    RetryRequest {
        request_id: id.into(),
        expected_abort: original.abort_proof().unwrap(),
    }
}

fn prepare(
    view: &ReadView,
    scope: &InboxScope,
    retry: &RetryRequest,
    now: u64,
) -> PreparedAdmission {
    let AdmissionDecision::New(plan) =
        PreparedAdmission::retry(view, &request(scope), retry, time(now), permission).unwrap()
    else {
        panic!("expected a new explicit retry");
    };
    plan.fence_inbox_scope(view, scope).unwrap()
}

fn publish(
    plan: PreparedAdmission,
    store: &EmbeddedStore,
    scope: &InboxScope,
    retry: &RetryRequest,
    now: u64,
) -> AdmittedCommand {
    match plan
        .publish_retry_or_existing(
            store,
            &request(scope),
            retry,
            || Ok(time(now)),
            || Ok(()),
            permission,
        )
        .unwrap()
    {
        PublishedAdmission::New(claim) => claim,
        PublishedAdmission::Existing(_) => panic!("retry unexpectedly lost its claim"),
    }
}

#[test]
fn scoped_equal_retries_share_one_attempt_and_keep_original_source_and_expiry() {
    let (_dir, store, effects) = accounted::setup(8);
    let scope = scope();
    install(&store, &scope);
    let original = aborted(&store, &effects, &scope);
    let retry = retry_request(&original, "same-retry");
    let view = store.snapshot().unwrap();
    let first = prepare(&view, &scope, &retry, 102);
    let second = prepare(&view, &scope, &retry, 102);
    drop(view);
    let claim = publish(first, &store, &scope, &retry, 102);
    let PublishedAdmission::Existing(winner) = second
        .publish_retry_or_existing(
            &store,
            &request(&scope),
            &retry,
            || Ok(time(103)),
            || Ok(()),
            permission,
        )
        .unwrap()
    else {
        panic!("equal retry started a second owner");
    };
    assert_eq!(&winner, claim.record());
    assert_eq!(winner.attempt(), 2);
    assert_eq!(winner.source(), original.source());
    assert_eq!(winner.result_expires(), original.result_expires());
    assert_eq!(winner.identity_expires(), original.identity_expires());
    assert_eq!(winner.inbox_identity(), original.inbox_identity());
    let view = store.snapshot().unwrap();
    assert!(matches!(
        PreparedAdmission::retry(
            &view,
            &request(&scope),
            &retry_request(&original, "different-retry"),
            time(103),
            permission,
        ),
        Err(AtomicError::RecoveryRequired)
    ));
    let envelope = CompleteEnvelope::success(
        &view,
        claim,
        Some(stage(&view)),
        vec![intent()],
        value(b"once"),
        &effects,
        time(104),
    )
    .unwrap();
    drop(view);
    let committed = settle(envelope, &store, &effects, 104);
    let view = store.snapshot().unwrap();
    let AdmissionDecision::Existing(replay) =
        PreparedAdmission::retry(&view, &request(&scope), &retry, time(105), permission).unwrap()
    else {
        panic!("lost retry response admitted another guest");
    };
    assert_eq!(replay, committed);
    assert_eq!(
        view.get(&attempt_row_key(original.id(), 1)).unwrap(),
        Some(original.encode().unwrap())
    );
    for family in [
        Family::Command,
        Family::State,
        Family::Outbox,
        Family::Inbox,
    ] {
        assert_eq!(view.scan(family, b"", 16, 1024 * 1024).unwrap().len(), 1);
    }
}

#[test]
fn source_loss_refuses_scoped_retry_publication_and_cas_winner_recovery() {
    for winner_present in [false, true] {
        let (_dir, store, effects) = accounted::setup(8);
        let scope = scope();
        let source = install(&store, &scope);
        let original = aborted(&store, &effects, &scope);
        let retry = retry_request(&original, "source-fenced");
        let view = store.snapshot().unwrap();
        let first = prepare(&view, &scope, &retry, 102);
        let second = prepare(&view, &scope, &retry, 102);
        drop(view);
        let winner = winner_present.then(|| publish(first, &store, &scope, &retry, 102));
        damage(&store, &source);
        assert!(matches!(
            second.publish_retry_or_existing(
                &store,
                &request(&scope),
                &retry,
                || Ok(time(103)),
                || panic!("source mismatch reached final acceptance"),
                permission,
            ),
            Err(AtomicError::Conflict)
        ));
        let view = store.snapshot().unwrap();
        let retained =
            CommandRecord::decode(&view.get(&command_row_key(original.id())).unwrap().unwrap())
                .unwrap();
        assert_eq!(retained.attempt(), if winner_present { 2 } else { 1 });
        assert!(view.scan(Family::Inbox, b"", 16, 1024).unwrap().is_empty());
        drop(winner);
    }
}

#[test]
fn retry_source_fence_survives_final_disposition_and_physical_retirement() {
    for technical_abort in [false, true] {
        let (_dir, store, effects) = accounted::setup(8);
        let scope = scope();
        let source = install(&store, &scope);
        let original = aborted(&store, &effects, &scope);
        let retry = retry_request(&original, "terminal-fence");
        let view = store.snapshot().unwrap();
        let plan = prepare(&view, &scope, &retry, 102);
        drop(view);
        let claim = publish(plan, &store, &scope, &retry, 102);
        let view = store.snapshot().unwrap();
        let envelope = if technical_abort {
            let retirement = claim.retirement();
            drop(claim);
            CompleteEnvelope::technical_abort(
                &view,
                retirement.proven_noncommit().unwrap(),
                "transient".into(),
                time(103),
            )
        } else {
            CompleteEnvelope::rejection(&view, claim, "rejected".into(), value(b"no"), time(103))
        }
        .unwrap();
        drop(view);
        damage(&store, &source);
        assert!(matches!(
            envelope.publish(&store, |_| panic!(
                "changed source reached disposition fence"
            )),
            PreparedDisposition::KnownNotCommitted {
                reason: AtomicError::Conflict,
                ..
            }
        ));
        let (record, result) = inspect(
            &store.snapshot().unwrap(),
            original.key(),
            time(104),
            permission,
        )
        .unwrap();
        assert_eq!(record.outcome(), Outcome::Pending);
        assert_eq!(record.attempt(), 2);
        assert!(result.is_none());
    }
}

#[test]
fn scoped_retry_keeps_abort_proof_clock_and_original_attempt_limits() {
    let (_dir, store, effects) = accounted::setup(8);
    let scope = scope();
    install(&store, &scope);
    let original = aborted(&store, &effects, &scope);
    let mut retry = retry_request(&original, "bounded-retry");
    retry.expected_abort = Identity::derive(b"untrusted", &[b"proof"]);
    let view = store.snapshot().unwrap();
    assert!(matches!(
        PreparedAdmission::retry(&view, &request(&scope), &retry, time(102), permission),
        Err(AtomicError::RecoveryRequired)
    ));
    retry.expected_abort = original.abort_proof().unwrap();
    for observed in [
        time(original.result_expires()),
        CommandTime {
            unix_millis: 102,
            continuity_proven: false,
        },
    ] {
        assert!(
            PreparedAdmission::retry(&view, &request(&scope), &retry, observed, permission,)
                .is_err()
        );
    }
    drop(view);
    let mut previous = original;
    for attempt in 2..=3 {
        let retry = retry_request(&previous, &format!("attempt-{attempt}"));
        let view = store.snapshot().unwrap();
        let plan = prepare(&view, &scope, &retry, 100 + attempt * 2);
        drop(view);
        let claim = publish(plan, &store, &scope, &retry, 100 + attempt * 2);
        let retirement = claim.retirement();
        drop(claim);
        let view = store.snapshot().unwrap();
        let envelope = CompleteEnvelope::technical_abort(
            &view,
            retirement.proven_noncommit().unwrap(),
            "transient".into(),
            time(101 + attempt * 2),
        )
        .unwrap();
        drop(view);
        previous = settle(envelope, &store, &effects, 101 + attempt * 2);
    }
    assert!(matches!(
        PreparedAdmission::retry(
            &store.snapshot().unwrap(),
            &request(&scope),
            &retry_request(&previous, "one-too-many"),
            time(110),
            permission,
        ),
        Err(AtomicError::Expired)
    ));
    assert_eq!(previous.attempt(), 3);
    assert_eq!(previous.result_expires(), 1100);
}
