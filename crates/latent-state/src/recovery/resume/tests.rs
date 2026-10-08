//! Real selected-engine row/receipt/counter schedules with controlled reviewers.
//! These do not qualify signed deployment, current RPC authorization or restore.
use super::*;
use crate::{
    embedded::{AtomicBatch, FencedStoreError, RowMutation},
    namespace::catalog::{NamespaceCatalog, NamespaceMutation, NamespaceOperationContext},
    namespace::NamespaceTransition,
    recovery::migration::{
        tests::fixture::Fixture, AggregateMigrationRecipe, MigrationError, MigrationPhase,
    },
};
use std::time::{Duration, Instant};

fn deadline() -> Instant {
    Instant::now() + Duration::from_secs(20)
}

fn complete(fixture: &Fixture) {
    fixture.apply(MigrationPhase::Stage);
    fixture.apply(MigrationPhase::Complete);
}

fn request(fixture: &Fixture) -> MigrationResumeRequest {
    let current = fixture.current();
    MigrationResumeRequest {
        scope: current.scope(),
        operation_id: "activate-format".into(),
        operator_id: "operator".into(),
        expected_view: current.view_token().unwrap(),
        migration: fixture.request.clone(),
        review_digest: [61; 32],
    }
}

fn prepare(
    fixture: &Fixture,
    request: &MigrationResumeRequest,
) -> Result<MigrationResumePlan, MigrationError> {
    MigrationResumePlan::prepare(
        &fixture.store.snapshot().unwrap(),
        request,
        &fixture.schema,
        deadline(),
        |_, _, _| Ok(()),
    )
}

fn apply(fixture: &Fixture, plan: MigrationResumePlan) -> MigrationResumeReceipt {
    let (batch, receipt, _) = plan.into_parts();
    fixture
        .store
        .apply_fenced(batch, || Ok::<(), StoreError>(()))
        .unwrap();
    receipt
}

#[test]
fn count_and_java_activate_once_with_original_cells_progress_and_tenant_census() {
    for recipe in [
        AggregateMigrationRecipe::Count,
        AggregateMigrationRecipe::JavaAggregate,
    ] {
        let fixture = Fixture::new(recipe, true);
        complete(&fixture);
        let cell = fixture.cell();
        let progress = fixture.progress_bytes();
        let before = fixture.current();
        let request = request(&fixture);
        let plan = prepare(&fixture, &request).unwrap();
        assert_eq!(plan.action(), MigrationResumeAction::Activate);
        let receipt = apply(&fixture, plan);
        assert_eq!(fixture.cell(), cell);
        assert_eq!(fixture.progress_bytes(), progress);
        let after = fixture.current();
        assert_eq!(after.namespace, receipt.namespace().unwrap());
        assert_eq!(after.history, receipt.history().unwrap());
        assert_eq!(after.namespace.status, NamespaceStatus::Active);
        assert_eq!(after.history.status, HistoryStatus::Ready);
        assert_eq!(after.history.epochs, before.history.epochs);
        assert_eq!(
            after.namespace.version.incarnation,
            before.namespace.version.incarnation
        );
        assert_eq!(
            after.namespace.version.generation,
            before.namespace.version.generation + 1
        );
        crate::recovery::require_namespace_ready(
            &fixture.store.snapshot().unwrap(),
            &request.scope.tenant,
            &request.scope.namespace,
            request.scope.incarnation,
        )
        .unwrap();
        let replay = prepare(&fixture, &request).unwrap();
        assert_eq!(replay.action(), MigrationResumeAction::Replay);
        assert_eq!(
            apply(&fixture, replay).encode().unwrap(),
            receipt.encode().unwrap()
        );
        assert_eq!(fixture.current().namespace, after.namespace);
        assert_eq!(fixture.cell(), cell);
        fixture.require_census();
        let view = fixture.store.snapshot().unwrap();
        let retained = fixture.closure(&view, vec![]).unwrap().inventory;
        assert!(retained
            .require_decoders(&fixture.metadata.decoder_formats)
            .is_err());
        let mut installed = fixture.metadata.decoder_formats.clone();
        installed.push(retained_format());
        retained.require_decoders(&installed).unwrap();
    }
}

#[test]
fn missing_incomplete_foreign_schema_and_refreshed_original_input_never_activate() {
    let fixture = Fixture::new(AggregateMigrationRecipe::Count, true);
    let missing = request(&fixture);
    assert!(prepare(&fixture, &missing).is_err());
    fixture.apply(MigrationPhase::Stage);
    let staged = request(&fixture);
    assert!(prepare(&fixture, &staged).is_err());
    assert!(
        !AggregateMigrationProgress::decode(&fixture.progress_bytes())
            .unwrap()
            .completed()
    );
    fixture.apply(MigrationPhase::Complete);
    let before = fixture.current().view_token().unwrap();
    let original = request(&fixture);
    let mut wrong = original.clone();
    wrong.scope.tenant.0 = "other-tenant".into();
    assert!(prepare(&fixture, &wrong).is_err());
    let mut wrong = original.clone();
    wrong.migration.package_digest = [62; 32];
    assert!(prepare(&fixture, &wrong).is_err());
    let mut wrong = original.clone();
    wrong.migration.expected_view = original.expected_view.clone();
    assert!(prepare(&fixture, &wrong).is_err());
    let mut wrong = original.clone();
    wrong.expected_view = wrong.migration.expected_view.clone();
    assert!(prepare(&fixture, &wrong).is_err());
    let v2 = SchemaId::parse(&original.scope.state_schema).unwrap();
    let foreign = crate::namespace::compatibility::ReviewedSchema::accept_with(
        crate::namespace::compatibility::SchemaDeclaration {
            package_digest: [63; 32],
            readers: vec![v2.clone()],
            writers: vec![v2],
        },
        [63; 32],
        [64; 32],
        |_, _, _| Ok(()),
    )
    .unwrap();
    assert!(MigrationResumePlan::prepare(
        &fixture.store.snapshot().unwrap(),
        &original,
        &foreign,
        deadline(),
        |_, _, _| Ok(())
    )
    .is_err());
    assert_eq!(fixture.current().view_token().unwrap(), before);
    assert!(
        inspect_receipt(&fixture.store.snapshot().unwrap(), &original)
            .unwrap()
            .is_none()
    );
    fixture.require_census();
}

#[test]
fn original_current_denial_and_actual_guard_race_leave_completed_migration_paused() {
    let fixture = Fixture::new(AggregateMigrationRecipe::Count, true);
    complete(&fixture);
    let request = request(&fixture);
    assert!(matches!(
        MigrationResumePlan::prepare(
            &fixture.store.snapshot().unwrap(),
            &request,
            &fixture.schema,
            deadline(),
            |_, _, _| Err(StoreError::Unavailable)
        ),
        Err(MigrationError::Review(StoreError::Unavailable))
    ));
    let plan = prepare(&fixture, &request).unwrap();
    let (batch, _, _) = plan.into_parts();
    assert!(matches!(
        fixture
            .store
            .apply_fenced(batch, || Err(StoreError::Unavailable)),
        Err(FencedStoreError::Fence(StoreError::Unavailable))
    ));
    let plan = prepare(&fixture, &request).unwrap();
    let (batch, _, _) = plan.into_parts();
    let guard = super::super::RecoveryGuard::staging([71; 32], [72; 32], [73; 32]).unwrap();
    fixture
        .store
        .apply(guard.prepare_staging().unwrap())
        .unwrap();
    assert_eq!(fixture.store.apply(batch), Err(StoreError::Conflict));
    assert!(prepare(&fixture, &request).is_err());
    assert!(
        inspect_receipt(&fixture.store.snapshot().unwrap(), &request)
            .unwrap()
            .is_none()
    );
    assert_eq!(
        fixture.current().history.status,
        HistoryStatus::ReconciliationRequired
    );
    assert_eq!(
        fixture.current().namespace.status,
        NamespaceStatus::Quiescing
    );
    fixture.require_census();
}

#[test]
fn historical_receipt_survives_restart_later_pause_and_current_read_refusal() {
    let mut fixture = Fixture::new(AggregateMigrationRecipe::Count, true);
    complete(&fixture);
    let original = request(&fixture);
    let receipt = apply(&fixture, prepare(&fixture, &original).unwrap());
    let exact = receipt.encode().unwrap();
    let current = fixture.current().namespace;
    let pause = NamespaceCatalog::new()
        .prepare(
            &fixture.store,
            NamespaceOperationContext {
                tenant: current.tenant.clone(),
                actor: "operator".into(),
                operation_id: "later-pause".into(),
            },
            &NamespaceMutation::Transition {
                id: current.id,
                expected: current.version,
                action: NamespaceTransition::Quiesce,
            },
            0,
        )
        .unwrap();
    fixture.store.apply(pause.batch).unwrap();
    let guard = super::super::RecoveryGuard::staging([81; 32], [82; 32], [83; 32]).unwrap();
    fixture
        .store
        .apply(guard.prepare_staging().unwrap())
        .unwrap();
    fixture.reopen();
    let before = fixture.current();
    assert_eq!(
        inspect_receipt(&fixture.store.snapshot().unwrap(), &original)
            .unwrap()
            .unwrap()
            .encode()
            .unwrap(),
        exact
    );
    assert!(matches!(
        MigrationResumePlan::prepare(
            &fixture.store.snapshot().unwrap(),
            &original,
            &fixture.schema,
            deadline(),
            |_, _, observation| {
                assert!(observation.original_receipt.is_some());
                assert_eq!(
                    observation.current.namespace.status,
                    NamespaceStatus::Quiescing
                );
                Err(StoreError::Unavailable)
            }
        ),
        Err(MigrationError::Review(StoreError::Unavailable))
    ));
    let replay = prepare(&fixture, &original).unwrap();
    assert_eq!(replay.action(), MigrationResumeAction::Replay);
    assert_eq!(apply(&fixture, replay).encode().unwrap(), exact);
    assert_eq!(
        fixture.current().view_token().unwrap(),
        before.view_token().unwrap()
    );
    assert!(crate::recovery::require_ready(&fixture.store.snapshot().unwrap()).is_err());
    let mut refreshed = original.clone();
    refreshed.expected_view = before.view_token().unwrap();
    assert!(matches!(
        inspect_receipt(&fixture.store.snapshot().unwrap(), &refreshed),
        Err(StoreError::Conflict)
    ));
    fixture.require_census();
}

#[test]
fn original_expiry_and_exact_tenant_metadata_high_water_refuse_before_activation() {
    let observed = Fixture::new(AggregateMigrationRecipe::Count, true);
    complete(&observed);
    let view = observed.store.snapshot().unwrap();
    let occupied = crate::tenant::inspect(&view, &observed.quota.as_ref().unwrap().tenant)
        .unwrap()
        .unwrap()
        .usage
        .metadata_rows;
    assert!(occupied > 0 && occupied < observed.quota.as_ref().unwrap().limits.metadata_rows);
    drop(view);
    observed.require_census();
    drop(observed);
    // Quotas are sealed during installation. Seed the exact supported high-water
    // configuration before migration instead of rewriting an installed quota.
    let fixture = Fixture::selected(AggregateMigrationRecipe::Count, true, occupied, None);
    complete(&fixture);
    assert_eq!(
        crate::tenant::inspect(
            &fixture.store.snapshot().unwrap(),
            &fixture.quota.as_ref().unwrap().tenant,
        )
        .unwrap()
        .unwrap()
        .usage
        .metadata_rows,
        occupied
    );
    let request = request(&fixture);
    assert!(matches!(
        MigrationResumePlan::prepare(
            &fixture.store.snapshot().unwrap(),
            &request,
            &fixture.schema,
            Instant::now() - Duration::from_millis(1),
            |_, _, _| Ok(())
        ),
        Err(MigrationError::Deadline)
    ));
    assert!(matches!(
        prepare(&fixture, &request),
        Err(MigrationError::Capacity)
    ));
    assert!(
        inspect_receipt(&fixture.store.snapshot().unwrap(), &request)
            .unwrap()
            .is_none()
    );
    assert_eq!(
        fixture.current().namespace.status,
        NamespaceStatus::Quiescing
    );
    fixture.require_census();
}

#[test]
fn canonical_receipt_requires_original_progress_and_rejects_partial_or_foreign_rows() {
    let fixture = Fixture::new(AggregateMigrationRecipe::Count, true);
    complete(&fixture);
    let request = request(&fixture);
    let receipt = apply(&fixture, prepare(&fixture, &request).unwrap());
    let bytes = receipt.encode().unwrap();
    assert!(bytes.len() <= RECEIPT_BYTES);
    for length in 0..bytes.len() {
        assert!(MigrationResumeReceipt::decode(&bytes[..length]).is_err());
    }
    let mut trailing = bytes.clone();
    trailing.push(0);
    assert!(MigrationResumeReceipt::decode(&trailing).is_err());
    let mut unsupported = bytes.clone();
    unsupported[4] = 2;
    assert!(matches!(
        MigrationResumeReceipt::decode(&unsupported),
        Err(StoreError::UnsupportedFormat)
    ));
    let mut foreign = request.receipt_key().unwrap();
    foreign.key.push(0);
    assert!(MigrationResumeReceipt::validate_row(&foreign, &bytes).is_err());
    fixture
        .store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: request.migration.progress_key().unwrap(),
                value: None,
            }],
        })
        .unwrap();
    assert!(matches!(
        inspect_receipt(&fixture.store.snapshot().unwrap(), &request),
        Err(StoreError::Corrupt)
    ));
}

#[test]
fn activation_never_restores_old_schema_or_pre_migration_view_tokens() {
    let fixture = Fixture::new(AggregateMigrationRecipe::Count, true);
    let old_token = fixture.request.expected_view.clone();
    complete(&fixture);
    let request = request(&fixture);
    let migrated = fixture.cell();
    let receipt = apply(&fixture, prepare(&fixture, &request).unwrap());
    assert_ne!(receipt.view_token().unwrap(), old_token);
    assert_ne!(receipt.view_token().unwrap(), request.expected_view);
    assert!(ViewIdentity::from_token(&request.scope, &old_token).is_err());
    assert_eq!(
        fixture.current().namespace.state_schema,
        request.scope.state_schema
    );
    assert_eq!(fixture.cell(), migrated);
    let current = fixture.current();
    let mut old_schema = request.clone();
    old_schema
        .scope
        .state_schema
        .clone_from(&old_schema.migration.scope.state_schema);
    assert!(prepare(&fixture, &old_schema).is_err());
    assert_eq!(
        fixture.current().view_token().unwrap(),
        current.view_token().unwrap()
    );
    fixture.require_census();
}
