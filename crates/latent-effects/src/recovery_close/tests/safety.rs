use super::*;

#[test]
fn guard_review_racing_prepared_close_refuses_without_changing_retained_work() {
    let fixture = Fixture::new(false);
    let plan = fixture.plan();
    let key = effect_row_key(&fixture.effect).unwrap();
    let record = fixture.row(&key);
    let payload_key = effect_payload_key(&fixture.effect).unwrap();
    let payload = fixture.row(&payload_key);
    let prepared = fixture.prepare(&plan);
    let guard = RecoveryGuard::decode(&fixture.row(&guard_key())).unwrap();
    let reviewed = guard
        .prepare_reviewed(
            &fixture.store.snapshot().unwrap(),
            [4; 32],
            |_, _, _| Ok(()),
        )
        .unwrap();
    fixture.store.apply(reviewed).unwrap();
    assert_eq!(
        fixture.store.apply(prepared.batch),
        Err(StoreError::Conflict)
    );
    assert_eq!(fixture.row(&key), record);
    assert_eq!(fixture.row(&payload_key), payload);
    assert!(fixture
        .store
        .snapshot()
        .unwrap()
        .get(&plan.receipt_key().unwrap())
        .unwrap()
        .is_none());
    assert_eq!(
        fixture
            .store
            .snapshot()
            .unwrap()
            .scan(
                Family::Maintenance,
                crate::dispatch_store::DUE_PREFIX,
                16,
                65536
            )
            .unwrap()
            .len(),
        1
    );
}

#[test]
fn changed_payload_or_attempt_history_cannot_cross_the_original_physical_close_cas() {
    for history in [false, true] {
        let fixture = Fixture::new(true);
        let plan = fixture.plan();
        let key = effect_row_key(&fixture.effect).unwrap();
        let original = fixture.row(&key);
        let prepared = fixture.prepare(&plan);
        let changed_key = if history {
            DispatchCatalog::history_page(
                &fixture.store.snapshot().unwrap(),
                &fixture.effect,
                None,
                16,
                65536,
            )
            .unwrap()
            .rows[0]
                .key()
                .unwrap()
        } else {
            effect_payload_key(&fixture.effect).unwrap()
        };
        let mut changed = fixture.row(&changed_key);
        changed.push(b' ');
        fixture
            .store
            .apply(AtomicBatch {
                expectations: vec![],
                mutations: vec![RowMutation {
                    key: changed_key.clone(),
                    value: Some(changed.clone()),
                }],
            })
            .unwrap();
        assert_eq!(
            fixture.store.apply(prepared.batch),
            Err(StoreError::Conflict)
        );
        assert_eq!(fixture.row(&key), original);
        assert_eq!(fixture.row(&changed_key), changed);
        assert!(fixture
            .store
            .snapshot()
            .unwrap()
            .get(&plan.receipt_key().unwrap())
            .unwrap()
            .is_none());
    }
}

#[test]
fn finite_close_plans_reject_duplicate_unknown_empty_and_changed_recovery_formats() {
    let fixture = Fixture::new(false);
    let view = fixture.store.snapshot().unwrap();
    for ids in [
        vec![],
        vec![fixture.effect.clone(); 2],
        vec![fixture.effect.clone(); EFFECTS + 1],
        vec!["b".repeat(64)],
    ] {
        assert!(inspect(
            &view,
            fixture.scope.clone(),
            "operator".into(),
            "close-1".into(),
            ids,
            "reviewed abandonment".into()
        )
        .is_err());
    }
    let plan = fixture.plan();
    let mut bytes = plan.encode().unwrap();
    bytes.push(b' ');
    assert!(ClosePlan::decode(&bytes).is_err());
    let mut wrong = plan.clone();
    wrong.schema_version = "lsf.effect-recovery-close.v2".into();
    assert!(wrong.encode().is_err());
    wrong = plan.clone();
    wrong.loss_window_digest = [9; 32];
    assert!(wrong.encode().is_err());
    let mut record = fixture.row(&effect_row_key(&fixture.effect).unwrap());
    record[4] = 3;
    assert!(EffectRecord::decode(&record).is_err());
    assert!(ClosePlan::decode(&vec![b'x'; PLAN_BYTES + 1]).is_err());
}
