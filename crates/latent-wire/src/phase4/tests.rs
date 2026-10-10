use super::*;
use crate::{invocation::LocalPrincipalPolicy, management::LocalManagementPolicy};
use c::dispatcher_service_server::DispatcherService;
use c::state_service_server::StateService;
use latent_core::{InvocationPrincipal, PrincipalKind, SystemActivationClock, TenantId};
use std::sync::atomic::{AtomicUsize, Ordering};
use t::transaction_service_server::TransactionService;

struct RefusingRuntime(AtomicUsize);
impl Phase4Runtime for RefusingRuntime {
    fn execute(
        &self,
        call: Phase4Call,
    ) -> BoxFuture<'_, Result<OwnedPhase4Response, PlatformError>> {
        self.0.fetch_add(1, Ordering::Relaxed);
        assert!(call.request().is_recovery());
        if call.request().is_node_management() {
            assert_eq!(
                call.context().principal().kind,
                PrincipalKind::Administrator
            );
            assert_eq!(
                call.context()
                    .principal()
                    .claims
                    .get("latent.node.operator")
                    .map(String::as_str),
                Some("true")
            );
        }
        Box::pin(async {
            Err(PlatformError {
                code: PlatformErrorCode::PermissionDenied,
                message: "current data-read grant denied".into(),
                retryable: false,
                details: Vec::new(),
            })
        })
    }
}
fn adapter(runtime: Arc<RefusingRuntime>) -> Phase4ServiceAdapter {
    Phase4ServiceAdapter::with_services(
        runtime,
        ManagementLimits::default(),
        Phase4Services {
            principals: Arc::new(LocalPrincipalPolicy),
            management: Arc::new(LocalManagementPolicy),
            clock: Arc::new(SystemActivationClock),
        },
    )
    .unwrap()
}
fn context(kind: PrincipalKind, tenant: &str) -> AuthenticatedInvocationContext {
    AuthenticatedInvocationContext::new(InvocationPrincipal {
        subject: "actor".into(),
        kind,
        tenant: Some(TenantId(tenant.into())),
        service: None,
        claims: latent_core::Metadata::new(),
    })
}
fn namespace() -> t::NamespaceSelector {
    t::NamespaceSelector {
        tenant: "tenant".into(),
        namespace: "app".into(),
        incarnation: "1".into(),
    }
}
fn publication() -> c::PublicationRef {
    c::PublicationRef {
        tenant: "tenant".into(),
        id: format!("publication:sha256:{}", "a".repeat(64)),
    }
}
fn lookup() -> t::LookupCommandRequest {
    t::LookupCommandRequest {
        profile: Some(contract::current_profile()),
        command: Some(t::CommandSelector {
            namespace: Some(namespace()),
            operation: "save".into(),
            client_key: "original".into(),
            ..Default::default()
        }),
        authorization_publication: Some(publication()),
        ..Default::default()
    }
}
fn inspect() -> c::InspectNamespaceRequest {
    c::InspectNamespaceRequest {
        profile: Some(contract::current_profile()),
        namespace: Some(namespace()),
        authorization_publication: Some(publication()),
    }
}

#[tokio::test]
async fn missing_identity_and_wrong_tenant_cannot_touch_recovery_runtime() {
    let runtime = Arc::new(RefusingRuntime(AtomicUsize::new(0)));
    let adapter = adapter(runtime.clone());
    let missing = adapter
        .lookup_command(Request::new(lookup()))
        .await
        .unwrap_err();
    assert_eq!(missing.code(), tonic::Code::Unauthenticated);
    let wrong = adapter
        .lookup_command(context(PrincipalKind::User, "other").request(lookup()))
        .await
        .unwrap_err();
    assert_eq!(wrong.code(), tonic::Code::PermissionDenied);
    assert_eq!(runtime.0.load(Ordering::Relaxed), 0);
}
#[tokio::test]
async fn ordinary_authenticated_user_uses_current_result_authority_without_admin_elevation() {
    let runtime = Arc::new(RefusingRuntime(AtomicUsize::new(0)));
    let adapter = adapter(runtime.clone());
    let denied = adapter
        .lookup_command(context(PrincipalKind::User, "tenant").request(lookup()))
        .await
        .unwrap_err();
    assert_eq!(denied.code(), tonic::Code::PermissionDenied);
    assert_eq!(runtime.0.load(Ordering::Relaxed), 1);
    assert!(!denied.message().contains("grant"));
}
#[tokio::test]
async fn namespace_operations_require_management_role_before_domain_owner() {
    let runtime = Arc::new(RefusingRuntime(AtomicUsize::new(0)));
    let adapter = adapter(runtime.clone());
    let denied = adapter
        .inspect_namespace(context(PrincipalKind::User, "tenant").request(inspect()))
        .await
        .unwrap_err();
    assert_eq!(denied.code(), tonic::Code::PermissionDenied);
    assert_eq!(runtime.0.load(Ordering::Relaxed), 0);
    assert!(adapter
        .inspect_namespace(context(PrincipalKind::Administrator, "tenant").request(inspect()))
        .await
        .is_err());
    assert_eq!(runtime.0.load(Ordering::Relaxed), 1);
}
#[tokio::test]
async fn malformed_profile_and_stale_transport_deadline_never_admit_work() {
    let runtime = Arc::new(RefusingRuntime(AtomicUsize::new(0)));
    let adapter = adapter(runtime.clone());
    let mut request = lookup();
    request.profile.as_mut().unwrap().profile = "unknown".into();
    assert_eq!(
        adapter
            .lookup_command(context(PrincipalKind::User, "tenant").request(request))
            .await
            .unwrap_err()
            .code(),
        tonic::Code::FailedPrecondition
    );
    let context = context(PrincipalKind::User, "tenant")
        .with_transport_deadline_at(1, std::time::Instant::now());
    assert_eq!(
        adapter
            .lookup_command(context.request(lookup()))
            .await
            .unwrap_err()
            .code(),
        tonic::Code::DeadlineExceeded
    );
    assert_eq!(runtime.0.load(Ordering::Relaxed), 0);
}

async fn dispatcher_status(
    adapter: &Phase4ServiceAdapter,
    context: Option<&AuthenticatedInvocationContext>,
    route: u8,
) -> Status {
    fn request<T>(context: Option<&AuthenticatedInvocationContext>, value: T) -> Request<T> {
        let mut request = match context {
            Some(context) => context.request(value),
            None => Request::new(value),
        };
        // Caller metadata cannot create or replace the listener's trusted claim.
        request
            .metadata_mut()
            .insert("latent.node.operator", "true".parse().unwrap());
        request
    }
    let control = c::ControlDispatcherRequest {
        profile: Some(contract::current_profile()),
        scope: c::DispatcherScope::Node as i32,
        operation_id: "original-pause".into(),
        action: c::DispatcherAction::Pause as i32,
        expected_generation: Some(c::DispatcherGeneration {
            owner_epoch: 7,
            revision: 1,
        }),
    };
    match route {
        0 => adapter
            .inspect_dispatcher(request(
                context,
                c::InspectDispatcherRequest {
                    profile: Some(contract::current_profile()),
                    scope: c::DispatcherScope::Node as i32,
                },
            ))
            .await
            .unwrap_err(),
        1 => adapter
            .control_dispatcher(request(context, control))
            .await
            .unwrap_err(),
        2 => adapter
            .get_dispatcher_operation(request(
                context,
                c::GetDispatcherOperationRequest {
                    original: Some(control),
                },
            ))
            .await
            .unwrap_err(),
        _ => panic!("unknown test route"),
    }
}

#[tokio::test]
async fn dispatcher_calls_require_trusted_node_operator_and_administrator_before_runtime() {
    let runtime = Arc::new(RefusingRuntime(AtomicUsize::new(0)));
    let adapter = adapter(runtime.clone());
    for route in 0..3 {
        assert_eq!(
            dispatcher_status(&adapter, None, route).await.code(),
            tonic::Code::Unauthenticated
        );
    }
    for (kind, claim) in [
        (PrincipalKind::Administrator, None),
        (PrincipalKind::Administrator, Some("false")),
        (PrincipalKind::Administrator, Some("True")),
        (PrincipalKind::User, Some("true")),
        (PrincipalKind::Node, Some("true")),
    ] {
        let mut principal = context(kind, "tenant").principal().clone();
        if let Some(claim) = claim {
            principal
                .claims
                .insert("latent.node.operator".into(), claim.into());
        }
        let context = AuthenticatedInvocationContext::new(principal);
        for route in 0..3 {
            assert_eq!(
                dispatcher_status(&adapter, Some(&context), route)
                    .await
                    .code(),
                tonic::Code::PermissionDenied
            );
        }
    }
    assert_eq!(runtime.0.load(Ordering::Relaxed), 0);
    let mut principal = context(PrincipalKind::Administrator, "tenant")
        .principal()
        .clone();
    principal
        .claims
        .insert("latent.node.operator".into(), "true".into());
    let context = AuthenticatedInvocationContext::new(principal);
    for route in 0..3 {
        assert_eq!(
            dispatcher_status(&adapter, Some(&context), route)
                .await
                .code(),
            tonic::Code::PermissionDenied
        );
        assert_eq!(runtime.0.load(Ordering::Relaxed), usize::from(route) + 1);
    }
}
