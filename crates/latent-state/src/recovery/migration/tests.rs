//! Actual engine/codec/checkpoint schedules. Controlled reviewers do not prove
//! authenticated Wire, publication rollout, or physical root qualification.
pub(crate) mod fixture;
use super::*;
use crate::{
    embedded::{AtomicBatch, FencedStoreError, RowMutation},
    namespace::{
        catalog::{NamespaceCatalog, NamespaceMutation, NamespaceOperationContext},
        compatibility::{require_composition, ReviewedSchema, SchemaDeclaration},
        NamespaceTransition,
    },
    session::{StateError, StateSession},
    tenant::TenantRecord,
};
use fixture::*;

#[test]
fn original_status_survives_completion_without_mutation_or_inferred_resume() {
    let fixture = Fixture::new(AggregateMigrationRecipe::Count, true);
    let view = fixture.store.snapshot().unwrap();
    assert!(inspect_progress(
        &view,
        &fixture.request.scope,
        &fixture.request.operator_id,
        &fixture.request.operation_id
    )
    .unwrap()
    .is_none());
    drop(view);
    fixture.apply(MigrationPhase::Stage);
    let view = fixture.store.snapshot().unwrap();
    let staged = inspect_progress(
        &view,
        &fixture.request.scope,
        &fixture.request.operator_id,
        &fixture.request.operation_id,
    )
    .unwrap()
    .unwrap();
    assert!(!staged.completed());
    assert!(inspect_progress(
        &view,
        &fixture.request.scope,
        "another-operator",
        &fixture.request.operation_id
    )
    .unwrap()
    .is_none());
    assert_eq!(
        view.get(&fixture.request.progress_key().unwrap())
            .unwrap()
            .unwrap(),
        staged.encode().unwrap()
    );
    drop(view);
    fixture.apply(MigrationPhase::Complete);
    let before = fixture.progress_bytes();
    let view = fixture.store.snapshot().unwrap();
    let completed = inspect_progress(
        &view,
        &fixture.request.scope,
        &fixture.request.operator_id,
        &fixture.request.operation_id,
    )
    .unwrap()
    .unwrap();
    assert!(completed.completed());
    assert_eq!(completed.encode().unwrap(), before);
    assert_eq!(fixture.progress_bytes(), before);
    assert_eq!(
        fixture.current().history.status,
        crate::namespace::history::HistoryStatus::ReconciliationRequired
    );
    fixture.require_census();
}

#[test]
fn actual_count_and_java_cells_change_format_once_and_remain_paused() {
    for recipe in [
        AggregateMigrationRecipe::Count,
        AggregateMigrationRecipe::JavaAggregate,
    ] {
        let fixture = Fixture::new(recipe, true);
        let old = fixture.cell();
        let before = fixture.current();
        let staged = fixture.apply(MigrationPhase::Stage);
        assert_eq!(staged.action(), MigrationAction::Stage);
        assert_eq!(fixture.cell(), old);
        assert_eq!(
            fixture.current().history.status,
            crate::namespace::history::HistoryStatus::ReconciliationRequired
        );
        let completed = fixture.apply(MigrationPhase::Complete);
        assert_eq!(completed.action(), MigrationAction::Complete);
        let after = fixture.current();
        assert_eq!(after.namespace.id, before.namespace.id);
        assert_eq!(after.namespace.tenant, before.namespace.tenant);
        assert_eq!(
            after.namespace.version.incarnation,
            before.namespace.version.incarnation
        );
        assert_eq!(
            after.namespace.version.generation,
            before.namespace.version.generation + 1
        );
        assert_eq!(
            after.history.epochs.schema,
            before.history.epochs.schema + 1
        );
        assert_eq!(
            after.history.epochs.recovery,
            before.history.epochs.recovery
        );
        let value = fixture.cell().value.unwrap();
        assert_eq!(value.media_type, "application/vnd.lsf.aggregate-v2");
        assert_eq!(
            value.bytes,
            [b"AG\x02\0".as_slice(), &u64::MAX.to_le_bytes()].concat()
        );
        assert_ne!(
            completed.progress().result_view_token().unwrap(),
            fixture.request.expected_view
        );
        fixture.require_census();
        assert_eq!(
            crate::recovery::require_namespace_ready(
                &fixture.store.snapshot().unwrap(),
                &fixture.request.scope.tenant,
                &fixture.request.scope.namespace,
                fixture.request.scope.incarnation
            ),
            Err(StoreError::Unavailable)
        );
    }
}

#[test]
fn actual_restart_keeps_incomplete_original_progress_and_refuses_namespace_bypass() {
    let mut fixture = Fixture::new(AggregateMigrationRecipe::Count, true);
    fixture.apply(MigrationPhase::Stage);
    let original = fixture.progress_bytes();
    fixture.reopen();
    assert_eq!(fixture.progress_bytes(), original);
    let current = fixture.current();
    let context = NamespaceOperationContext {
        tenant: current.namespace.tenant.clone(),
        actor: "operator".into(),
        operation_id: "bypass-migration".into(),
    };
    let mutation = NamespaceMutation::Transition {
        id: current.namespace.id.clone(),
        expected: current.namespace.version,
        action: NamespaceTransition::Retire,
    };
    assert!(matches!(
        NamespaceCatalog::new().prepare(&fixture.store, context, &mutation, 0),
        Err(crate::namespace::NamespaceError::Unavailable)
    ));
    let replay = fixture.apply(MigrationPhase::Stage);
    assert_eq!(replay.action(), MigrationAction::Replay);
    assert_eq!(fixture.progress_bytes(), original);
    fixture.apply(MigrationPhase::Complete);
    fixture.reopen();
    assert!(
        AggregateMigrationProgress::decode(&fixture.progress_bytes())
            .unwrap()
            .completed()
    );
    fixture.require_census();
}

#[test]
fn current_reviewer_and_real_writer_refusal_do_not_publish_a_pause_or_partial_cell() {
    let fixture = Fixture::new(AggregateMigrationRecipe::Count, true);
    let before = fixture.cell();
    let view = fixture.store.snapshot().unwrap();
    let checkpoint = fixture.checkpoint(&view).unwrap();
    assert!(matches!(
        AggregateMigrationPlan::prepare(
            &view,
            &fixture.request,
            &checkpoint,
            &fixture.schema,
            (fixture.recipe, MigrationPhase::Stage),
            deadline(),
            |_, _, _| Err(StoreError::Unavailable)
        ),
        Err(MigrationError::Review(StoreError::Unavailable))
    ));
    let plan = fixture.prepare(&view, MigrationPhase::Stage).unwrap();
    let (batch, _, _) = plan.into_parts();
    drop(view);
    assert!(matches!(
        fixture
            .store
            .apply_fenced(batch, || Err(StoreError::Unavailable)),
        Err(FencedStoreError::Fence(StoreError::Unavailable))
    ));
    assert!(fixture
        .store
        .snapshot()
        .unwrap()
        .get(&fixture.request.progress_key().unwrap())
        .unwrap()
        .is_none());
    assert_eq!(fixture.cell(), before);
    assert_eq!(
        fixture.current().history.status,
        crate::namespace::history::HistoryStatus::Ready
    );
    fixture.require_census();
}

#[test]
fn full_unit_checkpoint_detects_unrelated_valid_rows_and_counter_drift() {
    let fixture = Fixture::new(AggregateMigrationRecipe::Count, true);
    fixture.apply(MigrationPhase::Stage);
    let old = fixture.cell();
    let key = crate::tenant::quota_key(&fixture.request.scope.tenant).unwrap();
    let view = fixture.store.snapshot().unwrap();
    let mut record = TenantRecord::decode(&view.get(&key).unwrap().unwrap()).unwrap();
    drop(view);
    record.usage.metadata_bytes += 1;
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key,
                value: Some(record.encode().unwrap()),
            }],
        })
        .unwrap();
    assert!(matches!(
        fixture.prepare(&fixture.store.snapshot().unwrap(), MigrationPhase::Complete),
        Err(MigrationError::Review(StoreError::Conflict))
    ));
    assert_eq!(fixture.cell(), old);
    assert!(
        !AggregateMigrationProgress::decode(&fixture.progress_bytes())
            .unwrap()
            .completed()
    );
}

#[test]
fn normalized_original_quota_cannot_hide_a_forged_canonical_stage_counter() {
    let fixture = Fixture::new(AggregateMigrationRecipe::Count, true);
    fixture.apply(MigrationPhase::Stage);
    let progress_key = fixture.request.progress_key().unwrap();
    let quota_key = crate::tenant::quota_key(&fixture.request.scope.tenant).unwrap();
    let mut progress = AggregateMigrationProgress::decode(&fixture.progress_bytes()).unwrap();
    let view = fixture.store.snapshot().unwrap();
    let mut quota = TenantRecord::decode(&view.get(&quota_key).unwrap().unwrap()).unwrap();
    drop(view);
    quota.usage.metadata_bytes += 32;
    let bytes = quota.encode().unwrap();
    progress.set_staged_quota(Some(bytes.clone())).unwrap();
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![
                RowMutation {
                    key: quota_key,
                    value: Some(bytes),
                },
                RowMutation {
                    key: progress_key,
                    value: Some(progress.encode().unwrap()),
                },
            ],
        })
        .unwrap();
    assert!(matches!(
        fixture.prepare(&fixture.store.snapshot().unwrap(), MigrationPhase::Complete),
        Err(MigrationError::Source(StoreError::Corrupt))
    ));
}

#[test]
fn wrong_tenant_old_view_changed_package_and_changed_recipe_refuse_exact_original_operation() {
    let fixture = Fixture::new(AggregateMigrationRecipe::Count, true);
    fixture.apply(MigrationPhase::Stage);
    let view = fixture.store.snapshot().unwrap();
    let checkpoint = fixture.checkpoint(&view).unwrap();
    for change in 0..4 {
        let mut request = fixture.request.clone();
        let selected = if change == 3 {
            AggregateMigrationRecipe::JavaAggregate
        } else {
            fixture.recipe
        };
        match change {
            0 => request.scope.tenant.0 = "other-tenant".into(),
            1 => request.expected_view[35] ^= 1,
            2 => request.package_digest[0] ^= 1,
            _ => {}
        }
        assert!(AggregateMigrationPlan::prepare(
            &view,
            &request,
            &checkpoint,
            &fixture.schema,
            (selected, MigrationPhase::Complete),
            deadline(),
            |_, _, _| Ok(())
        )
        .is_err());
    }
    assert!(
        !AggregateMigrationProgress::decode(&fixture.progress_bytes())
            .unwrap()
            .completed()
    );
}

#[test]
fn unsupported_value_entity_or_second_key_refuses_before_durable_marker() {
    for selected in 0..4 {
        let fixture = Fixture::selected(
            AggregateMigrationRecipe::Count,
            true,
            32,
            (selected == 3).then(|| String::from("original-entity")),
        );
        let mut row = fixture.state_row();
        match selected {
            0 => row.value.as_mut().unwrap().push(0), // Original cell codec rejects trailing bytes.
            1 => row.key.key.push(b'x'),
            2 => {
                let mut additional = row.clone();
                additional.key.key.push(b'x');
                fixture
                    .store
                    .apply(AtomicBatch {
                        expectations: vec![],
                        mutations: vec![additional],
                    })
                    .unwrap();
            }
            _ => {}
        }
        if selected < 2 {
            fixture
                .store
                .apply(AtomicBatch {
                    expectations: vec![],
                    mutations: vec![row],
                })
                .unwrap();
        }
        assert!(fixture
            .prepare(&fixture.store.snapshot().unwrap(), MigrationPhase::Stage)
            .is_err());
        assert!(fixture
            .store
            .snapshot()
            .unwrap()
            .get(&fixture.request.progress_key().unwrap())
            .unwrap()
            .is_none());
    }
}

#[test]
fn actual_schema_epoch_change_refuses_old_writer_and_preserves_historical_receipt() {
    let fixture = Fixture::new(AggregateMigrationRecipe::Count, true);
    fixture.apply(MigrationPhase::Stage);
    let completed = fixture.apply(MigrationPhase::Complete);
    let exact = completed.progress().encode().unwrap();
    let original_token = completed.progress().result_view_token().unwrap();
    let current = fixture.current();
    let v1 = recipe::schema_ids().unwrap().0;
    let old = ReviewedSchema::accept_with(
        SchemaDeclaration {
            package_digest: [99; 32],
            readers: vec![v1.clone()],
            writers: vec![v1],
        },
        [99; 32],
        [98; 32],
        |_, _, _| Ok(()),
    )
    .unwrap();
    assert_eq!(
        require_composition(&current.namespace, &[old]),
        Err(crate::namespace::NamespaceError::UnsupportedFormat)
    );
    let replay = fixture.apply(MigrationPhase::Complete);
    assert_eq!(replay.action(), MigrationAction::Replay);
    assert_eq!(replay.progress().encode().unwrap(), exact);
    assert_eq!(
        replay.progress().result_view_token().unwrap(),
        original_token
    );
    assert!(matches!(
        StateSession::open(
            &fixture.store.snapshot().unwrap(),
            fixture.request.scope.clone(),
            Default::default(),
            |_, _| Ok(())
        ),
        Err(StateError::PermissionDenied)
    ));
}

#[test]
fn corrupt_checkpoint_missing_decoder_or_recipe_artifact_never_mutates_source() {
    let mut fixture = Fixture::new(AggregateMigrationRecipe::Count, true);
    let cell = fixture.cell();
    fixture.archive[50] ^= 1;
    assert!(fixture
        .checkpoint(&fixture.store.snapshot().unwrap())
        .is_err());
    assert_eq!(fixture.cell(), cell);
    for omitted in 0..2 {
        let mut fixture = Fixture::new(AggregateMigrationRecipe::Count, true);
        let mut metadata = fixture.metadata.clone();
        if omitted == 0 {
            metadata.decoder_formats.clear();
        } else {
            metadata
                .required_artifacts
                .retain(|artifact| artifact.identity != fixture.recipe.identity());
        }
        fixture.archive = fixture.export(metadata);
        fixture.refresh_checkpoint_request();
        assert!(fixture
            .prepare(&fixture.store.snapshot().unwrap(), MigrationPhase::Stage)
            .is_err());
        assert!(fixture
            .store
            .snapshot()
            .unwrap()
            .get(&fixture.request.progress_key().unwrap())
            .unwrap()
            .is_none());
    }
}

#[test]
fn canonical_progress_rejects_unknown_version_nested_amplification_and_truncation() {
    let fixture = Fixture::new(AggregateMigrationRecipe::Count, true);
    fixture.apply(MigrationPhase::Stage);
    let bytes = fixture.progress_bytes();
    for length in 0..bytes.len() {
        assert!(AggregateMigrationProgress::decode(&bytes[..length]).is_err());
    }
    for position in [4, 6] {
        let mut corrupt = bytes.clone();
        corrupt[position] = 255;
        if position == 6 {
            corrupt[position + 1] = 255;
        }
        let checksum = corrupt.len() - 32;
        let digest = sha2::Sha256::digest(&corrupt[..checksum]);
        corrupt[checksum..].copy_from_slice(&digest);
        assert!(AggregateMigrationProgress::decode(&corrupt).is_err());
    }
    assert_eq!(
        AggregateMigrationProgress::decode(&bytes)
            .unwrap()
            .encode()
            .unwrap(),
        bytes
    );
}

#[test]
fn expired_original_deadline_and_full_tenant_metadata_refuse_before_stage() {
    let fixture = Fixture::new(AggregateMigrationRecipe::Count, true);
    let view = fixture.store.snapshot().unwrap();
    let checkpoint = fixture.checkpoint(&view).unwrap();
    assert!(matches!(
        AggregateMigrationPlan::prepare(
            &view,
            &fixture.request,
            &checkpoint,
            &fixture.schema,
            (fixture.recipe, MigrationPhase::Stage),
            std::time::Instant::now(),
            |_, _, _| Ok(())
        ),
        Err(MigrationError::Deadline)
    ));
    drop(view);
    let full = Fixture::selected(AggregateMigrationRecipe::Count, true, 5, None);
    full.require_census();
    assert!(matches!(
        full.prepare(&full.store.snapshot().unwrap(), MigrationPhase::Stage),
        Err(MigrationError::Capacity)
    ));
    assert!(full
        .store
        .snapshot()
        .unwrap()
        .get(&full.request.progress_key().unwrap())
        .unwrap()
        .is_none());
}

#[test]
fn explicit_legacy_counter_absence_stays_absent_without_guessing_quota() {
    let fixture = Fixture::new(AggregateMigrationRecipe::Count, false);
    fixture.apply(MigrationPhase::Stage);
    fixture.apply(MigrationPhase::Complete);
    let view = fixture.store.snapshot().unwrap();
    assert!(crate::tenant::inspect(&view, &fixture.request.scope.tenant)
        .unwrap()
        .is_none());
    assert!(view.get(&crate::tenant::guard_key()).unwrap().is_none());
    assert_eq!(fixture.cell().value.unwrap().bytes.len(), 12);
}
