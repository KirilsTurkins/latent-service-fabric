use super::*;
use crate::atomic::record::result_row_key;

mod clocks;
mod ownership;

fn observation(now: u64, elapsed: u64) -> MaintenanceClock {
    MaintenanceClock {
        time: time(now),
        boot: [7; 32],
        monotonic_millis: elapsed,
    }
}
fn maintenance(record: Option<&CommandRecord>) -> Result<(), AtomicError> {
    permission(CommandAccess::Replay, record)
}
fn completed(store: &EmbeddedStore, effects: &EffectAuthorityOwner, key: &str) -> CommandRecord {
    let mut request = input(key);
    request.inbox = Some(InboxIdentity {
        provider: "events".into(),
        binding: "inbox".into(),
        message: key.into(),
        payload_digest: Identity::derive(b"test-input", &[key.as_bytes()]),
    });
    let owner = claim(store, request);
    let view = store.snapshot().unwrap();
    confirm(
        CompleteEnvelope::success(
            &view,
            owner,
            None,
            vec![intent()],
            value(&[42; 512]),
            effects,
            time(101),
        )
        .unwrap(),
        store,
        effects,
    )
}
fn result_bytes(store: &EmbeddedStore, record: &CommandRecord) -> Vec<u8> {
    store
        .snapshot()
        .unwrap()
        .get(&result_row_key(record.id, record.attempt))
        .unwrap()
        .unwrap()
}

#[test]
fn response_expiry_preserves_uncertain_effect_inbox_source_and_original_key_after_reopen() {
    let (dir, mut store, effects) = setup();
    let record = completed(&store, &effects, "linked-expiry");
    let old = store.snapshot().unwrap();
    let effect_key =
        latent_effects::dispatch_store::effect_row_key(&record.effects[0].hex()).unwrap();
    let payload_key =
        latent_effects::dispatch_store::effect_payload_key(&record.effects[0].hex()).unwrap();
    let inbox_key = record.inbox.as_ref().unwrap().row_key(&record.key).unwrap();
    let linked = [effect_key, payload_key, inbox_key, namespace_key()];
    let before: Vec<_> = linked.iter().map(|key| old.get(key).unwrap()).collect();
    let old_body = old
        .get(&result_row_key(record.id, record.attempt))
        .unwrap()
        .unwrap();
    let owner = ResultMaintenanceOwner::default();
    owner
        .anchor(&store, None, observation(1000, 0), maintenance)
        .unwrap();
    let progress = owner
        .step(&store, observation(1100, 100), maintenance)
        .unwrap();
    assert_eq!((progress.visited, progress.retired), (1, 1));
    let marker = result_bytes(&store, &record);
    assert!(marker.starts_with(b"LCE\0\x01"));
    assert_eq!(
        progress.reclaimed_bytes,
        (old_body.len() - marker.len()) as u64
    );
    assert_eq!(
        old.get(&result_row_key(record.id, record.attempt)).unwrap(),
        Some(old_body)
    );
    assert_eq!(
        store.compact(),
        Err(latent_state::embedded::StoreError::Capacity)
    );
    let current = store.snapshot().unwrap();
    for (key, bytes) in linked.iter().zip(before) {
        assert_eq!(current.get(key).unwrap(), bytes);
    }
    let (protected, response) = inspect(&current, &record.key, time(1100), permission).unwrap();
    assert!(response.is_none());
    assert_eq!(protected.source, record.source);
    assert_eq!(protected.fingerprint, record.fingerprint);
    assert_eq!(protected.result_policy, record.result_policy);
    assert_eq!(protected.effects, record.effects);
    assert_eq!(protected.identity_expires, record.identity_expires);
    drop(current);
    drop(old);
    drop(store);
    let reopened = open(&dir.path().join("state.redb"));
    let view = reopened.snapshot().unwrap();
    validate_view(&view, foreign_codec).unwrap();
    let mut redelivery = input("linked-expiry");
    redelivery.inbox = record.inbox.clone();
    assert!(matches!(
        PreparedAdmission::prepare(&view, redelivery, time(2200), permission),
        Ok(AdmissionDecision::Existing(_))
    ));
    let mut changed = input("linked-expiry");
    changed.inbox = record.inbox;
    changed.fingerprint.input = value(b"changed");
    assert!(matches!(
        PreparedAdmission::prepare(&view, changed, time(2200), permission),
        Err(AtomicError::Conflict)
    ));
}

#[test]
fn current_policy_revocation_at_retention_fence_keeps_body_and_progress_unchanged() {
    let (_dir, store, effects) = setup();
    let record = completed(&store, &effects, "revoke-maintenance");
    let owner = ResultMaintenanceOwner::default();
    let initial = owner
        .anchor(&store, None, observation(1000, 0), maintenance)
        .unwrap();
    let body = result_bytes(&store, &record);
    let mut calls = 0;
    assert_eq!(
        owner.step(&store, observation(1100, 100), |record| {
            calls += 1;
            if calls == 3 {
                Err(AtomicError::PermissionDenied)
            } else {
                maintenance(record)
            }
        }),
        Err(AtomicError::PermissionDenied)
    );
    assert_eq!(calls, 3);
    assert_eq!(result_bytes(&store, &record), body);
    let checkpoint = store
        .snapshot()
        .unwrap()
        .get(&MaintenanceProgress::key())
        .unwrap()
        .unwrap();
    assert_eq!(MaintenanceProgress::decode(&checkpoint).unwrap(), initial);
}

#[test]
fn corrupt_missing_payload_dependency_refuses_reclamation_without_advancing_progress() {
    let (_dir, store, effects) = setup();
    let record = completed(&store, &effects, "missing-link");
    let owner = ResultMaintenanceOwner::default();
    let initial = owner
        .anchor(&store, None, observation(1000, 0), maintenance)
        .unwrap();
    let body = result_bytes(&store, &record);
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: latent_effects::dispatch_store::effect_payload_key(&record.effects[0].hex())
                    .unwrap(),
                value: None,
            }],
        })
        .unwrap();
    assert_eq!(
        owner.step(&store, observation(1100, 100), maintenance),
        Err(AtomicError::Corrupt)
    );
    assert_eq!(result_bytes(&store, &record), body);
    let checkpoint = store
        .snapshot()
        .unwrap()
        .get(&MaintenanceProgress::key())
        .unwrap()
        .unwrap();
    assert_eq!(MaintenanceProgress::decode(&checkpoint).unwrap(), initial);
}
