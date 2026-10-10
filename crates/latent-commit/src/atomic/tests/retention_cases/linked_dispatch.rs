use super::*;
use latent_effects::{
    authority::AuthorityError,
    dispatch::{AttemptIdentity, AttemptReceipt, Disposition, EffectRecord},
    dispatch_store::{
        effect_payload_key, effect_row_key, DispatchCatalog, DispatchEpoch, DispatchStoreError,
    },
    payload::PayloadRecord,
};

fn effect_time(now: u64) -> EffectTime {
    EffectTime {
        unix_millis: now,
        continuity_proven: true,
    }
}

fn committed(store: &EmbeddedStore, effects: &EffectAuthorityOwner) -> CommandRecord {
    let mut request = input("dispatcher-result-expiry");
    request.result_policy.result_millis = 100;
    request.inbox = Some(InboxIdentity {
        provider: "events".into(),
        binding: "inbox".into(),
        message: "dispatcher-result-expiry".into(),
        payload_digest: Identity::derive(b"test-input", &[b"dispatcher-result-expiry"]),
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

fn retained_effect(store: &EmbeddedStore, record: &CommandRecord) -> EffectRecord {
    let view = store.snapshot().unwrap();
    EffectRecord::decode(
        &view
            .get(&effect_row_key(&record.effect_ids()[0].hex()).unwrap())
            .unwrap()
            .unwrap(),
    )
    .unwrap()
}

fn start_dispatch(
    store: &EmbeddedStore,
    disposition: Disposition,
) -> (DispatchEpoch, Option<AttemptIdentity>) {
    let epoch = DispatchCatalog::begin_exclusive_epoch(store, effect_time(102), None).unwrap();
    if disposition == Disposition::Pending {
        return (epoch, None);
    }
    let due = DispatchCatalog::due_page(&store.snapshot().unwrap(), 102, None, 1, 4096).unwrap();
    assert_eq!(due.rows.len(), 1);
    let claimed = DispatchCatalog::claim(store, epoch, &due.rows[0], effect_time(102)).unwrap();
    DispatchCatalog::begin_send(store, epoch, &claimed.attempt, effect_time(103)).unwrap();
    if disposition == Disposition::Uncertain {
        let receipt = AttemptReceipt {
            disposition,
            reason: "external-outcome-unknown".into(),
            provider_receipt: None,
            observed_at_millis: 104,
        };
        assert_eq!(
            DispatchCatalog::complete(
                store,
                epoch,
                &claimed.attempt,
                receipt,
                None,
                effect_time(104)
            ),
            Ok(Disposition::Uncertain)
        );
    }
    (epoch, Some(claimed.attempt))
}

fn expire_response(store: &EmbeddedStore, record: &CommandRecord) {
    let effect = retained_effect(store, record);
    let old = store.snapshot().unwrap();
    let keys = [
        effect_row_key(&record.effect_ids()[0].hex()).unwrap(),
        effect_payload_key(&record.effect_ids()[0].hex()).unwrap(),
        record
            .inbox
            .as_ref()
            .unwrap()
            .row_key(record.key())
            .unwrap(),
        namespace_key(),
    ];
    let result_key = result_row_key(record.id(), record.attempt());
    let old_body = old.get(&result_key).unwrap().unwrap();
    let owner = ResultMaintenanceOwner::default();
    owner
        .anchor(store, None, observation(105, 0), maintenance)
        .unwrap();
    let progress = owner
        .step(store, observation(201, 96), maintenance)
        .unwrap();
    assert_eq!((progress.visited, progress.retired), (1, 1));
    let view = store.snapshot().unwrap();
    let marker = view.get(&result_key).unwrap().unwrap();
    assert!(marker.starts_with(b"LCE\0\x01"));
    assert_eq!(
        progress.reclaimed_bytes,
        (old_body.len() - marker.len()) as u64
    );
    assert_eq!(old.get(&result_key).unwrap(), Some(old_body));
    for key in keys {
        assert_eq!(view.get(&key).unwrap(), old.get(&key).unwrap());
    }
    assert_eq!(
        DispatchCatalog::counts(&view).unwrap(),
        DispatchCatalog::counts(&old).unwrap()
    );
    assert_eq!(retained_effect(store, record), effect);
    let (protected, body) = inspect(&view, record.key(), time(201), permission).unwrap();
    assert!(body.is_none());
    assert_eq!(protected.effect_ids(), record.effect_ids());
    assert_eq!(protected.source(), record.source());
    assert_eq!(protected.fingerprint(), record.fingerprint());
    assert_eq!(protected.identity_expires(), record.identity_expires());
    validate_view(&view, foreign_codec).unwrap();
}

fn verify_reopened(store: &EmbeddedStore, record: &CommandRecord, effect: &EffectRecord) {
    let view = store.snapshot().unwrap();
    validate_view(&view, foreign_codec).unwrap();
    let (protected, body) = inspect(&view, record.key(), time(202), permission).unwrap();
    assert!(body.is_none());
    assert_eq!(protected.outcome(), Outcome::Committed);
    assert_eq!(protected.source(), record.source());
    assert_eq!(protected.effect_ids(), record.effect_ids());
    let authority = retained_effect(store, record).authority().unwrap();
    assert_eq!(authority, effect.authority().unwrap());
    assert_eq!(authority.link().command, record.id().hex());
    assert_eq!(authority.link().attempt, record.attempt());
    assert_eq!(authority.link().commit, record.disposition_id().hex());
    assert_eq!(authority.link().effect, record.effect_ids()[0].hex());
    let bytes = view
        .get(&effect_payload_key(&authority.link().effect).unwrap())
        .unwrap()
        .unwrap();
    let payload = PayloadRecord::decode(&bytes).unwrap();
    payload.verify(&authority).unwrap();
    assert_eq!(payload.value(), &value(b"updated"));
    let mut redelivery = input("dispatcher-result-expiry");
    redelivery.inbox = record.inbox.clone();
    redelivery.result_policy.result_millis = 100;
    let AdmissionDecision::Existing(replayed) =
        PreparedAdmission::prepare(&view, redelivery, time(202), permission).unwrap()
    else {
        panic!("expired response cannot recreate a committed command")
    };
    assert_eq!(replayed.id(), record.id());
    assert_eq!(replayed.effect_ids(), record.effect_ids());
}

fn scenario(disposition: Disposition) {
    let (dir, store, effects) = setup();
    let command = committed(&store, &effects);
    let (old_epoch, attempt) = start_dispatch(&store, disposition);
    let effect = retained_effect(&store, &command);
    assert_eq!(effect.disposition(), disposition);
    expire_response(&store, &command);
    drop(store);
    let store = open(&dir.path().join("state.redb"));
    verify_reopened(&store, &command, &effect);
    let current = DispatchCatalog::begin_exclusive_epoch(&store, effect_time(202), None).unwrap();
    if disposition == Disposition::Dispatching {
        assert_eq!(
            DispatchCatalog::recover_page(&store, current, None, false, effect_time(202)),
            Err(DispatchStoreError::Authority(AuthorityError::Unavailable))
        );
        assert_eq!(retained_effect(&store, &command).disposition(), disposition);
    }
    assert_eq!(
        DispatchCatalog::recover_page(&store, current, None, true, effect_time(202)),
        Ok(None)
    );
    let expected = if disposition == Disposition::Pending {
        disposition
    } else {
        Disposition::Uncertain
    };
    let retained = retained_effect(&store, &command);
    assert_eq!(retained.disposition(), expected);
    assert_eq!(retained.authority().unwrap(), effect.authority().unwrap());
    let view = store.snapshot().unwrap();
    let due = DispatchCatalog::due_page(&view, 202, None, 1, 4096).unwrap();
    if expected == Disposition::Pending {
        assert_eq!(due.rows.len(), 1);
        assert_eq!(due.rows[0].effect, command.effect_ids()[0].hex());
    } else {
        assert!(
            due.rows.is_empty(),
            "uncertainty cannot silently authorize redelivery"
        );
    }
    if let Some(attempt) = attempt {
        let receipt = AttemptReceipt {
            disposition: Disposition::ProviderAcknowledged,
            reason: "stale-provider-reply".into(),
            provider_receipt: Some("old-provider-receipt".into()),
            observed_at_millis: 203,
        };
        assert_eq!(
            DispatchCatalog::complete(&store, old_epoch, &attempt, receipt, None, effect_time(203)),
            Err(DispatchStoreError::StaleEpoch)
        );
        assert_eq!(retained_effect(&store, &command), retained);
    }
    validate_view(&view, foreign_codec).unwrap();
}

#[test]
fn pending_response_expiry_retains_eligible_effect_identity_and_payload_across_reopen() {
    scenario(Disposition::Pending);
}

#[test]
fn inflight_response_expiry_recovers_uncertain_without_accepting_stale_receipts() {
    scenario(Disposition::Dispatching);
}

#[test]
fn uncertain_response_expiry_reopens_without_unqualified_redelivery() {
    scenario(Disposition::Uncertain);
}
