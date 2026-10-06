use super::*;
use latent_effects::{authority::DurableEffectAuthority, dispatch::EffectRecord};

fn rule(authority: &DurableEffectAuthority) -> EffectRule {
    EffectRule {
        scope: authority.scope().clone(),
        profile: authority.profile().clone(),
        policy_revision: 2,
        credential_epoch: 2,
        protected_credential_reference: "rotated-protected-events".into(),
        ceiling: authority.ceiling(),
        enabled: true,
    }
}

fn publish(
    envelope: CompleteEnvelope,
    store: &EmbeddedStore,
    effects: &EffectAuthorityOwner,
) -> CommandRecord {
    let PreparedDisposition::Confirmed { command, .. } = envelope.publish(store, |authorities| {
        let fence = effects.commit_fence(
            authorities,
            EffectTime {
                unix_millis: 201,
                continuity_proven: true,
            },
        )?;
        drop(fence);
        Ok(())
    }) else {
        panic!("expected durable captured disposition");
    };
    command
}

fn stored_effect(store: &EmbeddedStore, effect: &str) -> DurableEffectAuthority {
    let bytes = store
        .snapshot()
        .unwrap()
        .get(&latent_effects::dispatch_store::effect_row_key(effect).unwrap())
        .unwrap()
        .unwrap();
    EffectRecord::decode(&bytes).unwrap().authority().unwrap()
}

#[test]
fn stage_grant_widening_and_credential_rotation_never_expand_durable_commit_authority() {
    let (dir, store, effects) = setup();
    let admitted = claim(&store, input("captured-widen"));
    let captured = admitted
        .intent_capture_context()
        .capture(0, intent(), &effects, time(100))
        .unwrap();
    let effect = captured.authority().link().effect.clone();
    let original = captured.authority().ceiling();
    let expires = captured.authority().expires_at_millis();
    let mut current = rule(captured.authority());
    current.ceiling.maximum_payload_bytes = 2048;
    current.ceiling.maximum_response_bytes = 2048;
    current.ceiling.maximum_attempts = 5;
    current.ceiling.maximum_age_millis = 2000;
    current.ceiling.attempt_timeout_millis = 200;
    effects.publish(current).unwrap();
    let view = store.snapshot().unwrap();
    let envelope = CompleteEnvelope::success_captured(
        &view,
        admitted,
        Some(stage(&view)),
        vec![captured],
        value(b"ok"),
        &effects,
        time(200),
    )
    .unwrap();
    let committed = publish(envelope, &store, &effects);
    let persisted = stored_effect(&store, &effect);
    assert_eq!(
        persisted.ceiling().maximum_payload_bytes,
        original.maximum_payload_bytes
    );
    assert_eq!(
        persisted.ceiling().maximum_attempts,
        original.maximum_attempts
    );
    assert_eq!(
        persisted.ceiling().attempt_timeout_millis,
        original.attempt_timeout_millis
    );
    assert_eq!(persisted.ceiling().maximum_age_millis, 900);
    assert_eq!(persisted.expires_at_millis(), expires);
    assert_eq!(persisted.committed_at_millis(), 200);
    assert_eq!(persisted.link().command, committed.id().hex());
    drop(view);
    drop(store);
    let reopened = open(&dir.path().join("state.redb"));
    validate_view(&reopened.snapshot().unwrap(), foreign_codec).unwrap();
    assert_eq!(stored_effect(&reopened, &effect), persisted);
}

#[test]
fn stage_grant_narrowing_before_prepare_is_frozen_in_the_complete_engine_envelope() {
    let (_dir, store, effects) = setup();
    let admitted = claim(&store, input("captured-narrow"));
    let captured = admitted
        .intent_capture_context()
        .capture(0, intent(), &effects, time(100))
        .unwrap();
    let effect = captured.authority().link().effect.clone();
    let mut current = rule(captured.authority());
    current.ceiling.maximum_payload_bytes = 512;
    current.ceiling.maximum_response_bytes = 256;
    current.ceiling.maximum_attempts = 2;
    current.ceiling.maximum_age_millis = 300;
    current.ceiling.attempt_timeout_millis = 50;
    effects.publish(current).unwrap();
    let view = store.snapshot().unwrap();
    let envelope = CompleteEnvelope::success_captured(
        &view,
        admitted,
        Some(stage(&view)),
        vec![captured],
        value(b"ok"),
        &effects,
        time(200),
    )
    .unwrap();
    publish(envelope, &store, &effects);
    let persisted = stored_effect(&store, &effect);
    assert_eq!(persisted.ceiling().maximum_payload_bytes, 512);
    assert_eq!(persisted.ceiling().maximum_response_bytes, 256);
    assert_eq!(persisted.ceiling().maximum_attempts, 2);
    assert_eq!(persisted.ceiling().attempt_timeout_millis, 50);
    assert_eq!(persisted.expires_at_millis(), 500);
    validate_view(&store.snapshot().unwrap(), foreign_codec).unwrap();
}

#[test]
fn revoked_staged_effect_prevents_any_business_envelope_or_outbox_row() {
    let (_dir, store, effects) = setup();
    let admitted = claim(&store, input("captured-revoked"));
    let captured = admitted
        .intent_capture_context()
        .capture(0, intent(), &effects, time(100))
        .unwrap();
    let mut current = rule(captured.authority());
    current.enabled = false;
    effects.publish(current).unwrap();
    let view = store.snapshot().unwrap();
    assert!(matches!(
        CompleteEnvelope::success_captured(
            &view,
            admitted,
            Some(stage(&view)),
            vec![captured],
            value(b"ok"),
            &effects,
            time(200)
        ),
        Err(AtomicError::PermissionDenied)
    ));
    assert_eq!(
        view.scan(Family::Outbox, b"", 128, 2 * 1024 * 1024)
            .unwrap()
            .len(),
        0
    );
    assert_eq!(
        view.scan(Family::State, b"", 128, 2 * 1024 * 1024)
            .unwrap()
            .len(),
        0
    );
}

#[test]
fn captured_intent_cannot_be_rebound_to_a_different_original_pending_claim() {
    let (_dir, store, effects) = setup();
    let first = claim(&store, input("captured-first"));
    let captured = first
        .intent_capture_context()
        .capture(0, intent(), &effects, time(100))
        .unwrap();
    let second = claim(&store, input("captured-second"));
    let view = store.snapshot().unwrap();
    assert!(matches!(
        CompleteEnvelope::success_captured(
            &view,
            second,
            None,
            vec![captured],
            value(b"ok"),
            &effects,
            time(200)
        ),
        Err(AtomicError::PermissionDenied)
    ));
    assert_eq!(
        view.scan(Family::Outbox, b"", 128, 2 * 1024 * 1024)
            .unwrap()
            .len(),
        0
    );
    assert_eq!(first.record().outcome(), Outcome::Pending);
}

#[test]
fn final_rule_narrowing_rejects_writer_acceptance_and_preserves_pending_owner() {
    let (_dir, store, effects) = setup();
    let admitted = claim(&store, input("captured-final-fence"));
    let key = admitted.record().key().clone();
    let captured = admitted
        .intent_capture_context()
        .capture(0, intent(), &effects, time(100))
        .unwrap();
    let mut current = rule(captured.authority());
    let view = store.snapshot().unwrap();
    let envelope = CompleteEnvelope::success_captured(
        &view,
        admitted,
        Some(stage(&view)),
        vec![captured],
        value(b"ok"),
        &effects,
        time(200),
    )
    .unwrap();
    current.ceiling.maximum_attempts = 1;
    effects.publish(current).unwrap();
    let PreparedDisposition::KnownNotCommitted { command, reason } =
        envelope.publish(&store, |authorities| {
            let fence = effects.commit_fence(
                authorities,
                EffectTime {
                    unix_millis: 201,
                    continuity_proven: true,
                },
            )?;
            drop(fence);
            Ok(())
        })
    else {
        panic!("final authority change must remain proven precommit");
    };
    assert_eq!(reason, AtomicError::PermissionDenied);
    assert_eq!(command.record().outcome(), Outcome::Pending);
    assert_eq!(
        inspect(&store.snapshot().unwrap(), &key, time(201), permission)
            .unwrap()
            .0
            .outcome(),
        Outcome::Pending
    );
    assert_eq!(
        store
            .snapshot()
            .unwrap()
            .scan(Family::Outbox, b"", 128, 2 * 1024 * 1024)
            .unwrap()
            .len(),
        0
    );
}

#[test]
fn staged_expiry_and_unproven_time_cannot_gain_a_new_lifetime_during_commit() {
    for final_time in [
        time(1100),
        CommandTime {
            unix_millis: 200,
            continuity_proven: false,
        },
    ] {
        let (_dir, store, effects) = setup();
        let admitted = claim(&store, input("captured-expiry"));
        let captured = admitted
            .intent_capture_context()
            .capture(0, intent(), &effects, time(100))
            .unwrap();
        let view = store.snapshot().unwrap();
        assert!(matches!(
            CompleteEnvelope::success_captured(
                &view,
                admitted,
                None,
                vec![captured],
                value(b"ok"),
                &effects,
                final_time
            ),
            Err(AtomicError::Expired | AtomicError::RecoveryRequired)
        ));
        assert_eq!(
            view.scan(Family::Outbox, b"", 128, 2 * 1024 * 1024)
                .unwrap()
                .len(),
            0
        );
    }
}
