use super::*;
use latent_commit::atomic::{
    command_row_key, AdmissionDecision, AdmissionInput, CommandTime, CompleteEnvelope, Identity,
    MaintenanceClock, PreparedAdmission, PreparedDisposition, ReplayPolicy, ResultPolicy,
    RetentionRequest, RetiredCommand, SourceIdentity,
};
use latent_core::transaction_contract::{CommandFingerprint, CommandKey, Value};
use latent_state::{embedded::StoreError, store_io::StoreIoKind};

fn observation(now: u64, elapsed: u64) -> MaintenanceClock {
    MaintenanceClock {
        time: CommandTime {
            unix_millis: now,
            continuity_proven: true,
        },
        boot: [7; 32],
        monotonic_millis: elapsed,
    }
}
struct TestMaintenanceClock;
impl StateMaintenanceClock for TestMaintenanceClock {
    fn sample(&self) -> Result<MaintenanceClock, PlatformError> {
        Ok(observation(2304, 204))
    }
}
fn value(bytes: &[u8]) -> Value {
    Value {
        bytes: bytes.to_vec(),
        media_type: "application/octet-stream".into(),
        metadata: vec![],
    }
}

async fn seed_floor(fixture: &mut Fixture) -> Identity {
    drop(fixture.create().await);
    Arc::get_mut(&mut fixture.backend.0)
        .unwrap()
        .services
        .maintenance_clock = Arc::new(TestMaintenanceClock);
    let maintenance = Arc::clone(&fixture.backend.0.services.maintenance);
    let binding = Arc::clone(&fixture.backend.0.bindings[0]);
    let caller = latent_capabilities::namespace::CallerScope::derive(
        context("alice").principal(),
        &latent_capabilities::namespace::RecoverySelection::OriginalCaller,
    )
    .unwrap();
    fixture
        .store
        .with_store(
            StoreIoKind::RecoveryWrite,
            WORK_BYTES as u64,
            move |engine| {
                // This lower fixture grant seeds a genuine durable rejection. The
                // public floor mutation below uses the real PolicyStore separately.
                let view = engine.snapshot()?;
                let input = AdmissionInput {
                    key: CommandKey {
                        tenant: "a".into(),
                        namespace: "orders".into(),
                        incarnation: "1".into(),
                        recovery_scope: caller.scope,
                        operation: "fixture-rejection".into(),
                        entity: None,
                        client_key: "original-business-key".into(),
                    },
                    fingerprint: CommandFingerprint {
                        input_format: "lsf-wit-values-v1".into(),
                        input: value(b"original input"),
                        expected_versions: vec![],
                    },
                    source: SourceIdentity {
                        publication: binding.publication.id.as_str().into(),
                        revision: "original-fixture-revision".into(),
                        release_digest: binding.component.0.clone(),
                        component_digest: binding.component.0.clone(),
                        contract_digest: fixture::schema(),
                        route_generation: 1,
                        state_schema: binding.state_schema.clone(),
                        input_format: "lsf-wit-values-v1".into(),
                        result_format: "lsf-wit-values-v1".into(),
                    },
                    result_read_policy: binding.result_policy.clone(),
                    result_policy: ResultPolicy {
                        replay: ReplayPolicy::Full,
                        maximum_result_bytes: 1024,
                        result_millis: 1000,
                        identity_millis: 2000,
                        maximum_attempts: 1,
                    },
                    inbox: None,
                    owner_epoch: 1,
                };
                let AdmissionDecision::New(prepared) =
                    PreparedAdmission::prepare(&view, input, observation(100, 0).time, |_, _| {
                        Ok(())
                    })
                    .unwrap()
                else {
                    panic!("fresh native business identity required")
                };
                drop(view);
                let admitted = prepared.publish(engine, || Ok(())).unwrap();
                let view = engine.snapshot()?;
                let envelope = CompleteEnvelope::rejection(
                    &view,
                    admitted,
                    "fixture-decision".into(),
                    value(b"original rejection"),
                    observation(101, 1).time,
                )
                .unwrap();
                drop(view);
                let PreparedDisposition::Confirmed { command, .. } =
                    envelope.publish(engine, |effects| {
                        assert!(effects.is_empty());
                        Ok(())
                    })
                else {
                    panic!("native rejection must durably confirm")
                };
                maintenance
                    .anchor_review(
                        engine,
                        command.key(),
                        None,
                        observation(2100, 0),
                        |_| Ok(()),
                    )
                    .unwrap();
                let request = RetentionRequest {
                    key: command.key().clone(),
                    expected_command_digest: RetentionRequest::command_digest(&command).unwrap(),
                    actor: "operator:fixture-retention".into(),
                    operation_id: "original-retention-review".into(),
                    policy: "fixture/destructive-review-v1".into(),
                    retain_until_millis: 2300,
                    inbox_expires_at_millis: None,
                };
                assert!(
                    maintenance
                        .terminalize(engine, &request, observation(2200, 100), |_, _, _| Ok(()))
                        .unwrap()
                        .complete
                );
                let mut complete = false;
                for step in 0..3 {
                    complete = maintenance
                        .purge(
                            engine,
                            &request,
                            observation(2300 + step, 200 + step),
                            |_, _, _| Ok(()),
                        )
                        .unwrap()
                        .complete;
                    if complete {
                        break;
                    }
                }
                assert!(
                    complete,
                    "one original attempt has bounded purge completion"
                );
                let bytes = engine
                    .snapshot()?
                    .get(&command_row_key(command.id()))?
                    .unwrap();
                let floor = RetiredCommand::decode(&bytes).unwrap();
                assert_eq!(floor.id(), command.id());
                Ok(floor.id())
            },
        )
        .unwrap()
        .await
        .unwrap()
        .unwrap()
}

async fn inspect(fixture: &Fixture) -> c::NamespaceInspection {
    let response = fixture
        .backend
        .execute_state(context("alice"), fixture.target().into())
        .await
        .unwrap();
    let contract::Response::InspectNamespace(public) = &response.response else {
        panic!("expected actual namespace inspection")
    };
    public.namespace.as_ref().unwrap().clone()
}
async fn retire(fixture: &Fixture) {
    for (operation, kind) in [
        ("floor-quiesce", c::NamespaceMutationKind::Quiesce),
        ("floor-retire", c::NamespaceMutationKind::Retire),
    ] {
        let generation = inspect(fixture).await.generation;
        drop(
            fixture
                .backend
                .execute_state(
                    context("alice"),
                    fixture.mutation(operation, kind, generation).into(),
                )
                .await
                .unwrap(),
        );
    }
}
fn request(
    fixture: &Fixture,
    floor: Identity,
    namespace: &c::NamespaceInspection,
) -> c::MutateStateRequest {
    c::MutateStateRequest {
        namespace: Some(fixture.target()),
        operation_id: "floor-release-original".into(),
        mutation: c::StateMutationKind::ReleaseExpiredCommandFloor as i32,
        record_id: Some(floor.hex()),
        expected_version: namespace.view.as_ref().unwrap().version.clone(),
        expected_policy_digest: namespace.policy_digest.clone().unwrap(),
        reason: "approved fixture retention cleanup".into(),
    }
}
fn outcome(response: &OwnedPhase4Response) -> &c::StateOperationReceipt {
    let contract::Response::MutateState(response) = &response.response else {
        panic!("expected actual state mutation receipt")
    };
    assert_eq!(
        response.audit_ack.as_ref().unwrap().status,
        c::AuditAckStatus::Durable as i32
    );
    response.receipt.as_ref().unwrap()
}
async fn get(fixture: &Fixture, caller: &str) -> Result<OwnedPhase4Response, PlatformError> {
    fixture
        .backend
        .execute_state(
            context(caller),
            c::GetStateOperationReceiptRequest {
                namespace: Some(fixture.target()),
                operation_id: "floor-release-original".into(),
            }
            .into(),
        )
        .await
}
fn recovered(response: &OwnedPhase4Response) -> &c::StateOperationReceipt {
    let contract::Response::GetStateOperationReceipt(response) = &response.response else {
        panic!("expected original state operation")
    };
    response.receipt.as_ref().unwrap()
}
fn linked_row(
    view: &latent_state::embedded::ReadView,
    key: &latent_state::embedded::RowKey,
    bytes: &[u8],
) -> Result<(), StoreError> {
    match StateManagementBackend::tenant_metadata_contribution(view, key, bytes) {
        Ok(latent_state::tenant::TenantCensusContribution::Usage { tenant, usage }) => {
            assert_eq!(tenant.0, "a");
            assert_eq!(
                usage,
                latent_state::tenant::TenantUsage {
                    metadata_rows: 1,
                    metadata_bytes: latent_state::tenant::row_charge(key, bytes).unwrap(),
                    ..latent_state::tenant::TenantUsage::default()
                }
            );
            return Ok(());
        }
        Ok(_) => panic!("management receipt must retain its original tenant charge"),
        Err(StoreError::UnsupportedFormat) => {}
        Err(error) => return Err(error),
    }
    for result in [
        latent_state::session::validate_row(view, key, bytes),
        StateManagementBackend::validate_operation_row(view, key, bytes),
        latent_state::recovery::resume::NamespaceResumeReceipt::validate_row(key, bytes),
        latent_state::recovery::migration::AggregateMigrationProgress::validate_row(key, bytes),
        NamespaceCatalog::validate_row(key, bytes)
            .map_err(super::super::inspection::native_namespace),
        latent_state::recovery::RecoveryGuard::validate_row(key, bytes),
        latent_effects::dispatch_store::validate_row(key, bytes),
    ] {
        if result != Err(StoreError::UnsupportedFormat) {
            return result;
        }
    }
    Err(StoreError::UnsupportedFormat)
}

#[tokio::test]
async fn actual_audited_floor_release_preserves_original_receipt_and_reopens_linked_native_rows() {
    let mut fixture = Fixture::new(true).await;
    let floor = seed_floor(&mut fixture).await;
    let before = inspect(&fixture).await;
    assert_eq!(before.command_count, 1);
    assert!(before.retained_formats.is_empty());
    retire(&fixture).await;
    let request = request(&fixture, floor, &inspect(&fixture).await);
    let original = fixture
        .backend
        .execute_state(context("alice"), request.clone().into())
        .await
        .unwrap();
    let receipt = outcome(&original).clone();
    assert_eq!(receipt.record_id, Some(floor.hex()));
    assert_eq!(receipt.completed_at_unix_millis, 2304);
    drop(original);
    let replay = fixture
        .backend
        .execute_state(context("alice"), request.clone().into())
        .await
        .unwrap();
    assert_eq!(outcome(&replay), &receipt);
    drop(replay);
    let mut changed = request;
    changed.reason = "different review".into();
    assert_eq!(
        fixture
            .backend
            .execute_state(context("alice"), changed.into())
            .await
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::StateConflict
    );
    assert_eq!(
        get(&fixture, "bob").await.err().unwrap().code,
        PlatformErrorCode::NotFound
    );
    let after = inspect(&fixture).await;
    assert_eq!(after.command_count, 0);
    fixture.store.close();
    assert!(
        fixture
            .store
            .drain_async(deadline(), std::future::pending())
            .unwrap()
            .await
            .clean
    );
    let reopened = Arc::new(
        ProtectedStoreOwner::start_validated_view(fixture.config.clone(), 0, |view| {
            latent_commit::atomic::validate_view(view, linked_row)?;
            latent_effects::dispatch_store::DispatchCatalog::validate_view(view)
        })
        .unwrap()
        .await
        .unwrap(),
    );
    Arc::get_mut(&mut fixture.backend.0).unwrap().services.store = Arc::clone(&reopened);
    fixture.store = reopened;
    let recovered_response = get(&fixture, "alice").await.unwrap();
    assert_eq!(recovered(&recovered_response), &receipt);
    drop(recovered_response);
    fixture.finish().await;
}

#[tokio::test]
async fn floor_operation_retained_response_and_recovery_require_current_permission_without_refresh()
{
    let mut fixture = Fixture::new(true).await;
    let floor = seed_floor(&mut fixture).await;
    retire(&fixture).await;
    let request = request(&fixture, floor, &inspect(&fixture).await);
    let original = fixture
        .backend
        .execute_state(context("alice"), request.into())
        .await
        .unwrap();
    let receipt = outcome(&original).clone();
    fixture.update(None, "withdraw-floor-inspection");
    let mut published = false;
    assert!(original
        .owner
        .with_current(&mut || published = true)
        .is_err());
    assert!(!published);
    assert_eq!(
        get(&fixture, "alice").await.err().unwrap().code,
        PlatformErrorCode::PermissionDenied
    );
    let document = fixture.document.clone();
    fixture.update(Some(&document), "rebind-current-floor-inspection");
    assert!(original
        .owner
        .with_current(&mut || published = true)
        .is_err());
    let current = get(&fixture, "alice").await.unwrap();
    assert_eq!(recovered(&current), &receipt);
    drop(original);
    drop(current);
    fixture.finish().await;
}

#[tokio::test]
async fn floor_release_refuses_live_physical_reader_and_stale_native_view_or_policy() {
    let mut fixture = Fixture::new(true).await;
    let floor = seed_floor(&mut fixture).await;
    retire(&fixture).await;
    let original = request(&fixture, floor, &inspect(&fixture).await);
    let physical = fixture
        .store
        .with_store(StoreIoKind::RecoveryRead, 65536, |engine| engine.snapshot())
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        fixture
            .backend
            .execute_state(context("alice"), original.clone().into())
            .await
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    assert!(physical.get(&command_row_key(floor)).unwrap().is_some());
    drop(physical);
    let mut stale = original.clone();
    stale.expected_version[43..51].copy_from_slice(&1_u64.to_le_bytes());
    assert_eq!(
        fixture
            .backend
            .execute_state(context("alice"), stale.into())
            .await
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::StateConflict
    );
    let mut changed_policy = original.clone();
    changed_policy.expected_policy_digest = format!("sha256:{}", "f".repeat(64));
    assert_eq!(
        fixture
            .backend
            .execute_state(context("alice"), changed_policy.into())
            .await
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::StateConflict
    );
    let committed = fixture
        .backend
        .execute_state(context("alice"), original.into())
        .await
        .unwrap();
    assert_eq!(outcome(&committed).record_id, Some(floor.hex()));
    drop(committed);
    fixture.finish().await;
}

#[tokio::test]
async fn another_namespace_current_permission_cannot_disclose_original_floor_operation() {
    let mut fixture = Fixture::new(true).await;
    let floor = seed_floor(&mut fixture).await;
    retire(&fixture).await;
    let original = request(&fixture, floor, &inspect(&fixture).await);
    drop(
        fixture
            .backend
            .execute_state(context("alice"), original.into())
            .await
            .unwrap(),
    );

    // A second installed fixture constraint uses the same actual artifact and
    // real policy owner. Its namespace permission is deliberately independent.
    let first = &fixture.backend.0.bindings[0];
    let mut binding = fixture::binding(first.publication.clone(), first.component.clone());
    binding.namespace = latent_core::StateNamespaceId("other-orders".into());
    super::super::authorization::validate_binding(&binding).unwrap();
    Arc::get_mut(&mut fixture.backend.0)
        .unwrap()
        .bindings
        .push(Arc::new(binding));
    let mut document = fixture.document.clone();
    for rule in document["rules"].as_array_mut().unwrap() {
        let scopes = rule["resources"]["scopes"].as_array_mut().unwrap();
        let mut other = scopes[0].clone();
        other["namespace"] = "other-orders".into();
        scopes.push(other);
    }
    fixture.update(Some(&document), "authorize-second-namespace");
    let mut other = fixture.target();
    other.namespace.as_mut().unwrap().namespace = "other-orders".into();
    let mut create = fixture.mutation(
        "create-second-namespace",
        c::NamespaceMutationKind::Create,
        0,
    );
    create.namespace = Some(other.clone());
    drop(
        fixture
            .backend
            .execute_state(context("alice"), create.into())
            .await
            .unwrap(),
    );
    assert_eq!(
        fixture
            .backend
            .execute_state(
                context("alice"),
                c::GetStateOperationReceiptRequest {
                    namespace: Some(other),
                    operation_id: "floor-release-original".into(),
                }
                .into()
            )
            .await
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::NotFound
    );
    let original = get(&fixture, "alice").await.unwrap();
    assert_eq!(recovered(&original).record_id, Some(floor.hex()));
    drop(original);
    fixture.finish().await;
}
