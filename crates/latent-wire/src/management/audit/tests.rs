use super::super::{LocalManagementPolicy, ManagementLimits, ManagementPolicy};
use super::*;
use latent_core::{InvocationPrincipal, Metadata, PrincipalKind, TenantId};

fn principal(operator: bool) -> InvocationPrincipal {
    InvocationPrincipal {
        subject: "alice".into(),
        kind: PrincipalKind::Administrator,
        tenant: Some(TenantId("acme".into())),
        service: None,
        claims: if operator {
            Metadata::from([("latent.node.operator".into(), "true".into())])
        } else {
            Metadata::new()
        },
    }
}
fn query(kind: proto::AuditScopeKind, tenant: Option<&str>) -> proto::QueryPhase2AuditRequest {
    proto::QueryPhase2AuditRequest {
        scope: Some(proto::AuditQueryScope {
            kind: kind as i32,
            tenant: tenant.map(Into::into),
        }),
        filter: None,
        page: None,
    }
}

#[test]
fn audit_authorization_requires_admin_and_existing_operator_claim_for_node_scope() {
    assert!(LocalManagementPolicy
        .authorize(&principal(false), ManagementOperation::AuditTenant)
        .is_ok());
    assert!(LocalManagementPolicy
        .authorize(&principal(false), ManagementOperation::AuditNode)
        .is_err());
    assert!(LocalManagementPolicy
        .authorize(&principal(true), ManagementOperation::AuditNode)
        .is_ok());
    let mut caller = principal(true);
    caller.kind = PrincipalKind::User;
    assert!(LocalManagementPolicy
        .authorize(&caller, ManagementOperation::AuditTenant)
        .is_err());
    assert!(LocalManagementPolicy
        .authorize(&caller, ManagementOperation::AuditNode)
        .is_err());
}

#[test]
fn typed_scopes_cannot_select_foreign_tenant_even_for_an_operator() {
    let limits = ManagementLimits::default();
    for operator in [false, true] {
        let caller = principal(operator);
        assert!(validation::typed(
            &query(proto::AuditScopeKind::Tenant, Some("acme")),
            &caller,
            &limits
        )
        .is_ok());
        assert_eq!(
            validation::typed(
                &query(proto::AuditScopeKind::Tenant, Some("other")),
                &caller,
                &limits
            )
            .unwrap_err()
            .code(),
            tonic::Code::PermissionDenied
        );
    }
    for bad in [
        query(proto::AuditScopeKind::Tenant, None),
        query(proto::AuditScopeKind::Node, Some("acme")),
        query(proto::AuditScopeKind::Unspecified, None),
    ] {
        assert_eq!(
            validation::typed(&bad, &principal(true), &limits)
                .unwrap_err()
                .code(),
            tonic::Code::InvalidArgument
        );
    }
}

#[test]
fn query_bounds_reject_hidden_capacity_unknown_kind_bad_time_and_oversized_cursor() {
    let limits = ManagementLimits::default();
    let mut value = query(proto::AuditScopeKind::Tenant, Some("acme"));
    let mut actor = String::with_capacity(2048);
    actor.push_str("alice");
    value.filter = Some(proto::Phase2AuditFilter {
        actor_subject: Some(actor),
        ..Default::default()
    });
    assert_eq!(
        validation::typed(&value, &principal(false), &limits)
            .unwrap_err()
            .code(),
        tonic::Code::ResourceExhausted
    );
    value.filter = Some(proto::Phase2AuditFilter {
        kind: Some(999),
        ..Default::default()
    });
    assert!(validation::typed(&value, &principal(false), &limits).is_err());
    value.filter = Some(proto::Phase2AuditFilter {
        from_unix_millis: Some(2),
        to_unix_millis: Some(1),
        ..Default::default()
    });
    assert!(validation::typed(&value, &principal(false), &limits).is_err());
    value.filter = None;
    value.page = Some(proto::PageRequest {
        page_size: 1,
        page_token: Some("a".repeat(1025)),
    });
    assert!(validation::typed(&value, &principal(false), &limits).is_err());
}

#[test]
fn legacy_omission_means_authenticated_tenant_and_unsupported_filters_are_explicit() {
    let limits = ManagementLimits::default();
    let mut value = proto::QueryAuditRequest::default();
    assert_eq!(
        validation::legacy(&value, &principal(false), &limits).unwrap(),
        AuditScope::Tenant(TenantId("acme".into()))
    );
    value.tenant = Some("other".into());
    assert_eq!(
        validation::legacy(&value, &principal(true), &limits)
            .unwrap_err()
            .code(),
        tonic::Code::PermissionDenied
    );
    value.tenant = None;
    value.resource_prefix = Some("anything".into());
    assert_eq!(
        validation::legacy(&value, &principal(false), &limits)
            .unwrap_err()
            .code(),
        tonic::Code::InvalidArgument
    );
    assert!(enums::kind_from_name("made-up").is_err());
}
