use super::*;

pub(super) fn checkpoint(store: &EmbeddedStore, record: &CommandRecord) -> Vec<Option<Vec<u8>>> {
    let view = store.snapshot().unwrap();
    let mut keys = vec![
        record::command_row_key(record.id),
        record::attempt_row_key(record.id, record.attempt),
        result_row_key(record.id, record.attempt),
        MaintenanceProgress::key(),
        namespace_key(),
        writer::usage_row_key(
            &record.key.tenant,
            &record.key.namespace,
            incarnation(&record.key).unwrap(),
        )
        .unwrap(),
    ];
    keys.extend(record.effects.iter().flat_map(|effect| {
        [
            latent_effects::dispatch_store::effect_row_key(&effect.hex()).unwrap(),
            latent_effects::dispatch_store::effect_payload_key(&effect.hex()).unwrap(),
        ]
    }));
    keys.into_iter()
        .map(|key| view.get(&key).unwrap())
        .collect()
}

#[test]
fn current_policy_and_original_horizons_refuse_terminalization_and_purge_without_partial_rows() {
    let (_dir, store, effects) = setup();
    let record = completed(&store, &effects, "refuse-review");
    let owner = ResultMaintenanceOwner::default();
    owner
        .anchor(&store, None, observation(2000, 0), maintenance)
        .unwrap();
    let request = request(&record);
    let before = checkpoint(&store, &record);
    assert_eq!(
        owner.terminalize(&store, &request, observation(2001, 1), authorize),
        Err(AtomicError::Expired)
    );
    assert_eq!(checkpoint(&store, &record), before);
    let mut calls = 0;
    let denied = owner.terminalize(
        &store,
        &request,
        observation(2200, 200),
        |action, request, record| {
            calls += 1;
            if calls == 3 {
                return Err(AtomicError::PermissionDenied);
            }
            authorize(action, request, record)
        },
    );
    assert_eq!(denied, Err(AtomicError::PermissionDenied));
    assert_eq!(calls, 3);
    assert_eq!(checkpoint(&store, &record), before);
    owner
        .terminalize(&store, &request, observation(2200, 200), authorize)
        .unwrap();
    let reviewed = checkpoint(&store, &record);
    assert_eq!(
        owner.purge(&store, &request, observation(2299, 299), authorize),
        Err(AtomicError::Expired)
    );
    assert_eq!(checkpoint(&store, &record), reviewed);
    let mut calls = 0;
    assert_eq!(
        owner.purge(
            &store,
            &request,
            observation(2300, 300),
            |action, request, record| {
                calls += 1;
                if calls == 3 {
                    return Err(AtomicError::PermissionDenied);
                }
                authorize(action, request, record)
            }
        ),
        Err(AtomicError::PermissionDenied)
    );
    assert_eq!(calls, 3);
    assert_eq!(checkpoint(&store, &record), reviewed);
    let mut uncertain_clock = observation(2300, 300);
    uncertain_clock.time.continuity_proven = false;
    assert_eq!(
        owner.purge(&store, &request, uncertain_clock, authorize),
        Err(AtomicError::RecoveryRequired)
    );
    assert_eq!(checkpoint(&store, &record), reviewed);
}

#[test]
fn active_effect_claim_and_restore_pause_hold_every_audited_destructive_dependency() {
    let (_dir, store, effects) = setup();
    let record = completed(&store, &effects, "active-effect-review");
    let epoch = DispatchCatalog::begin_exclusive_epoch(&store, effect_time(102), None).unwrap();
    let page = DispatchCatalog::due_page(&store.snapshot().unwrap(), 102, None, 1, 4096).unwrap();
    let claim = DispatchCatalog::claim(&store, epoch, &page.rows[0], effect_time(102)).unwrap();
    DispatchCatalog::begin_send(&store, epoch, &claim.attempt, effect_time(103)).unwrap();
    let owner = ResultMaintenanceOwner::default();
    anchor(&owner, &store);
    let request = request(&record);
    let before = checkpoint(&store, &record);
    assert_eq!(
        owner.terminalize(&store, &request, observation(2200, 100), authorize),
        Err(AtomicError::InProgress)
    );
    assert_eq!(checkpoint(&store, &record), before);
    DispatchCatalog::complete(
        &store,
        epoch,
        &claim.attempt,
        AttemptReceipt {
            disposition: Disposition::Uncertain,
            reason: "retired-lost-response".into(),
            provider_receipt: None,
            observed_at_millis: 104,
        },
        None,
        effect_time(104),
    )
    .unwrap();
    owner
        .terminalize(&store, &request, observation(2200, 100), authorize)
        .unwrap();
    let paused = latent_state::recovery::RecoveryGuard::staging([7; 32], [8; 32], [9; 32])
        .unwrap()
        .prepare_staging()
        .unwrap();
    store.apply(paused).unwrap();
    let before = checkpoint(&store, &record);
    assert_eq!(
        owner.purge(&store, &request, observation(2300, 200), authorize),
        Err(AtomicError::Unavailable)
    );
    assert_eq!(checkpoint(&store, &record), before);
}

#[test]
fn interrupted_multi_attempt_purge_deletes_only_exact_retry_backpointers_and_releases_usage() {
    let (dir, store, effects) = setup();
    let admitted = claim(&store, input("multi-attempt-purge"));
    let watch = admitted.retirement();
    let physical = admitted.physical_work().unwrap();
    drop(admitted);
    physical.retire();
    let abort = CompleteEnvelope::technical_abort(
        &store.snapshot().unwrap(),
        watch.proven_noncommit().unwrap(),
        "fixture-retired".into(),
        time(101),
    )
    .unwrap();
    let aborted = confirm(abort, &store, &effects);
    let retry = writer::RetryRequest {
        request_id: "same-command-retry-2".into(),
        expected_abort: aborted.abort_proof().unwrap(),
    };
    let AdmissionDecision::New(prepared) = PreparedAdmission::retry(
        &store.snapshot().unwrap(),
        &input("multi-attempt-purge"),
        &retry,
        time(102),
        permission,
    )
    .unwrap() else {
        panic!()
    };
    let admitted = prepared.publish(&store, || Ok(())).unwrap();
    let final_command = confirm(
        CompleteEnvelope::success_without_intents(
            &store.snapshot().unwrap(),
            admitted,
            None,
            value(b"original-second-result"),
            time(103),
        )
        .unwrap(),
        &store,
        &effects,
    );
    assert_eq!(final_command.attempt, 2);
    let owner = ResultMaintenanceOwner::default();
    anchor(&owner, &store);
    let request = request(&final_command);
    assert!(
        owner
            .terminalize(&store, &request, observation(2200, 100), authorize)
            .unwrap()
            .complete
    );
    let progress = owner
        .purge(&store, &request, observation(2300, 200), authorize)
        .unwrap();
    assert_eq!(progress.purged_attempts, 1);
    assert!(!progress.complete);
    validate_view(&store.snapshot().unwrap(), foreign_codec).unwrap();
    drop(store);
    let store = open(&dir.path().join("state.redb"));
    assert!(
        ResultMaintenanceOwner::default()
            .purge(&store, &request, observation(2301, 201), authorize)
            .unwrap()
            .complete
    );
    let view = store.snapshot().unwrap();
    validate_view(&view, foreign_codec).unwrap();
    assert_retries_released(&view);
    let (usage, key, bytes) = writer::Usage::read(&view, &final_command.key).unwrap();
    let floor = view
        .get(&record::command_row_key(final_command.id))
        .unwrap()
        .unwrap();
    let expected_encoded = (key.key.len()
        + bytes.unwrap().len()
        + floor.len()
        + record::command_row_key(final_command.id).key.len()
        + 2 * 65) as u64;
    assert_eq!(usage.result_bytes, expected_encoded);
    assert_eq!(
        (usage.results, usage.reserved, usage.recovery_reserved),
        (1, 0, 0)
    );
    assert!(matches!(
        PreparedAdmission::retry(
            &view,
            &input("multi-attempt-purge"),
            &retry,
            time(2301),
            permission
        ),
        Err(AtomicError::Expired)
    ));
}

fn assert_retries_released(view: &latent_state::embedded::ReadView) {
    for (family, prefix) in [
        (Family::Attempt, b"command-attempt-v1\0".as_slice()),
        (Family::Result, b"command-result-v1\0".as_slice()),
        (Family::Maintenance, b"command-retry-v1\0".as_slice()),
        (Family::Maintenance, b"command-retry-index-v1\0".as_slice()),
    ] {
        assert!(view
            .scan_after(family, prefix, None, 128, 4096)
            .unwrap()
            .rows
            .is_empty());
    }
}
