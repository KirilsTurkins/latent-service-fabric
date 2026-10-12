use std::fs::OpenOptions;

use latent_state::embedded::{AtomicBatch, EmbeddedStore, ExpectedRow, StoreLimits};

use crate::dispatch::EffectRecord;
use crate::payload::{tests as payload_fixture, PayloadRecord};

use super::*;

#[test]
fn due_index_orders_time_and_identity_and_rejects_unknown_or_malformed_rows() {
    let first = DueRecord {
        due_millis: 255,
        effect: "f".repeat(64),
        incarnation: 1,
        claim_generation: 0,
    };
    let mut second = first.clone();
    second.due_millis = 256;
    second.effect = "0".repeat(64);
    assert!(first.key().unwrap().key < second.key().unwrap().key);
    let key = first.key().unwrap();
    let encoded = first.encode().unwrap();
    assert_eq!(DueRecord::decode(&key, &encoded), Ok(first));
    for cut in 0..encoded.len() {
        assert!(DueRecord::decode(&key, &encoded[..cut]).is_err());
    }
    let mut unknown = encoded.clone();
    unknown[4] = 2;
    assert_eq!(
        DueRecord::decode(&key, &unknown),
        Err(StoreError::UnsupportedFormat)
    );
    let mut zero_incarnation = encoded;
    zero_incarnation[5..13].fill(0);
    assert_eq!(
        DueRecord::decode(&key, &zero_incarnation),
        Err(StoreError::Corrupt)
    );
    let mut wrong_key = key;
    wrong_key.key.push(0);
    assert_eq!(
        DueRecord::decode(&wrong_key, &zero_incarnation),
        Err(StoreError::Corrupt)
    );
    assert!(effect_row_key(&"A".repeat(64)).is_err());
    assert!(effect_payload_key("noncanonical-effect").is_err());
}

#[test]
fn envelope_outbox_payload_and_due_index_are_atomic_and_survive_reopen() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("effect-envelope.redb");
    let open = || {
        EmbeddedStore::open_file(
            OpenOptions::new()
                .read(true)
                .write(true)
                .create(true)
                .truncate(false)
                .open(&path)
                .unwrap(),
            StoreLimits::default(),
        )
        .unwrap()
    };
    let store = open();
    let value = payload_fixture::value();
    let authority = payload_fixture::authority(&value, &"3".repeat(64));
    let payload = PayloadRecord::new(&authority, value).unwrap();
    let outbox_key = effect_row_key(payload.effect()).unwrap();
    let payload_key = effect_payload_key(payload.effect()).unwrap();
    let due = initial_due_mutation(&authority).unwrap();
    let rows = vec![
        RowMutation {
            key: outbox_key.clone(),
            value: Some(
                EffectRecord::committed(&authority)
                    .unwrap()
                    .encode()
                    .unwrap(),
            ),
        },
        RowMutation {
            key: payload_key.clone(),
            value: Some(payload.encode().unwrap()),
        },
        due.clone(),
    ];
    for row in &rows {
        validate_row(&row.key, row.value.as_ref().unwrap()).unwrap();
    }
    let wrong_identity = effect_row_key(&"4".repeat(64)).unwrap();
    assert_eq!(
        validate_row(&wrong_identity, rows[0].value.as_ref().unwrap()),
        Err(StoreError::Corrupt)
    );
    assert_eq!(
        validate_row(
            &RowKey {
                family: Family::Command,
                key: b"unrecognized-command".to_vec()
            },
            b"opaque"
        ),
        Err(StoreError::UnsupportedFormat)
    );
    let batch = AtomicBatch {
        expectations: rows
            .iter()
            .map(|row| ExpectedRow {
                key: row.key.clone(),
                value: None,
            })
            .collect(),
        mutations: rows,
    };
    let before = store.snapshot().unwrap();
    assert_eq!(store.apply(batch.clone()), Ok(()));
    for key in [&outbox_key, &payload_key, &due.key] {
        assert_eq!(before.get(key), Ok(None));
        assert!(store.snapshot().unwrap().get(key).unwrap().is_some());
    }
    assert_eq!(store.apply(batch), Err(StoreError::Conflict));
    drop(before);
    drop(store);
    let reopened = open();
    let view = reopened.snapshot().unwrap();
    let record = EffectRecord::decode(&view.get(&outbox_key).unwrap().unwrap()).unwrap();
    let decoded = PayloadRecord::decode(&view.get(&payload_key).unwrap().unwrap()).unwrap();
    decoded.verify(&record.authority().unwrap()).unwrap();
    let index = DueRecord::decode(&due.key, &view.get(&due.key).unwrap().unwrap()).unwrap();
    assert_eq!(index.due_millis, authority.committed_at_millis());
    assert_eq!(index.incarnation, authority.scope().incarnation);
    assert_eq!(index.claim_generation, 0);
    assert_eq!(index.effect, record.authority().unwrap().link().effect);
}
