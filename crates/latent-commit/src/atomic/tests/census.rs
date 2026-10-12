//! Real installed upper rows, original reservations, retry and physical reopen.
use super::*;
use latent_effects::{
    dispatch::{AttemptReceipt, Disposition},
    dispatch_store::DispatchCatalog,
};
use latent_state::{
    embedded::StoreError,
    tenant::{self, TenantCensus, TenantCensusReport, INSTALLED_GLOBAL_ALLOWANCE},
};
use std::time::{Duration, Instant};

pub(super) fn census(store: &EmbeddedStore) -> Result<TenantCensusReport, StoreError> {
    let view = store.snapshot()?;
    let quota = accounted::usage(store).quota;
    let mut census = TenantCensus::capture(
        &view,
        &[quota],
        INSTALLED_GLOBAL_ALLOWANCE,
        Instant::now() + Duration::from_secs(20),
    )?;
    validate_view_observed(&view, accounted::installed_codec, |view, key, bytes| {
        let contribution = match tenant_census_contribution(view, key, bytes) {
            Err(StoreError::UnsupportedFormat) => {
                match tenant::census_contribution(view, key, bytes) {
                    Err(StoreError::UnsupportedFormat) => {
                        DispatchCatalog::tenant_census_contribution(view, key, bytes)
                    }
                    result => result,
                }
            }
            result => result,
        }?;
        census.observe(key, bytes, contribution)
    })?;
    census.finish()
}

fn effect_time(now: u64) -> EffectTime {
    EffectTime {
        unix_millis: now,
        continuity_proven: true,
    }
}

#[test]
fn original_upper_census_covers_real_state_inbox_effect_and_uncertain_history_after_reopen() {
    let (dir, store, effects) = accounted::setup(8);
    let mut request = input("census-uncertain");
    request.inbox = Some(InboxIdentity {
        provider: "input".into(),
        binding: "source".into(),
        message: "census-input".into(),
        payload_digest: Identity::derive(b"input", &[b"census-input"]),
    });
    let admitted = claim(&store, request);
    let view = store.snapshot().unwrap();
    let record = confirm(
        CompleteEnvelope::success(
            &view,
            admitted,
            Some(stage(&view)),
            vec![intent()],
            value(b"original census result"),
            &effects,
            time(101),
        )
        .unwrap(),
        &store,
        &effects,
    );
    drop(view);
    census(&store).unwrap();
    let epoch = DispatchCatalog::begin_exclusive_epoch(&store, effect_time(102), None).unwrap();
    let candidate = DispatchCatalog::due_page(&store.snapshot().unwrap(), 102, None, 1, 4096)
        .unwrap()
        .rows
        .pop()
        .unwrap();
    let claim = DispatchCatalog::claim(&store, epoch, &candidate, effect_time(102)).unwrap();
    // The real active disposition reservation is also covered by original LCU2.
    census(&store).unwrap();
    DispatchCatalog::begin_send(&store, epoch, &claim.attempt, effect_time(103)).unwrap();
    DispatchCatalog::complete(
        &store,
        epoch,
        &claim.attempt,
        AttemptReceipt {
            disposition: Disposition::Uncertain,
            reason: "fixture-lost-response".into(),
            provider_receipt: None,
            observed_at_millis: 104,
        },
        None,
        effect_time(104),
    )
    .unwrap();
    let before = accounted::usage(&store);
    let report = census(&store).unwrap();
    assert_eq!(report.global_rows, 2);
    drop(store);
    let store = open(&dir.path().join("state.redb"));
    assert_eq!(accounted::usage(&store), before);
    assert_eq!(census(&store).unwrap(), report);
    let (_, result) = inspect(
        &store.snapshot().unwrap(),
        &record.key,
        time(105),
        permission,
    )
    .unwrap();
    assert_eq!(
        result.unwrap().value(),
        Some(&value(b"original census result"))
    );
}

#[test]
fn original_upper_census_refuses_validly_encoded_ledger_drift_without_upgrading_counters() {
    let (_dir, store, effects) = accounted::setup(8);
    let admitted = claim(&store, input("census-drift"));
    confirm(
        CompleteEnvelope::success_without_intents(
            &store.snapshot().unwrap(),
            admitted,
            None,
            value(b"original"),
            time(101),
        )
        .unwrap(),
        &store,
        &effects,
    );
    census(&store).unwrap();
    let original = accounted::usage(&store);
    let key = writer::usage_row_key("tenant", "aggregate", 1).unwrap();
    let mut ledger =
        writer::Usage::decode(&store.snapshot().unwrap().get(&key).unwrap().unwrap()).unwrap();
    ledger.result_bytes += 1;
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key,
                value: Some(ledger.encode().unwrap()),
            }],
        })
        .unwrap();
    validate_view(&store.snapshot().unwrap(), accounted::installed_codec).unwrap();
    assert_eq!(census(&store), Err(StoreError::Corrupt));
    assert_eq!(accounted::usage(&store), original);
}

fn retried(store: &EmbeddedStore, effects: &EffectAuthorityOwner) -> (CommandRecord, RetryRequest) {
    let admitted = claim(store, input("census-retry"));
    let watch = admitted.retirement();
    let physical = admitted.physical_work().unwrap();
    drop(admitted);
    physical.retire();
    let aborted = confirm(
        CompleteEnvelope::technical_abort(
            &store.snapshot().unwrap(),
            watch.proven_noncommit().unwrap(),
            "fixture-retired".into(),
            time(101),
        )
        .unwrap(),
        store,
        effects,
    );
    let retry = RetryRequest {
        request_id: "census-retry-2".into(),
        expected_abort: aborted.abort_proof().unwrap(),
    };
    let AdmissionDecision::New(prepared) = PreparedAdmission::retry(
        &store.snapshot().unwrap(),
        &input("census-retry"),
        &retry,
        time(102),
        permission,
    )
    .unwrap() else {
        panic!("expected original second attempt")
    };
    let admitted = prepared.publish(store, || Ok(())).unwrap();
    let record = confirm(
        CompleteEnvelope::success_without_intents(
            &store.snapshot().unwrap(),
            admitted,
            None,
            value(b"original retry result"),
            time(103),
        )
        .unwrap(),
        store,
        effects,
    );
    (record, retry)
}

#[test]
fn installed_retry_receipt_replays_reopens_and_purges_with_exact_original_tenant_ownership() {
    let (dir, store, effects) = accounted::setup(8);
    let (record, retry) = retried(&store, &effects);
    let rows = store
        .snapshot()
        .unwrap()
        .scan_after(Family::Maintenance, b"command-retry-v1\0", None, 3, 4096)
        .unwrap()
        .rows;
    assert_eq!(rows.len(), 1);
    assert!(rows[0].1.starts_with(b"LCT\0\x02"));
    let original = accounted::usage(&store);
    assert!(matches!(PreparedAdmission::retry(
        &store.snapshot().unwrap(), &input("census-retry"), &retry, time(104), permission,
    ).unwrap(), AdmissionDecision::Existing(command) if command == record));
    assert_eq!(accounted::usage(&store), original);
    let report = census(&store).unwrap();
    drop(store);
    let store = open(&dir.path().join("state.redb"));
    assert_eq!(census(&store).unwrap(), report);
    purge_retry(&store, &record);
    assert!(!store
        .snapshot()
        .unwrap()
        .contains_prefix(Family::Maintenance, b"command-retry-v1\0")
        .unwrap());
    assert!(accounted::usage(&store).usage.result_bytes < original.usage.result_bytes);
    census(&store).unwrap();
}

#[test]
fn installed_retry_startup_refuses_a_valid_receipt_rebound_to_another_tenant() {
    let (dir, store, effects) = accounted::setup(8);
    let (record, retry) = retried(&store, &effects);
    let row = store
        .snapshot()
        .unwrap()
        .scan_after(Family::Maintenance, b"command-retry-v1\0", None, 1, 4096)
        .unwrap()
        .rows
        .pop()
        .unwrap();
    let decoded = super::super::retry_receipt::RetryReceipt::decode(&row.1).unwrap();
    let retry_identity = Identity(row.0.key[row.0.key.len() - 32..].try_into().unwrap());
    let original = accounted::usage(&store);
    let index_key = super::super::retention::RetryIndex::row_key(record.id, record.attempt);
    let index_bytes = store.snapshot().unwrap().get(&index_key).unwrap().unwrap();
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: index_key.clone(),
                value: None,
            }],
        })
        .unwrap();
    assert!(matches!(
        PreparedAdmission::retry(
            &store.snapshot().unwrap(),
            &input("census-retry"),
            &retry,
            time(104),
            permission,
        ),
        Err(AtomicError::Corrupt)
    ));
    assert_eq!(census(&store), Err(StoreError::Corrupt));
    assert_eq!(accounted::usage(&store), original);
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: index_key,
                value: Some(index_bytes),
            }],
        })
        .unwrap();
    census(&store).unwrap();
    let mut foreign = record.clone();
    foreign.key.tenant = "foreign".into();
    let encoded = super::super::retry_receipt::RetryReceipt::create(
        &foreign,
        retry_identity,
        retry.expected_abort,
        true,
    )
    .unwrap();
    assert_eq!(
        super::super::retry_receipt::RetryReceipt::decode(&encoded)
            .unwrap()
            .attempt,
        decoded.attempt
    );
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: row.0,
                value: Some(encoded),
            }],
        })
        .unwrap();
    assert_eq!(census(&store), Err(StoreError::Corrupt));
    assert_eq!(accounted::usage(&store), original);
    drop(store);
    let store = open(&dir.path().join("state.redb"));
    assert_eq!(census(&store), Err(StoreError::Corrupt));
    assert_eq!(accounted::usage(&store), original);
}

fn purge_retry(store: &EmbeddedStore, record: &CommandRecord) {
    let owner = ResultMaintenanceOwner::default();
    let clock = |now, elapsed| MaintenanceClock {
        time: time(now),
        boot: [7; 32],
        monotonic_millis: elapsed,
    };
    owner
        .anchor(store, None, clock(2100, 0), |record| {
            permission(CommandAccess::Replay, record)
        })
        .unwrap();
    let request = RetentionRequest {
        key: record.key.clone(),
        expected_command_digest: RetentionRequest::command_digest(record).unwrap(),
        actor: "operator:census".into(),
        operation_id: "purge-retry".into(),
        policy: "reviewed/census-v1".into(),
        retain_until_millis: 2300,
        inbox_expires_at_millis: None,
    };
    let authorize = |_, _: &RetentionRequest, record: Option<&CommandRecord>| {
        permission(CommandAccess::Replay, record)
    };
    assert!(
        owner
            .terminalize(store, &request, clock(2200, 100), authorize)
            .unwrap()
            .complete
    );
    assert!(
        !owner
            .purge(store, &request, clock(2300, 200), authorize)
            .unwrap()
            .complete
    );
    assert!(
        owner
            .purge(store, &request, clock(2301, 201), authorize)
            .unwrap()
            .complete
    );
}

#[test]
fn explicit_legacy_retry_keeps_original_lct1_bytes_and_requires_review_before_installed_census() {
    let (_dir, store, effects) = setup();
    let (record, _) = retried(&store, &effects);
    let row = store
        .snapshot()
        .unwrap()
        .scan_after(Family::Maintenance, b"command-retry-v1\0", None, 1, 4096)
        .unwrap()
        .rows
        .pop()
        .unwrap();
    assert!(row.1.starts_with(b"LCT\0\x01"));
    assert_eq!(row.1.len(), 77);
    validate_view(&store.snapshot().unwrap(), foreign_codec).unwrap();
    assert!(matches!(
        tenant_census_contribution(&store.snapshot().unwrap(), &row.0, &row.1),
        Err(StoreError::UnsupportedFormat)
    ));
    purge_retry(&store, &record);
    validate_view(&store.snapshot().unwrap(), foreign_codec).unwrap();
}
