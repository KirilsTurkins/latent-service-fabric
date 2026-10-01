use super::*;
mod fixture;
mod physical;
mod recovery;
use fixture::{context, deadline, Fixture};
use latent_core::PlatformErrorCode;
use latent_rpc::control::v1::state_service_server::StateService;

fn receipt(value: &OwnedPhase4Response) -> &c::NamespaceOperationReceipt {
    let contract::Response::MutateNamespace(value) = &value.response else {
        panic!("wrong response kind")
    };
    value.receipt.as_ref().unwrap()
}
#[tokio::test]
async fn actual_authenticated_namespace_create_inspect_and_original_receipt() {
    let mut fixture = Fixture::new(false).await;
    let adapter = super::super::Phase4ServiceAdapter::with_services(
        Arc::new(fixture.backend.clone()),
        crate::management::ManagementLimits::default(),
        super::super::Phase4Services {
            principals: Arc::new(crate::invocation::LocalPrincipalPolicy),
            management: Arc::new(crate::management::LocalManagementPolicy),
            clock: Arc::new(latent_core::SystemActivationClock),
        },
    )
    .unwrap();
    let created = adapter
        .mutate_namespace(context("alice").request(fixture.mutation(
            "create-original",
            c::NamespaceMutationKind::Create,
            0,
        )))
        .await
        .unwrap();
    assert_eq!(
        created.get_ref().receipt.as_ref().unwrap().after_generation,
        1
    );
    assert!(created
        .get_ref()
        .receipt
        .as_ref()
        .unwrap()
        .authenticated_operator
        .starts_with("administrator:recovery:sha256:"));
    let inspected = adapter
        .inspect_namespace(context("alice").request(fixture.target()))
        .await
        .unwrap();
    let metadata = inspected.get_ref().namespace.as_ref().unwrap();
    assert_eq!(
        (
            metadata.generation,
            metadata.encoded_state_bytes,
            metadata.command_count,
            metadata.pending_effect_count
        ),
        (1, 0, 0, 0)
    );
    assert_eq!(metadata.status, c::NamespaceStatus::Active as i32);
    let recovered = adapter
        .get_state_operation_receipt(
            context("alice").request(c::GetStateOperationReceiptRequest {
                namespace: Some(fixture.target()),
                operation_id: "create-original".into(),
            }),
        )
        .await
        .unwrap();
    assert_eq!(
        recovered.get_ref().namespace_receipt.as_ref(),
        created.get_ref().receipt.as_ref()
    );
    drop(created);
    drop(inspected);
    drop(recovered);
    fixture.finish().await;
}

#[tokio::test]
async fn original_actor_operation_and_generation_survive_replay_without_refresh() {
    let mut fixture = Fixture::new(false).await;
    drop(fixture.create().await);
    let request = fixture.mutation("quiesce-original", c::NamespaceMutationKind::Quiesce, 1);
    let original = fixture
        .backend
        .execute_state(context("alice"), request.clone().into())
        .await
        .unwrap();
    let replay = fixture
        .backend
        .execute_state(context("alice"), request.clone().into())
        .await
        .unwrap();
    assert_eq!(receipt(&original), receipt(&replay));
    assert!(
        matches!(&replay.response,contract::Response::MutateNamespace(value) if value.replayed)
    );
    let mut changed = request;
    changed.expected_generation = Some(2);
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
    let wrong = fixture
        .backend
        .execute_state(
            context("bob"),
            c::GetStateOperationReceiptRequest {
                namespace: Some(fixture.target()),
                operation_id: "quiesce-original".into(),
            }
            .into(),
        )
        .await
        .err()
        .unwrap();
    assert_eq!(wrong.code, PlatformErrorCode::NotFound);
    drop(original);
    drop(replay);
    fixture.finish().await;
}

#[tokio::test]
async fn postcommit_revocation_denies_retained_body_and_fresh_authorization_recovers_original() {
    let mut fixture = Fixture::new(false).await;
    let created = fixture.create().await;
    let original = receipt(&created).clone();
    fixture.update(None, "withdraw-current-access");
    let mut published = false;
    assert!(created
        .owner
        .with_current(&mut || published = true)
        .is_err());
    assert!(!published);
    let request = c::GetStateOperationReceiptRequest {
        namespace: Some(fixture.target()),
        operation_id: "create-original".into(),
    };
    assert_eq!(
        fixture
            .backend
            .execute_state(context("alice"), request.clone().into())
            .await
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::PermissionDenied
    );
    let document = fixture.document.clone();
    fixture.update(Some(&document), "current-new-authorized-read");
    assert!(created
        .owner
        .with_current(&mut || published = true)
        .is_err());
    assert!(!published);
    let recovered = fixture
        .backend
        .execute_state(context("alice"), request.into())
        .await
        .unwrap();
    assert!(
        matches!(&recovered.response,contract::Response::GetStateOperationReceipt(value) if value.namespace_receipt.as_ref()==Some(&original))
    );
    drop(created);
    drop(recovered);
    fixture.finish().await;
}

#[tokio::test]
async fn lifecycle_transition_invalidates_old_metadata_and_tombstone_is_inspectable() {
    let mut fixture = Fixture::new(false).await;
    let old = fixture.create().await;
    let quiesce = fixture
        .backend
        .execute_state(
            context("alice"),
            fixture
                .mutation("quiesce", c::NamespaceMutationKind::Quiesce, 1)
                .into(),
        )
        .await
        .unwrap();
    assert!(old.owner.with_current(&mut || {}).is_err());
    drop(old);
    drop(quiesce);
    let retired = fixture
        .backend
        .execute_state(
            context("alice"),
            fixture
                .mutation("retire", c::NamespaceMutationKind::Retire, 2)
                .into(),
        )
        .await
        .unwrap();
    drop(retired);
    let destroyed = fixture
        .backend
        .execute_state(
            context("alice"),
            fixture
                .mutation("destroy", c::NamespaceMutationKind::Destroy, 3)
                .into(),
        )
        .await
        .unwrap();
    assert_eq!(
        receipt(&destroyed).status,
        c::NamespaceStatus::Tombstone as i32
    );
    let inspected = fixture
        .backend
        .execute_state(context("alice"), fixture.target().into())
        .await
        .unwrap();
    assert!(
        matches!(&inspected.response,contract::Response::InspectNamespace(value) if value.namespace.as_ref().unwrap().generation==4 && value.namespace.as_ref().unwrap().status==c::NamespaceStatus::Tombstone as i32)
    );
    drop(destroyed);
    drop(inspected);
    fixture.finish().await;
}

#[tokio::test]
async fn recovery_response_capacity_is_reserved_before_poll_and_retained_until_body_drops() {
    let mut fixture = Fixture::new(false).await;
    let created = fixture.create().await;
    assert_eq!(fixture.admission.budget.outstanding_reservations(), 1);
    let future = fixture
        .backend
        .execute_state(context("alice"), fixture.target().into());
    assert_eq!(fixture.admission.budget.outstanding_reservations(), 2);
    drop(future);
    assert_eq!(fixture.admission.budget.outstanding_reservations(), 1);
    let occupied = fixture
        .admission
        .budget
        .reserve_host_memory(40 * 1024 * 1024)
        .unwrap();
    assert_eq!(
        fixture
            .backend
            .execute_state(context("alice"), fixture.target().into())
            .await
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(fixture.admission.budget.outstanding_reservations(), 2);
    drop(occupied);
    drop(created);
    fixture.finish().await;
}

#[tokio::test]
async fn wrong_tenant_target_and_expired_arrival_cannot_reserve_or_lookup() {
    let mut fixture = Fixture::new(false).await;
    let mut target = fixture.target();
    target.namespace.as_mut().unwrap().tenant = "other".into();
    target.authorization_publication.as_mut().unwrap().tenant = "other".into();
    assert_eq!(
        fixture
            .backend
            .execute_state(context("alice"), target.into())
            .await
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::PermissionDenied
    );
    let expired_context = context("alice").with_transport_deadline_at(
        1,
        Instant::now().checked_sub(Duration::from_secs(1)).unwrap(),
    );
    assert_eq!(
        fixture
            .backend
            .execute_state(expired_context, fixture.target().into())
            .await
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::DeadlineExceeded
    );
    assert_eq!(
        fixture
            .admission
            .calls
            .load(std::sync::atomic::Ordering::Relaxed),
        0
    );
    fixture.finish().await;
}

#[tokio::test]
async fn exact_selected_service_mismatch_denies_before_native_lookup_even_when_store_closed() {
    let mut fixture = Fixture::new(false).await;
    let entry = fixture
        .backend
        .0
        .services
        .artifacts
        .get_selected_catalog_entry(
            &fixture.backend.0.bindings[0].publication.scope,
            &fixture.backend.0.bindings[0].publication,
        )
        .await
        .unwrap()
        .unwrap();
    assert_eq!(entry.service.0, "a/echo");
    // The real catalog service must match trusted installed configuration. A
    // caller cannot install a target by supplying a matching publication ID.
    let mut bindings = fixture.backend.0.bindings[0].service.0.clone();
    bindings.push_str("-not-installed");
    let inner = Arc::get_mut(&mut fixture.backend.0).unwrap();
    Arc::get_mut(&mut inner.bindings[0]).unwrap().service = ServiceId(bindings);
    fixture.store.close();
    assert_eq!(
        fixture
            .backend
            .execute_state(context("alice"), fixture.target().into())
            .await
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::PermissionDenied
    );
    fixture.finish().await;
}

#[tokio::test]
async fn durable_typed_audit_precedes_mutation_and_closed_audit_cannot_create() {
    let mut fixture = Fixture::new(true).await;
    let created = fixture.create().await;
    assert!(
        matches!(&created.response,contract::Response::MutateNamespace(value) if value.audit_ack.as_ref().unwrap().status==c::AuditAckStatus::Durable as i32 && value.audit_ack.as_ref().unwrap().attempt_sequence.is_some())
    );
    let handle = fixture.audit.as_ref().unwrap().0.clone();
    let page = handle
        .query(
            latent_audit::AuditQueryRequest {
                scope: latent_audit::AuditScope::Tenant(latent_core::TenantId("a".into())),
                filter: latent_audit::AuditFilter::default(),
                limit: 16,
                maximum_bytes: 65536,
                cursor: None,
            },
            deadline(),
        )
        .unwrap()
        .wait()
        .await
        .unwrap();
    assert!(page.records().iter().any(|row|matches!(&row.data,latent_audit::AuditRecordData::Attempt(value) if value.operation_id=="create-original" && value.action==latent_audit::AuditControlAction::NamespaceCreate && value.identities.state.as_ref().unwrap().namespace=="orders")));
    assert!(page.records().iter().any(|row|matches!(&row.data,latent_audit::AuditRecordData::Outcome {conclusion,..} if conclusion.result==latent_audit::AuditOperationResult::Committed && conclusion.receipt_digest.is_some())));
    drop(page);
    drop(created);
    handle.close();
    assert_eq!(
        fixture
            .backend
            .execute_state(
                context("alice"),
                fixture
                    .mutation(
                        "denied-after-audit-close",
                        c::NamespaceMutationKind::Quiesce,
                        1
                    )
                    .into()
            )
            .await
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::Unavailable
    );
    let metadata = fixture
        .store
        .with_store(latent_state::store_io::StoreIoKind::Read, 8192, |engine| {
            Ok(NamespaceCatalog::read_in(
                &engine.snapshot()?,
                &latent_core::TenantId("a".into()),
                &StateNamespaceId("orders".into()),
            )
            .unwrap()
            .unwrap()
            .record()
            .clone())
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    assert_eq!(metadata.version.generation, 1);
    fixture.finish().await;
}
