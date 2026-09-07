use std::sync::atomic::Ordering;

use latent_core::{PrincipalKind, TenantId};
use latent_wire::invocation::{proto, AuthenticatedInvocationContext, InvocationService};
use tonic::Code;

use super::model;
use super::support::{authenticated, finish, request, scoped, Harness};

#[tokio::test]
async fn malformed_optional_identity_is_not_coerced_into_server_assignment() {
    let harness = Harness::standard();
    let adapter = harness.adapter();
    for (activation, root, parent) in [
        (Some(""), None, None),
        (None, Some(""), None),
        (None, Some("root"), Some("")),
        (None, None, Some("parent")),
        (Some("space id"), None, None),
    ] {
        let mut input = request("unused");
        input.activation_id = activation.map(str::to_owned);
        input.root_activation_id = root.map(str::to_owned);
        input.parent_activation_id = parent.map(str::to_owned);
        let error = finish(adapter.invoke(authenticated(input)))
            .await
            .expect_err("invalid identity");
        assert_eq!(error.code(), Code::InvalidArgument);
    }
    assert_eq!(harness.ids.0.load(Ordering::Relaxed), 0);
    assert_eq!(harness.manager.journal().snapshot().begun, 0);
    assert_eq!(harness.artifacts.entered.load(Ordering::Relaxed), 0);
    assert!(harness.catalog.keys.lock().expect("keys").is_empty());
    harness.assert_idle();
}

#[tokio::test]
async fn trusted_principal_is_required_and_administrators_keep_exact_tenant_scope() {
    let harness = Harness::standard();
    let adapter = harness.adapter();
    assert_eq!(
        finish(adapter.invoke(tonic::Request::new(request("anonymous"))))
            .await
            .expect_err("missing extension")
            .code(),
        Code::Unauthenticated,
    );
    for administrator in [false, true] {
        assert_eq!(
            finish(adapter.invoke(scoped(request("foreign"), "tenant-b", administrator)))
                .await
                .expect_err("scope denied")
                .code(),
            Code::PermissionDenied,
        );
    }
    for kind in [PrincipalKind::Anonymous, PrincipalKind::Service] {
        let mut principal = model::request("context").principal;
        principal.kind = kind;
        let result = finish(adapter.invoke(
            AuthenticatedInvocationContext::new(principal).request(request("invalid-principal")),
        ))
        .await;
        assert!(
            result.is_err(),
            "anonymous or service without service identity must fail"
        );
    }
    let mut unscoped = model::request("context").principal;
    unscoped.tenant = None;
    assert!(finish(
        adapter.get_activation(AuthenticatedInvocationContext::new(unscoped).request(
            proto::GetActivationRequest {
                activation_id: "unknown".to_owned(),
            }
        ),)
    )
    .await
    .is_err());
    assert_eq!(harness.manager.journal().snapshot().begun, 0);
    assert_eq!(harness.backend.entered.load(Ordering::Relaxed), 0);
    finish(adapter.invoke(scoped(request("administrator"), model::TENANT, true)))
        .await
        .expect("same-tenant administrator accepted");
    harness.assert_idle();
}

#[tokio::test]
async fn manager_assigns_identity_and_preserves_opaque_lineage_and_uninterpreted_payload() {
    let harness = Harness::standard();
    let adapter = harness.adapter();
    let mut absent = request("unused");
    absent.activation_id = None;
    absent.payload = b"loop-forever panic trap cancel deadline".to_vec();
    let payload = absent.payload.clone();
    let response = finish(adapter.invoke(authenticated(absent)))
        .await
        .expect("assigned")
        .into_inner();
    assert_eq!(response.activation_id, "generated-1");
    let Some(proto::invoke_response::Result::Success(success)) = response.result else {
        panic!("control-looking bytes are application data");
    };
    assert_eq!(success.payload, payload);
    for (id, parent) in [("child", Some("unknown-parent")), ("root-only", None)] {
        let mut input = request(id);
        input.root_activation_id = Some("unknown-root".to_owned());
        input.parent_activation_id = parent.map(str::to_owned);
        input
            .metadata
            .insert("trace_id".to_owned(), "guest-spoof".to_owned());
        input
            .metadata
            .insert("retry_attempt".to_owned(), "99".to_owned());
        finish(adapter.invoke(authenticated(input)))
            .await
            .expect("opaque lineage");
    }
    let observed = harness.backend.requests.lock().expect("requests");
    let first = &observed[0].activation;
    assert_eq!(first.root_activation_id, first.activation_id);
    assert_eq!(first.parent_activation_id, None);
    for (index, request) in observed.iter().enumerate() {
        let activation = &request.activation;
        assert_eq!(activation.retry_attempt, 0);
        assert_eq!(
            activation.principal.tenant,
            Some(TenantId(model::TENANT.to_owned()))
        );
        assert!(!activation.trace.trace_id.0.is_empty());
        assert!(!activation.trace.span_id.0.is_empty());
        assert!(activation.trace.baggage.is_empty());
        assert_ne!(activation.trace.trace_id.0, "guest-spoof");
        if index > 0 {
            assert_eq!(activation.root_activation_id.0, "unknown-root");
            assert_ne!(activation.trace.trace_id, first.trace.trace_id);
            assert_ne!(activation.trace.span_id, first.trace.span_id);
            assert_eq!(activation.metadata["retry_attempt"], "99");
        }
    }
    assert_eq!(
        observed[1]
            .activation
            .parent_activation_id
            .as_ref()
            .expect("parent")
            .0,
        "unknown-parent"
    );
    assert_eq!(observed[2].activation.parent_activation_id, None);
    drop(observed);
    assert_eq!(harness.ids.0.load(Ordering::Relaxed), 1);
    harness.assert_idle();
}

#[tokio::test]
async fn forged_auth_metadata_and_later_phase_budgets_fail_before_acceptance() {
    let harness = Harness::standard();
    let adapter = harness.adapter();
    for key in ["latent.auth.subject", "LATENT.PRINCIPAL.tenant"] {
        let mut input = request("forged");
        input
            .metadata
            .insert(key.to_owned(), "administrator".to_owned());
        assert!(finish(adapter.invoke(authenticated(input))).await.is_err());
    }
    let mut input = request("later-phase");
    input.budget.as_mut().expect("budget").child_calls = 1;
    assert_eq!(
        finish(adapter.invoke(authenticated(input)))
            .await
            .expect_err("Phase 1 ceiling")
            .code(),
        Code::InvalidArgument
    );
    assert_eq!(harness.manager.journal().snapshot().begun, 0);
    harness.assert_idle();
}
