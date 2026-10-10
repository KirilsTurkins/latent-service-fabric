//! Real installed envelopes, optional management metadata and original GC CAS.
use super::*;
use latent_effects::{
    dispatch::{effect_record_version, Disposition},
    dispatch_store::{
        effect_management::{
            EffectManagementAction, EffectManagementCatalog, EffectManagementError,
            EffectManagementEvidence, EffectManagementInput, EffectManagementPlan,
            EffectManagementRequest, RESERVATION_OWNER_PREFIX, RESERVED_DISPOSITION_BYTES,
        },
        effect_row_key, DispatchCatalog, DispatchEpoch,
    },
};
use latent_state::{
    embedded::{FencedStoreError, StoreError},
    reservation::{LogicalReservation, KEY_PREFIX},
    tenant,
};

fn effect_time(now: u64) -> EffectTime {
    EffectTime {
        unix_millis: now,
        continuity_proven: true,
    }
}

fn completed(store: &EmbeddedStore, effects: &EffectAuthorityOwner, key: &str) -> CommandRecord {
    let admitted = claim(store, input(key));
    confirm(
        CompleteEnvelope::success(
            &store.snapshot().unwrap(),
            admitted,
            None,
            vec![intent()],
            value(b"original managed result"),
            effects,
            time(101),
        )
        .unwrap(),
        store,
        effects,
    )
}

fn request(
    store: &EmbeddedStore,
    record: &CommandRecord,
    operation: &str,
) -> EffectManagementRequest {
    let bytes = store
        .snapshot()
        .unwrap()
        .get(&effect_row_key(&record.effects[0].hex()).unwrap())
        .unwrap()
        .unwrap();
    EffectManagementRequest::new(EffectManagementInput {
        actor_tenant: record.key.tenant.clone(),
        actor_subject: "operator:fixture".into(),
        namespace: record.key.namespace.clone(),
        incarnation: 1,
        caller_scope: record.key.recovery_scope.clone(),
        command: record.id.hex(),
        command_attempt: record.attempt,
        effect: record.effects[0].hex(),
        operation_id: operation.into(),
        action: EffectManagementAction::Terminate,
        expected_version: effect_record_version(&bytes).unwrap(),
        expected_policy_digest: "original-policy-v1".into(),
        original_request_digest: [3; 32],
        reason: "original reviewed disposition".into(),
        retry_delay_millis: 0,
    })
    .unwrap()
}

fn plan(
    store: &EmbeddedStore,
    epoch: DispatchEpoch,
    request: EffectManagementRequest,
) -> EffectManagementPlan {
    let view = store.snapshot().unwrap();
    let (batch, plan, replayed) =
        EffectManagementCatalog::prepare_plan(&view, epoch, request, effect_time(103), None)
            .unwrap()
            .into_parts();
    assert!(!replayed);
    drop(view);
    store.apply_fenced(batch, || Ok::<_, ()>(())).unwrap();
    plan
}

fn terminate(store: &EmbeddedStore, epoch: DispatchEpoch, plan: EffectManagementPlan) {
    let view = store.snapshot().unwrap();
    let (batch, receipt, replayed) = EffectManagementCatalog::prepare_mutation(
        &view,
        epoch,
        plan,
        EffectManagementEvidence::Administrator,
        effect_time(104),
    )
    .unwrap()
    .into_parts();
    assert!(!replayed);
    assert_eq!(receipt.after(), Disposition::DeadLettered);
    drop(view);
    store.apply_fenced(batch, || Ok::<_, ()>(())).unwrap();
}

fn optional_charge(store: &EmbeddedStore) -> u64 {
    let view = store.snapshot().unwrap();
    let rows = view
        .scan_after(Family::Maintenance, b"", None, 256, 4 * 1024 * 1024)
        .unwrap();
    assert!(rows.resume.is_none());
    let mut reservation_prefix = KEY_PREFIX.to_vec();
    reservation_prefix.extend_from_slice(RESERVATION_OWNER_PREFIX);
    rows.rows
        .iter()
        .filter(|(key, _)| EffectManagementCatalog::owns_row(key))
        .map(|(key, bytes)| {
            tenant::row_charge(key, bytes).unwrap()
                + if key.key.starts_with(&reservation_prefix) {
                    LogicalReservation::decode(bytes).unwrap().bytes
                } else {
                    0
                }
        })
        .sum()
}

fn namespace_usage(store: &EmbeddedStore) -> writer::Usage {
    let key = writer::usage_row_key("tenant", "aggregate", 1).unwrap();
    writer::Usage::decode(&store.snapshot().unwrap().get(&key).unwrap().unwrap()).unwrap()
}

fn observation(now: u64, elapsed: u64) -> MaintenanceClock {
    MaintenanceClock {
        time: time(now),
        boot: [7; 32],
        monotonic_millis: elapsed,
    }
}

fn retention(record: &CommandRecord) -> RetentionRequest {
    RetentionRequest {
        key: record.key.clone(),
        expected_command_digest: RetentionRequest::command_digest(record).unwrap(),
        actor: "operator:fixture".into(),
        operation_id: "original-retention".into(),
        policy: "original-destructive-policy".into(),
        retain_until_millis: 40_000,
        inbox_expires_at_millis: None,
    }
}

fn authorize(
    _: RetentionAction,
    request: &RetentionRequest,
    record: Option<&CommandRecord>,
) -> Result<(), AtomicError> {
    if request.actor != "operator:fixture" || request.policy != "original-destructive-policy" {
        return Err(AtomicError::PermissionDenied);
    }
    permission(CommandAccess::Replay, record)
}

#[test]
fn actual_optional_management_rows_and_future_disposition_share_one_ledger_and_reopen() {
    let (dir, store, effects) = accounted::setup(8);
    let record = completed(&store, &effects, "managed-ledger");
    let epoch = DispatchCatalog::begin_exclusive_epoch(&store, effect_time(102), None).unwrap();
    let before = accounted::usage(&store);
    let initial = namespace_usage(&store);
    let request = request(&store, &record, "original-plan");
    let original_plan = plan(&store, epoch, request.clone());
    let charge = optional_charge(&store);
    assert!(charge > RESERVED_DISPOSITION_BYTES);
    assert!(charge < 2 * RESERVED_DISPOSITION_BYTES);
    let planned = accounted::usage(&store);
    assert_eq!(planned.generation, before.generation + 1);
    assert_eq!(
        planned.usage.effect_bytes,
        before.usage.effect_bytes + charge
    );
    assert_eq!(
        namespace_usage(&store).effect_bytes,
        initial.effect_bytes + charge
    );
    assert_eq!(planned.usage.effect_rows, before.usage.effect_rows);
    assert_eq!(planned.usage.result_bytes, before.usage.result_bytes);
    assert_eq!(planned.usage.recovery_bytes, before.usage.recovery_bytes);
    census::census(&store).unwrap();

    // Same operation returns the original plan; no quota or clock advances.
    let (batch, replayed_plan, replayed) = EffectManagementCatalog::prepare_plan(
        &store.snapshot().unwrap(),
        epoch,
        request,
        effect_time(103),
        None,
    )
    .unwrap()
    .into_parts();
    assert!(replayed);
    assert_eq!(replayed_plan, original_plan);
    assert!(batch.mutations.is_empty());
    store.apply(batch).unwrap();
    assert_eq!(accounted::usage(&store), planned);

    terminate(&store, epoch, original_plan.clone());
    let finished = accounted::usage(&store);
    let remaining = optional_charge(&store);
    assert!(remaining < charge);
    assert_eq!(finished.generation, planned.generation + 1);
    assert_eq!(
        finished.usage.effect_bytes,
        before.usage.effect_bytes + remaining
    );
    assert_eq!(
        namespace_usage(&store).effect_bytes,
        initial.effect_bytes + remaining
    );
    let (batch, _, replayed) = EffectManagementCatalog::prepare_mutation(
        &store.snapshot().unwrap(),
        epoch,
        original_plan,
        EffectManagementEvidence::Administrator,
        effect_time(105),
    )
    .unwrap()
    .into_parts();
    assert!(replayed);
    assert!(batch.mutations.is_empty());
    store.apply(batch).unwrap();
    assert_eq!(accounted::usage(&store), finished);
    let report = census::census(&store).unwrap();
    drop(store);
    let reopened = open(&dir.path().join("state.redb"));
    assert_eq!(accounted::usage(&reopened), finished);
    assert_eq!(census::census(&reopened).unwrap(), report);
    DispatchCatalog::validate_view(&reopened.snapshot().unwrap()).unwrap();
}

#[test]
fn namespace_quota_refuses_optional_management_without_writing_or_quarantining_store() {
    let (_dir, store, effects) = accounted::setup(8);
    let record = completed(&store, &effects, "managed-capacity");
    let epoch = DispatchCatalog::begin_exclusive_epoch(&store, effect_time(102), None).unwrap();
    let mut namespace = NamespaceRecord::decode(
        &store
            .snapshot()
            .unwrap()
            .get(&namespace_key())
            .unwrap()
            .unwrap(),
    )
    .unwrap();
    namespace.quota.effect_bytes = namespace_usage(&store).effect_bytes;
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: namespace_key(),
                value: Some(namespace.encode().unwrap()),
            }],
        })
        .unwrap();
    let before = accounted::usage(&store);
    let original = namespace_usage(&store).encode().unwrap();
    assert!(matches!(
        EffectManagementCatalog::prepare_plan(
            &store.snapshot().unwrap(),
            epoch,
            request(&store, &record, "refused-plan"),
            effect_time(103),
            None,
        ),
        Err(EffectManagementError::Store(StoreError::Capacity))
    ));
    assert_eq!(optional_charge(&store), 0);
    assert_eq!(namespace_usage(&store).encode().unwrap(), original);
    assert_eq!(accounted::usage(&store), before);
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![],
        })
        .unwrap();
    assert!(inspect(
        &store.snapshot().unwrap(),
        &record.key,
        time(104),
        permission
    )
    .unwrap()
    .1
    .is_some());
    census::census(&store).unwrap();
}

#[test]
fn simultaneous_original_management_plans_conflict_without_rebinding_or_quota_refresh() {
    let (_dir, store, effects) = accounted::setup(8);
    let record = completed(&store, &effects, "managed-cas");
    let epoch = DispatchCatalog::begin_exclusive_epoch(&store, effect_time(102), None).unwrap();
    let view = store.snapshot().unwrap();
    let (first, first_plan, _) = EffectManagementCatalog::prepare_plan(
        &view,
        epoch,
        request(&store, &record, "first"),
        effect_time(103),
        None,
    )
    .unwrap()
    .into_parts();
    let (second, second_plan, _) = EffectManagementCatalog::prepare_plan(
        &view,
        epoch,
        request(&store, &record, "second"),
        effect_time(103),
        None,
    )
    .unwrap()
    .into_parts();
    assert_eq!(first_plan.sequence(), second_plan.sequence());
    drop(view);
    store.apply_fenced(first, || Ok::<_, ()>(())).unwrap();
    let first_usage = accounted::usage(&store);
    assert!(matches!(
        store.apply_fenced(second, || Ok::<_, ()>(())),
        Err(FencedStoreError::Store(StoreError::Conflict))
    ));
    assert_eq!(accounted::usage(&store), first_usage);
    assert!(EffectManagementCatalog::plan_for_actor(
        &store.snapshot().unwrap(),
        "tenant",
        "operator:fixture",
        "second"
    )
    .unwrap()
    .is_none());
    census::census(&store).unwrap();
}

#[test]
fn unfinished_management_plan_protects_original_rows_after_its_deadline() {
    let (_dir, store, effects) = accounted::setup(8);
    let record = completed(&store, &effects, "managed-protection");
    let epoch = DispatchCatalog::begin_exclusive_epoch(&store, effect_time(102), None).unwrap();
    let original_plan = plan(&store, epoch, request(&store, &record, "unfinished"));
    assert!(original_plan.expires_at_millis() < 39_000);
    let owner = ResultMaintenanceOwner::default();
    owner
        .anchor(&store, None, observation(39_000, 0), |record| {
            permission(CommandAccess::Replay, record)
        })
        .unwrap();
    let before = accounted::usage(&store);
    let original_effect = store
        .snapshot()
        .unwrap()
        .get(&effect_row_key(&record.effects[0].hex()).unwrap())
        .unwrap();
    assert!(matches!(
        DispatchCatalog::retention_rows(&store.snapshot().unwrap(), &record.effects[0].hex()),
        Err(StoreError::Capacity)
    ));
    assert_eq!(
        owner.terminalize(
            &store,
            &retention(&record),
            observation(39_001, 1),
            authorize
        ),
        Err(AtomicError::Limit)
    );
    assert_eq!(accounted::usage(&store), before);
    assert_eq!(
        store
            .snapshot()
            .unwrap()
            .get(&effect_row_key(&record.effects[0].hex()).unwrap())
            .unwrap(),
        original_effect
    );
    assert!(EffectManagementCatalog::plan_for_actor(
        &store.snapshot().unwrap(),
        "tenant",
        "operator:fixture",
        "unfinished"
    )
    .unwrap()
    .is_some());
    census::census(&store).unwrap();
}

#[test]
fn completed_management_closure_is_purged_only_with_its_original_quota_and_native_view_fences() {
    let (_dir, store, effects) = accounted::setup(8);
    let record = completed(&store, &effects, "managed-purge");
    let epoch = DispatchCatalog::begin_exclusive_epoch(&store, effect_time(102), None).unwrap();
    let original_plan = plan(&store, epoch, request(&store, &record, "finished"));
    terminate(&store, epoch, original_plan);
    let owner = ResultMaintenanceOwner::default();
    owner
        .anchor(&store, None, observation(39_000, 0), |record| {
            permission(CommandAccess::Replay, record)
        })
        .unwrap();
    let request = retention(&record);
    assert!(
        owner
            .terminalize(&store, &request, observation(39_001, 1), authorize)
            .unwrap()
            .complete
    );
    let retained = store.snapshot().unwrap();
    let before = accounted::usage(&store);
    assert_eq!(
        owner.purge(&store, &request, observation(40_000, 1000), authorize),
        Err(AtomicError::Limit)
    );
    assert_eq!(accounted::usage(&store), before);
    drop(retained);
    let progress = owner
        .purge(&store, &request, observation(40_000, 1000), authorize)
        .unwrap();
    assert_eq!(progress.purged_effects, 1);
    assert!(!progress.complete);
    assert_eq!(optional_charge(&store), 0);
    assert_eq!(accounted::usage(&store).usage.effect_rows, 0);
    assert_eq!(accounted::usage(&store).usage.effect_bytes, 0);
    assert_eq!(accounted::usage(&store).usage.payload_bytes, 0);
    census::census(&store).unwrap();
    assert!(
        owner
            .purge(&store, &request, observation(40_001, 1001), authorize)
            .unwrap()
            .complete
    );
    census::census(&store).unwrap();
    DispatchCatalog::validate_view(&store.snapshot().unwrap()).unwrap();
    assert!(store
        .snapshot()
        .unwrap()
        .get(&effect_row_key(&record.effects[0].hex()).unwrap())
        .unwrap()
        .is_none());
    assert!(matches!(
        inspect(
            &store.snapshot().unwrap(),
            &record.key,
            time(40_002),
            permission
        ),
        Err(AtomicError::Expired)
    ));
}
