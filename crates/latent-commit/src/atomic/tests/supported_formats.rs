//! Supported historical bytes are read explicitly, never upgraded by lookup.
use super::*;
use latent_state::embedded::ExpectedRow;

#[test]
fn durable_metadata_reports_decoded_command_and_independent_result_versions() {
    let (_dir, store, effects) = setup();
    let admitted = claim(&store, input("format-metadata"));
    let pending = store
        .snapshot()
        .unwrap()
        .get(&result_row_key(admitted.record.id, 1))
        .unwrap()
        .unwrap();
    assert_eq!(
        durable_row_format(&result_row_key(admitted.record.id, 1), &pending).unwrap(),
        ("latent.result-pending.v1", 1)
    );
    let record = confirm(
        CompleteEnvelope::success_without_intents(
            &store.snapshot().unwrap(),
            admitted,
            None,
            value(b"original result"),
            time(101),
        )
        .unwrap(),
        &store,
        &effects,
    );
    let command_key = command_row_key(record.id);
    let result_key = result_row_key(record.id, record.attempt);
    let view = store.snapshot().unwrap();
    let original = view.get(&command_key).unwrap().unwrap();
    let result = view.get(&result_key).unwrap().unwrap();
    assert_eq!(
        durable_row_format(&command_key, &original).unwrap(),
        ("latent.command.v1", 4)
    );
    assert_eq!(
        durable_row_format(&result_key, &result).unwrap(),
        ("latent.result.v1", 3)
    );
    let mut legacy = record.clone();
    legacy.accounted = false;
    legacy.retention_review.clear();
    let historical = legacy.encode().unwrap();
    assert_eq!(
        durable_row_format(&command_key, &historical).unwrap(),
        ("latent.command.v1", 3)
    );
    assert_eq!(
        DurableResult::decode(&result).unwrap().durable_format(),
        ("latent.result.v1", 3)
    );
    let mut unsupported = original.clone();
    unsupported[4] = 9;
    assert_eq!(
        durable_row_format(&command_key, &unsupported),
        Err(AtomicError::UnsupportedFormat)
    );
    assert_eq!(
        durable_row_format(&command_row_key(Identity([7; 32])), &original),
        Err(AtomicError::Corrupt)
    );
    assert_eq!(view.get(&command_key).unwrap().unwrap(), original);
    assert_eq!(view.get(&result_key).unwrap().unwrap(), result);
}

#[test]
fn original_lcm3_lct1_retry_receipt_replays_without_a_retention_index_or_implicit_migration() {
    let (_dir, store, effects) = setup();
    let request_input = input("historical-retry");
    let admitted = claim(&store, input("historical-retry"));
    let watch = admitted.retirement();
    let physical = admitted.physical_work().unwrap();
    drop(admitted);
    physical.retire();
    let aborted = confirm(
        CompleteEnvelope::technical_abort(
            &store.snapshot().unwrap(),
            watch.proven_noncommit().unwrap(),
            "physically-retired-original".into(),
            time(101),
        )
        .unwrap(),
        &store,
        &effects,
    );
    let retry = RetryRequest {
        request_id: "original-retry".into(),
        expected_abort: aborted.abort_proof().unwrap(),
    };
    let AdmissionDecision::New(prepared) = PreparedAdmission::retry(
        &store.snapshot().unwrap(),
        &request_input,
        &retry,
        time(102),
        permission,
    )
    .unwrap() else {
        panic!("expected second original attempt")
    };
    let admitted = prepared.publish(&store, || Ok(())).unwrap();
    let record = confirm(
        CompleteEnvelope::success_without_intents(
            &store.snapshot().unwrap(),
            admitted,
            None,
            value(b"original second attempt"),
            time(103),
        )
        .unwrap(),
        &store,
        &effects,
    );

    // Install an explicit historical fixture from supported codec bytes. This
    // is test setup, not a migration/admission path or invented abort proof.
    let view = store.snapshot().unwrap();
    let mut batch = AtomicBatch {
        expectations: vec![],
        mutations: vec![],
    };
    for key in [
        command_row_key(record.id),
        attempt_row_key(record.id, 1),
        attempt_row_key(record.id, 2),
    ] {
        let original = view.get(&key).unwrap().unwrap();
        let mut old = CommandRecord::decode(&original).unwrap();
        old.accounted = false;
        old.retention_review.clear();
        batch.expectations.push(ExpectedRow {
            key: key.clone(),
            value: Some(original),
        });
        batch.mutations.push(RowMutation {
            key,
            value: Some(old.encode().unwrap()),
        });
    }
    let index = super::super::retention::RetryIndex::row_key(record.id, record.attempt);
    batch.expectations.push(ExpectedRow {
        key: index.clone(),
        value: view.get(&index).unwrap(),
    });
    batch.mutations.push(RowMutation {
        key: index,
        value: None,
    });
    drop(view);
    store.apply(batch).unwrap();
    let before = store.snapshot().unwrap();
    let bytes = before.get(&command_row_key(record.id)).unwrap().unwrap();
    assert!(bytes.starts_with(b"LCM\0\x03"));
    let receipts = before
        .scan_after(Family::Maintenance, b"command-retry-v1\0", None, 1, 4096)
        .unwrap();
    assert_eq!(receipts.rows.len(), 1);
    assert_eq!(receipts.rows[0].1.len(), 77);
    assert!(receipts.rows[0].1.starts_with(b"LCT\0\x01"));
    let usage_key = writer::usage_row_key("tenant", "aggregate", 1).unwrap();
    let original_usage = before.get(&usage_key).unwrap();
    let AdmissionDecision::Existing(replayed) =
        PreparedAdmission::retry(&before, &request_input, &retry, time(104), permission).unwrap()
    else {
        panic!("legacy retry must never renew execution")
    };
    assert_eq!(replayed.durable_format(), ("latent.command.v1", 3));
    assert_eq!(replayed.outcome(), Outcome::Committed);
    assert_eq!(replayed.source, record.source);
    assert_eq!(replayed.fingerprint, record.fingerprint);
    assert_eq!(
        before.get(&command_row_key(record.id)).unwrap().unwrap(),
        bytes
    );
    assert_eq!(before.get(&usage_key).unwrap(), original_usage);
    let mut changed = retry;
    changed.expected_abort = Identity([9; 32]);
    assert!(matches!(
        PreparedAdmission::retry(&before, &request_input, &changed, time(104), permission),
        Err(AtomicError::Conflict)
    ));
}
