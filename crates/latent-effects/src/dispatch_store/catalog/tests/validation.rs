use crate::dispatch_store::codec::{attempt_reservation_key, history_key};
use latent_state::embedded::RowKey;

use super::*;

#[test]
fn coherent_dispatch_links_validate_claim_send_recovery_and_terminal_payload_retirement() {
    let mut fixture = Fixture::new();
    let due = seed(fixture.store(), 'a');
    DispatchCatalog::validate_view(&fixture.store().snapshot().unwrap()).unwrap();
    assert!(!DispatchCatalog::has_owner_history(&fixture.store().snapshot().unwrap()).unwrap());
    let epoch = DispatchCatalog::begin_exclusive_epoch(fixture.store(), time(100), None).unwrap();
    let claim = DispatchCatalog::claim(fixture.store(), epoch, &due, time(101)).unwrap();
    DispatchCatalog::validate_view(&fixture.store().snapshot().unwrap()).unwrap();
    DispatchCatalog::begin_send(fixture.store(), epoch, &claim.attempt, time(102)).unwrap();
    fixture.reopen();
    DispatchCatalog::validate_view(&fixture.store().snapshot().unwrap()).unwrap();
    assert!(DispatchCatalog::has_owner_history(&fixture.store().snapshot().unwrap()).unwrap());
    let epoch = DispatchCatalog::begin_exclusive_epoch(
        fixture.store(),
        time(103),
        Some((epoch.generation(), 102)),
    )
    .unwrap();
    DispatchCatalog::recover_page(fixture.store(), epoch, None, true, time(103)).unwrap();
    DispatchCatalog::validate_view(&fixture.store().snapshot().unwrap()).unwrap();
    assert_eq!(
        record(fixture.store(), &due.effect).disposition(),
        Disposition::Uncertain
    );

    let terminal = seed(fixture.store(), 'b');
    let claim = DispatchCatalog::claim(fixture.store(), epoch, &terminal, time(104)).unwrap();
    DispatchCatalog::begin_send(fixture.store(), epoch, &claim.attempt, time(105)).unwrap();
    DispatchCatalog::complete(
        fixture.store(),
        epoch,
        &claim.attempt,
        receipt(Disposition::ProviderAcknowledged, 106),
        None,
        time(106),
    )
    .unwrap();
    fixture
        .store()
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: effect_payload_key(&terminal.effect).unwrap(),
                value: None,
            }],
        })
        .unwrap();
    DispatchCatalog::validate_view(&fixture.store().snapshot().unwrap()).unwrap();
    assert_eq!(
        DispatchCatalog::counts(&fixture.store().snapshot().unwrap())
            .unwrap()
            .uncertain,
        1
    );
}

#[test]
fn individually_valid_but_orphaned_dispatch_rows_fail_coherent_readiness() {
    for family in [
        Family::Outbox,
        Family::PayloadReference,
        Family::Maintenance,
    ] {
        let fixture = Fixture::new();
        let due = seed(fixture.store(), 'c');
        let key = match family {
            Family::Outbox => effect_row_key(&due.effect).unwrap(),
            Family::PayloadReference => effect_payload_key(&due.effect).unwrap(),
            _ => due.key().unwrap(),
        };
        fixture
            .store()
            .apply(AtomicBatch {
                expectations: vec![],
                mutations: vec![RowMutation { key, value: None }],
            })
            .unwrap();
        assert_eq!(
            DispatchCatalog::validate_view(&fixture.store().snapshot().unwrap()),
            Err(StoreError::Corrupt),
        );
    }
    for remove_history in [false, true] {
        let fixture = Fixture::new();
        let due = seed(fixture.store(), 'd');
        let epoch =
            DispatchCatalog::begin_exclusive_epoch(fixture.store(), time(100), None).unwrap();
        DispatchCatalog::claim(fixture.store(), epoch, &due, time(101)).unwrap();
        let key = if remove_history {
            history_key(&due.effect, 1).unwrap()
        } else {
            attempt_reservation_key(&due.effect).unwrap()
        };
        fixture
            .store()
            .apply(AtomicBatch {
                expectations: vec![],
                mutations: vec![RowMutation { key, value: None }],
            })
            .unwrap();
        assert_eq!(
            DispatchCatalog::validate_view(&fixture.store().snapshot().unwrap()),
            Err(StoreError::Corrupt),
        );
    }
}

#[test]
fn coherent_dispatch_validator_walks_multiple_pages_and_leaves_foreign_registry_prefixes() {
    let fixture = Fixture::new();
    for identity in 1..=40 {
        let value = payload_fixture::value();
        let authority = payload_fixture::authority(&value, &format!("{identity:064x}"));
        fixture
            .store()
            .apply(AtomicBatch {
                expectations: vec![],
                mutations: vec![
                    RowMutation {
                        key: effect_row_key(&authority.link().effect).unwrap(),
                        value: Some(
                            EffectRecord::committed(&authority)
                                .unwrap()
                                .encode()
                                .unwrap(),
                        ),
                    },
                    RowMutation {
                        key: effect_payload_key(&authority.link().effect).unwrap(),
                        value: Some(
                            PayloadRecord::new(&authority, value)
                                .unwrap()
                                .encode()
                                .unwrap(),
                        ),
                    },
                    crate::dispatch_store::initial_due_mutation(&authority).unwrap(),
                ],
            })
            .unwrap();
    }
    fixture
        .store()
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: [Family::Maintenance, Family::Attempt, Family::Command]
                .into_iter()
                .map(|family| RowMutation {
                    key: RowKey {
                        family,
                        key: b"foreign-owned-prefix".to_vec(),
                    },
                    value: Some(b"foreign-format".to_vec()),
                })
                .collect(),
        })
        .unwrap();
    DispatchCatalog::validate_view(&fixture.store().snapshot().unwrap()).unwrap();
    assert_eq!(
        DispatchCatalog::counts(&fixture.store().snapshot().unwrap())
            .unwrap()
            .pending,
        40
    );
}
