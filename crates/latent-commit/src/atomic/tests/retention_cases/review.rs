use super::*;
mod adversarial;
mod capacity;
mod release;
use latent_effects::{
    authority::EffectTime,
    dispatch::{AttemptReceipt, Disposition, EffectRecord},
    dispatch_store::DispatchCatalog,
};

fn effect_time(now: u64) -> EffectTime {
    EffectTime {
        unix_millis: now,
        continuity_proven: true,
    }
}
fn request(record: &CommandRecord) -> RetentionRequest {
    RetentionRequest {
        key: record.key.clone(),
        expected_command_digest: RetentionRequest::command_digest(record).unwrap(),
        actor: "operator:retention-fixture".into(),
        operation_id: "review-1".into(),
        policy: "closed/destructive-review-v1".into(),
        retain_until_millis: 2300,
        inbox_expires_at_millis: record.inbox.as_ref().map(|_| 2100),
    }
}
fn authorize(
    action: RetentionAction,
    request: &RetentionRequest,
    record: Option<&CommandRecord>,
) -> Result<(), AtomicError> {
    assert!(matches!(
        action,
        RetentionAction::Terminalize | RetentionAction::Purge
    ));
    if request.actor != "operator:retention-fixture"
        || request.policy != "closed/destructive-review-v1"
    {
        return Err(AtomicError::PermissionDenied);
    }
    maintenance(record)
}
fn anchor(owner: &ResultMaintenanceOwner, store: &EmbeddedStore) {
    owner
        .anchor(store, None, observation(2100, 0), maintenance)
        .unwrap();
}
fn uncertain(store: &EmbeddedStore, record: &CommandRecord) -> Vec<u8> {
    let epoch = DispatchCatalog::begin_exclusive_epoch(store, effect_time(102), None).unwrap();
    let view = store.snapshot().unwrap();
    let page = DispatchCatalog::due_page(&view, 102, None, 1, 4096).unwrap();
    assert_eq!(page.rows[0].effect, record.effects[0].hex());
    drop(view);
    let claim = DispatchCatalog::claim(store, epoch, &page.rows[0], effect_time(102)).unwrap();
    DispatchCatalog::begin_send(store, epoch, &claim.attempt, effect_time(103)).unwrap();
    assert_eq!(
        DispatchCatalog::complete(
            store,
            epoch,
            &claim.attempt,
            AttemptReceipt {
                disposition: Disposition::Uncertain,
                reason: "lost-response-after-send".into(),
                provider_receipt: None,
                observed_at_millis: 104,
            },
            None,
            effect_time(104)
        )
        .unwrap(),
        Disposition::Uncertain
    );
    let view = store.snapshot().unwrap();
    let history =
        DispatchCatalog::history_page(&view, &record.effects[0].hex(), None, 128, 4096).unwrap();
    assert_eq!(history.rows.len(), 1);
    history.rows[0].encode().unwrap()
}

#[test]
fn explicit_terminalization_keeps_real_uncertain_receipt_payload_inbox_and_original_identity() {
    let (_dir, store, effects) = setup();
    let record = completed(&store, &effects, "explicit-uncertain");
    let history = uncertain(&store, &record);
    let payload_key =
        latent_effects::dispatch_store::effect_payload_key(&record.effects[0].hex()).unwrap();
    let payload = store.snapshot().unwrap().get(&payload_key).unwrap();
    let owner = ResultMaintenanceOwner::default();
    anchor(&owner, &store);
    let request = request(&record);
    let result = owner
        .terminalize(&store, &request, observation(2200, 100), authorize)
        .unwrap();
    assert!(result.complete);
    assert_eq!((result.terminalized_effects, result.purged_effects), (1, 0));
    let view = store.snapshot().unwrap();
    let effect = EffectRecord::decode(
        &view
            .get(&latent_effects::dispatch_store::effect_row_key(&record.effects[0].hex()).unwrap())
            .unwrap()
            .unwrap(),
    )
    .unwrap();
    assert_eq!(effect.disposition(), Disposition::Expired);
    assert_eq!(effect.latest().unwrap().disposition, Disposition::Uncertain);
    assert_eq!(view.get(&payload_key).unwrap(), payload);
    assert_eq!(
        DispatchCatalog::history_page(&view, &record.effects[0].hex(), None, 128, 4096)
            .unwrap()
            .rows[0]
            .encode()
            .unwrap(),
        history
    );
    assert!(view
        .get(&record.inbox.as_ref().unwrap().row_key(&record.key).unwrap())
        .unwrap()
        .is_some());
    let (protected, result) = inspect(&view, &record.key, time(2200), permission).unwrap();
    assert!(result.is_none());
    assert_eq!(
        (protected.fingerprint, protected.effects, protected.source),
        (record.fingerprint, record.effects, record.source)
    );
    let namespace = NamespaceRecord::decode(&view.get(&namespace_key()).unwrap().unwrap()).unwrap();
    assert_eq!(
        (
            namespace.pins.retained_results,
            namespace.pins.unresolved_effects,
            namespace.pins.payload_references,
            namespace.pins.inbox_protection
        ),
        (1, 1, 1, 1)
    );
    validate_view(&view, foreign_codec).unwrap();
}

#[test]
fn destructive_purge_waits_for_native_reader_then_resumes_after_reopen_to_expired_floor() {
    let (dir, store, effects) = setup();
    let record = completed(&store, &effects, "purge-reopen");
    uncertain(&store, &record);
    let owner = ResultMaintenanceOwner::default();
    anchor(&owner, &store);
    let request = request(&record);
    owner
        .terminalize(&store, &request, observation(2200, 100), authorize)
        .unwrap();
    let reader = store.snapshot().unwrap();
    assert_eq!(
        owner.purge(&store, &request, observation(2300, 200), authorize),
        Err(AtomicError::Limit)
    );
    assert!(reader
        .get(&latent_effects::dispatch_store::effect_payload_key(&record.effects[0].hex()).unwrap())
        .unwrap()
        .is_some());
    drop(reader);
    let partial = owner
        .purge(&store, &request, observation(2300, 200), authorize)
        .unwrap();
    assert!(!partial.complete);
    assert_eq!(partial.purged_effects, 1);
    validate_view(&store.snapshot().unwrap(), foreign_codec).unwrap();
    drop(store);
    let store = open(&dir.path().join("state.redb"));
    let owner = ResultMaintenanceOwner::default();
    let final_step = owner
        .purge(&store, &request, observation(2301, 201), authorize)
        .unwrap();
    assert!(final_step.complete);
    let view = store.snapshot().unwrap();
    validate_view(&view, foreign_codec).unwrap();
    assert!(matches!(
        inspect(&view, &record.key, time(2301), permission),
        Err(AtomicError::Expired)
    ));
    assert!(matches!(
        PreparedAdmission::prepare(&view, input("purge-reopen"), time(2301), permission),
        Err(AtomicError::Expired)
    ));
    assert!(view
        .get(&record.inbox.as_ref().unwrap().row_key(&record.key).unwrap())
        .unwrap()
        .is_none());
    let namespace = NamespaceRecord::decode(&view.get(&namespace_key()).unwrap().unwrap()).unwrap();
    assert_eq!(
        (
            namespace.pins.retained_results,
            namespace.pins.unresolved_effects,
            namespace.pins.payload_references,
            namespace.pins.inbox_protection
        ),
        (1, 0, 0, 0)
    );
    let (usage, _, _) = writer::Usage::read(&view, &record.key).unwrap();
    assert_eq!(
        (
            usage.results,
            usage.effects,
            usage.effect_bytes,
            usage.payload_bytes,
            usage.reserved,
            usage.recovery_reserved
        ),
        (1, 0, 0, 0, 0, 0)
    );
    drop(view);
    let ordinary = owner
        .step(&store, observation(2302, 202), maintenance)
        .unwrap();
    assert_eq!((ordinary.visited, ordinary.retired), (1, 0));
    // Explicit review advanced its namespace clock. Ordinary body maintenance
    // merely observes the retained expired floor and cannot count a new expiry.
    let view = store.snapshot().unwrap();
    assert!(RetiredCommand::is_present(
        &view
            .get(&record::command_row_key(record.id))
            .unwrap()
            .unwrap()
    ));
}
