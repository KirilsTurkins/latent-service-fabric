use std::fs::OpenOptions;

use crate::payload::tests as payload_fixture;

use super::*;

struct Fixture {
    directory: tempfile::TempDir,
    store: Option<EmbeddedStore>,
}

impl Fixture {
    fn new() -> Self {
        let directory = tempfile::tempdir().unwrap();
        let store = Some(Self::open(directory.path()));
        Self { directory, store }
    }

    fn open(directory: &std::path::Path) -> EmbeddedStore {
        EmbeddedStore::open_file(
            OpenOptions::new()
                .read(true)
                .write(true)
                .create(true)
                .truncate(false)
                .open(directory.join("dispatcher.redb"))
                .unwrap(),
            latent_state::embedded::StoreLimits::default(),
        )
        .unwrap()
    }

    fn store(&self) -> &EmbeddedStore {
        self.store.as_ref().unwrap()
    }

    fn reopen(&mut self) {
        drop(self.store.take());
        self.store = Some(Self::open(self.directory.path()));
    }
}

fn time(unix_millis: u64) -> EffectTime {
    EffectTime {
        unix_millis,
        continuity_proven: true,
    }
}

fn seed(store: &EmbeddedStore, identity: char) -> DueRecord {
    let value = payload_fixture::value();
    let authority = payload_fixture::authority(&value, &identity.to_string().repeat(64));
    let due = super::super::initial_due_mutation(&authority).unwrap();
    let record = EffectRecord::committed(&authority).unwrap();
    let payload = PayloadRecord::new(&authority, value).unwrap();
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![
                RowMutation {
                    key: effect_row_key(payload.effect()).unwrap(),
                    value: Some(record.encode().unwrap()),
                },
                RowMutation {
                    key: effect_payload_key(payload.effect()).unwrap(),
                    value: Some(payload.encode().unwrap()),
                },
                due.clone(),
            ],
        })
        .unwrap();
    DueRecord::decode(&due.key, due.value.as_ref().unwrap()).unwrap()
}

fn record(store: &EmbeddedStore, effect: &str) -> EffectRecord {
    EffectRecord::decode(
        &store
            .snapshot()
            .unwrap()
            .get(&effect_row_key(effect).unwrap())
            .unwrap()
            .unwrap(),
    )
    .unwrap()
}

fn receipt(disposition: Disposition, now: u64) -> AttemptReceipt {
    AttemptReceipt {
        disposition,
        reason: "provider-boundary".into(),
        provider_receipt: (disposition == Disposition::ProviderAcknowledged)
            .then(|| "provider-receipt".into()),
        observed_at_millis: now,
    }
}

#[test]
fn native_claim_send_complete_and_history_are_generation_cas_atomic() {
    let fixture = Fixture::new();
    let store = fixture.store();
    let due = seed(store, 'a');
    let epoch = DispatchCatalog::begin_exclusive_epoch(store, time(100), None).unwrap();
    let before = store.snapshot().unwrap();
    let claimed = DispatchCatalog::claim(store, epoch, &due, time(101)).unwrap();
    assert_eq!(claimed.attempt.attempt(), 1);
    assert_eq!(claimed.attempt.owner_epoch(), epoch.generation());
    assert_eq!(
        before.get(&due.key().unwrap()).unwrap(),
        Some(due.encode().unwrap())
    );
    assert_eq!(store.snapshot().unwrap().get(&due.key().unwrap()), Ok(None));
    assert_eq!(
        DispatchCatalog::claim(store, epoch, &due, time(101)).err(),
        Some(AuthorityError::Stale.into())
    );
    DispatchCatalog::begin_send(store, epoch, &claimed.attempt, time(102)).unwrap();
    assert_eq!(
        DispatchCatalog::begin_send(store, epoch, &claimed.attempt, time(102)),
        Err(AuthorityError::Stale.into())
    );
    let ack = receipt(Disposition::ProviderAcknowledged, 103);
    assert_eq!(
        DispatchCatalog::complete(store, epoch, &claimed.attempt, ack.clone(), None, time(103)),
        Ok(Disposition::ProviderAcknowledged)
    );
    assert_eq!(
        DispatchCatalog::complete(store, epoch, &claimed.attempt, ack, None, time(103)),
        Err(AuthorityError::Stale.into())
    );
    let view = store.snapshot().unwrap();
    let history = DispatchCatalog::history_page(&view, &due.effect, None, 1, 4096).unwrap();
    assert_eq!(history.rows.len(), 1);
    assert!(history.resume.is_none());
    assert_eq!(history.rows[0].attempt.as_ref().unwrap(), &claimed.attempt);
    assert_eq!(record(store, &due.effect).history_sequence(), 1);
    let counts = DispatchCatalog::counts(&view).unwrap();
    assert_eq!(counts.acknowledged, 1);
    assert_eq!(counts.active, 0);
    assert_eq!(counts.payload_bytes, 0);
}

#[test]
fn reopened_send_boundary_is_uncertain_and_old_worker_receipt_cannot_overwrite_it() {
    let mut fixture = Fixture::new();
    let due = seed(fixture.store(), 'b');
    let old = DispatchCatalog::begin_exclusive_epoch(fixture.store(), time(100), None).unwrap();
    let claim = DispatchCatalog::claim(fixture.store(), old, &due, time(101)).unwrap();
    DispatchCatalog::begin_send(fixture.store(), old, &claim.attempt, time(102)).unwrap();
    fixture.reopen();
    let current = DispatchCatalog::begin_exclusive_epoch(
        fixture.store(),
        time(103),
        Some((old.generation(), 102)),
    )
    .unwrap();
    assert_eq!(
        DispatchCatalog::recover_page(fixture.store(), current, None, false, time(103)),
        Err(AuthorityError::Unavailable.into())
    );
    assert_eq!(
        record(fixture.store(), &due.effect).disposition(),
        Disposition::Dispatching
    );
    assert_eq!(
        DispatchCatalog::recover_page(fixture.store(), current, None, true, time(103)),
        Ok(None)
    );
    let recovered = record(fixture.store(), &due.effect);
    assert_eq!(recovered.disposition(), Disposition::Uncertain);
    assert_eq!(recovered.authority().unwrap().link().command, "command-a");
    assert_eq!(
        DispatchCatalog::complete(
            fixture.store(),
            old,
            &claim.attempt,
            receipt(Disposition::ProviderAcknowledged, 104),
            None,
            time(104)
        ),
        Err(DispatchStoreError::StaleEpoch)
    );
    assert_eq!(
        DispatchCatalog::complete(
            fixture.store(),
            current,
            &claim.attempt,
            receipt(Disposition::ProviderAcknowledged, 104),
            None,
            time(104)
        ),
        Err(AuthorityError::Stale.into())
    );
    assert_eq!(
        record(fixture.store(), &due.effect).disposition(),
        Disposition::Uncertain
    );
    assert_eq!(record(fixture.store(), &due.effect).history_sequence(), 1);
    assert!(fixture
        .store()
        .snapshot()
        .unwrap()
        .get(&effect_payload_key(&due.effect).unwrap())
        .unwrap()
        .is_some());
}

#[test]
fn claim_before_send_restart_is_known_nonexecution_and_missing_payload_fails_recovery() {
    let mut fixture = Fixture::new();
    let due = seed(fixture.store(), 'c');
    let old = DispatchCatalog::begin_exclusive_epoch(fixture.store(), time(100), None).unwrap();
    DispatchCatalog::claim(fixture.store(), old, &due, time(101)).unwrap();
    fixture.reopen();
    let epoch = DispatchCatalog::begin_exclusive_epoch(fixture.store(), time(102), None).unwrap();
    DispatchCatalog::recover_page(fixture.store(), epoch, None, true, time(102)).unwrap();
    assert_eq!(
        record(fixture.store(), &due.effect).disposition(),
        Disposition::KnownFailed
    );
    fixture
        .store()
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: effect_payload_key(&due.effect).unwrap(),
                value: None,
            }],
        })
        .unwrap();
    assert_eq!(
        DispatchCatalog::recover_page(fixture.store(), epoch, None, true, time(103)),
        Err(StoreError::Corrupt.into())
    );
    assert_eq!(
        record(fixture.store(), &due.effect).disposition(),
        Disposition::KnownFailed
    );
}

#[test]
fn uncertain_completion_never_retries_without_qualified_exact_payload_provider_proof() {
    let fixture = Fixture::new();
    let due = seed(fixture.store(), 'd');
    let epoch = DispatchCatalog::begin_exclusive_epoch(fixture.store(), time(100), None).unwrap();
    let claimed = DispatchCatalog::claim(fixture.store(), epoch, &due, time(101)).unwrap();
    DispatchCatalog::begin_send(fixture.store(), epoch, &claimed.attempt, time(102)).unwrap();
    assert_eq!(
        DispatchCatalog::complete(
            fixture.store(),
            epoch,
            &claimed.attempt,
            receipt(Disposition::Uncertain, 103),
            Some((RetryProof::KnownNonexecution, 1)),
            time(103)
        ),
        Ok(Disposition::Uncertain)
    );
    assert!(
        DispatchCatalog::due_page(&fixture.store().snapshot().unwrap(), 1000, None, 16, 4096)
            .unwrap()
            .rows
            .is_empty()
    );
    assert_eq!(record(fixture.store(), &due.effect).attempts(), 1);
}

#[test]
fn qualified_retry_persists_one_due_identity_and_history_pages_remain_bounded() {
    let fixture = Fixture::new();
    let due = seed(fixture.store(), 'e');
    let epoch = DispatchCatalog::begin_exclusive_epoch(fixture.store(), time(100), None).unwrap();
    let first = DispatchCatalog::claim(fixture.store(), epoch, &due, time(101)).unwrap();
    DispatchCatalog::begin_send(fixture.store(), epoch, &first.attempt, time(102)).unwrap();
    let proof = RetryProof::QualifiedDeduplication {
        valid_until_millis: 1000,
        same_payload: true,
        same_provider_incarnation: true,
    };
    assert_eq!(
        DispatchCatalog::complete(
            fixture.store(),
            epoch,
            &first.attempt,
            receipt(Disposition::Uncertain, 103),
            Some((proof, 5)),
            time(103)
        ),
        Ok(Disposition::RetryScheduled)
    );
    let early =
        DispatchCatalog::due_page(&fixture.store().snapshot().unwrap(), 107, None, 16, 4096)
            .unwrap();
    assert!(early.rows.is_empty());
    assert_eq!(early.next_due_millis, Some(108));
    let page = DispatchCatalog::due_page(&fixture.store().snapshot().unwrap(), 108, None, 16, 4096)
        .unwrap();
    assert_eq!(page.rows.len(), 1);
    assert_eq!(page.rows[0].effect, due.effect);
    assert_eq!(
        page.rows[0].claim_generation,
        first.attempt.claim_generation()
    );
    let second = DispatchCatalog::claim(fixture.store(), epoch, &page.rows[0], time(108)).unwrap();
    assert_eq!(second.attempt.attempt(), 2);
    DispatchCatalog::begin_send(fixture.store(), epoch, &second.attempt, time(109)).unwrap();
    DispatchCatalog::complete(
        fixture.store(),
        epoch,
        &second.attempt,
        receipt(Disposition::ProviderAcknowledged, 110),
        None,
        time(110),
    )
    .unwrap();
    let view = fixture.store().snapshot().unwrap();
    let page = DispatchCatalog::history_page(&view, &due.effect, None, 1, 4096).unwrap();
    assert_eq!(page.rows.len(), 1);
    assert_eq!(page.rows[0].sequence, 1);
    let next =
        DispatchCatalog::history_page(&view, &due.effect, page.resume.as_deref(), 1, 4096).unwrap();
    assert_eq!(next.rows[0].sequence, 2);
    assert!(next.resume.is_none());
    assert_eq!(
        DispatchCatalog::complete(
            fixture.store(),
            epoch,
            &first.attempt,
            receipt(Disposition::ProviderAcknowledged, 111),
            None,
            time(111)
        ),
        Err(AuthorityError::Stale.into())
    );
}

#[test]
fn policy_block_and_expiry_persist_without_send_and_clock_restore_rollback_never_advances() {
    let fixture = Fixture::new();
    let blocked = seed(fixture.store(), '0');
    let expired = seed(fixture.store(), '1');
    let epoch = DispatchCatalog::begin_exclusive_epoch(fixture.store(), time(100), None).unwrap();
    DispatchCatalog::block_eligible(fixture.store(), epoch, &blocked, time(101)).unwrap();
    assert_eq!(
        record(fixture.store(), &blocked.effect).disposition(),
        Disposition::PolicyBlocked
    );
    assert_eq!(record(fixture.store(), &blocked.effect).attempts(), 0);
    assert_eq!(
        DispatchCatalog::claim(fixture.store(), epoch, &expired, time(1100)).err(),
        Some(AuthorityError::Expired.into())
    );
    assert_eq!(
        record(fixture.store(), &expired.effect).disposition(),
        Disposition::Expired
    );
    let before = fixture
        .store()
        .snapshot()
        .unwrap()
        .get(&OwnerRecord::key())
        .unwrap();
    assert_eq!(
        DispatchCatalog::begin_exclusive_epoch(fixture.store(), time(1099), None),
        Err(AuthorityError::ClockDiscontinuity.into())
    );
    assert_eq!(
        DispatchCatalog::begin_exclusive_epoch(
            fixture.store(),
            EffectTime {
                unix_millis: 1200,
                continuity_proven: false
            },
            None
        ),
        Err(AuthorityError::ClockDiscontinuity.into())
    );
    assert_eq!(
        DispatchCatalog::begin_exclusive_epoch(
            fixture.store(),
            time(1200),
            Some((epoch.generation() + 1, 1100))
        ),
        Err(DispatchStoreError::StaleEpoch)
    );
    assert_eq!(
        fixture
            .store()
            .snapshot()
            .unwrap()
            .get(&OwnerRecord::key())
            .unwrap(),
        before
    );
    let counts = DispatchCatalog::counts(&fixture.store().snapshot().unwrap()).unwrap();
    assert_eq!(counts.blocked, 1);
    assert_eq!(counts.expired, 1);
}
