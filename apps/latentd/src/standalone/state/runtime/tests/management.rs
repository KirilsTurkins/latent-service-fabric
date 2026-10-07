use super::*;
use c::dispatcher_service_server::DispatcherService;
use latent_core::{InvocationPrincipal, Metadata, PrincipalKind};
use latent_wire::invocation::AuthenticatedInvocationContext;
use latent_wire::{management::proto as c, phase4::contract};

fn operator(trusted: bool) -> AuthenticatedInvocationContext {
    AuthenticatedInvocationContext::new(InvocationPrincipal {
        subject: "operator".into(),
        kind: PrincipalKind::Administrator,
        tenant: Some(TenantId("alpha".into())),
        service: None,
        claims: if trusted {
            Metadata::from([("latent.node.operator".into(), "true".into())])
        } else {
            Metadata::new()
        },
    })
}
fn inspect() -> contract::Request {
    c::InspectDispatcherRequest {
        profile: Some(contract::current_profile()),
        scope: c::DispatcherScope::Node as i32,
    }
    .into()
}

#[tokio::test]
async fn installed_empty_state_host_exposes_the_original_audited_dispatcher_and_retains_recovery_owner(
) {
    let fixture = Fixture::new();
    let (audit, mut worker) = latent_audit::DirectoryPhase2AuditJournal::open(
        fixture.root().join("management-audit"),
        latent_audit::AuditLimits::default(),
    )
    .unwrap();
    let (state, mut effects) = StateRuntime::open(
        &fixture.settings,
        Arc::clone(&fixture.artifacts),
        Arc::clone(&fixture.policy),
        fixture.clock.clone(),
        Some(audit.clone()),
        tokio::runtime::Handle::current(),
        None,
    )
    .await
    .unwrap();
    let backend = state.management().expect("installed node management");
    assert!(state.0.installed.is_empty());
    let port = effects.management_port();
    assert!(port.uses_store(&state.0.store));
    assert!(port.uses_native_capacity(&state.0.native));
    assert_eq!(
        backend
            .execute_state(operator(false), inspect())
            .await
            .err()
            .unwrap()
            .code,
        latent_core::PlatformErrorCode::PermissionDenied,
    );
    assert!(state.0.native.snapshot().unwrap().physically_retired());
    let original = port.snapshot().unwrap();
    let adapter = latent_wire::phase4::Phase4ServiceAdapter::with_services(
        Arc::new(backend.clone()),
        latent_wire::management::ManagementLimits::default(),
        latent_wire::phase4::Phase4Services {
            principals: Arc::new(latent_wire::invocation::LocalPrincipalPolicy),
            management: Arc::new(latent_wire::management::LocalManagementPolicy),
            clock: fixture.clock.clone(),
        },
    )
    .unwrap();
    let contract::Request::InspectDispatcher(request) = inspect() else {
        unreachable!("exact fixture request");
    };
    let mut request = tonic::Request::new(*request);
    request.extensions_mut().insert(operator(true));
    let response = adapter.inspect_dispatcher(request).await.unwrap();
    let value = response.get_ref();
    let public = value.dispatcher.as_ref().unwrap();
    assert_eq!(
        public.generation.as_ref().unwrap().owner_epoch,
        original.control.generation.owner_epoch()
    );
    assert_eq!(public.live_workers, original.live_workers as u64);
    assert_eq!(public.paused, original.paused);
    assert_eq!(
        value.audit_ack.as_ref().unwrap().status,
        c::AuditAckStatus::Durable as i32
    );
    assert_eq!(state.0.native.snapshot().unwrap().recovery.slots, 1);
    drop(response);
    assert!(state.0.native.snapshot().unwrap().physically_retired());
    let page = audit
        .query(
            latent_audit::AuditQueryRequest {
                scope: latent_audit::AuditScope::Node,
                filter: latent_audit::AuditFilter::default(),
                limit: 16,
                maximum_bytes: 65536,
                cursor: None,
            },
            Instant::now() + WATCHDOG,
        )
        .unwrap()
        .wait()
        .await
        .unwrap();
    assert!(page.records().iter().any(|record| matches!(
        &record.data,
        latent_audit::AuditRecordData::Attempt(value)
            if value.action == latent_audit::AuditControlAction::DispatcherInspect
    )));
    drop(page);
    drop(adapter);
    drop(backend);
    retained_dispatcher_role(&state).await;
    finish(&state, &mut effects).await;
    audit.close();
    assert!(worker.join_until(Instant::now() + WATCHDOG).unwrap());
}

async fn retained_dispatcher_role(state: &StateRuntime) {
    // The live dispatcher owns one affine store registration until shutdown.
    // Transient completed jobs retire under the original cutoff; the retained
    // registration must remain charged rather than being refunded early.
    tokio::time::timeout_at((Instant::now() + WATCHDOG).into(), async {
        loop {
            let store = state.0.store.snapshot().unwrap();
            if store.accepted == 1
                && store.physical_owners == 1
                && store.active_reads == 0
                && store.active_writes == 0
                && store.recovery_accepted == 0
            {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert_eq!(state.0.store.snapshot().unwrap().physical_owners, 1);
}
