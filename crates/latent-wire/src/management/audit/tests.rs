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
fn typed_query_requires_an_explicit_scope() {
    assert_eq!(
        validation::typed(
            &proto::QueryPhase2AuditRequest::default(),
            &principal(false),
            &ManagementLimits::default(),
        )
        .unwrap_err()
        .code(),
        tonic::Code::InvalidArgument
    );
}

#[test]
fn audit_resource_class_wire_numbers_remain_stable_and_stream_is_distinct() {
    use latent_audit::AuditCapabilityResourceClass as R;
    use prost::Message;
    for (index, resource) in [
        R::Context,
        R::Clock,
        R::Random,
        R::Log,
        R::Http,
        R::Blob,
        R::Secrets,
        R::Events,
        R::Telemetry,
        R::Service,
        R::State,
        R::Stream,
    ]
    .into_iter()
    .enumerate()
    {
        let wire = proto::AuditCapabilityContext {
            resource_class: enums::capability_resource(resource),
            ..Default::default()
        };
        let decoded =
            proto::AuditCapabilityContext::decode(wire.encode_to_vec().as_slice()).unwrap();
        assert_eq!(decoded.resource_class, i32::try_from(index + 1).unwrap());
    }
    assert_eq!(proto::AuditCapabilityResourceClass::State as i32, 11);
    assert_eq!(proto::AuditCapabilityResourceClass::Stream as i32, 12);
    assert_ne!(
        proto::AuditCapabilityResourceClass::Stream,
        proto::AuditCapabilityResourceClass::State
    );
    assert_ne!(
        proto::AuditCapabilityResourceClass::Stream,
        proto::AuditCapabilityResourceClass::Http
    );
}

#[test]
fn command_cancel_audit_projects_distinct_action_and_preserves_existing_wire_numbers() {
    use latent_audit::AuditControlAction as A;
    use prost::Message;
    for (action, number) in [
        (A::Publish, 1),
        (A::Revoke, 2),
        (A::Retire, 3),
        (A::RenewEvidence, 4),
        (A::DeploymentApply, 5),
        (A::Rollout, 6),
        (A::Promotion, 7),
        (A::Rollback, 8),
        (A::DeploymentDelete, 9),
        (A::CapabilityCall, 10),
        (A::TriggerApply, 11),
        (A::TriggerDelete, 12),
        (A::NamespaceCreate, 13),
        (A::NamespaceQuiesce, 14),
        (A::NamespaceRetire, 15),
        (A::NamespaceDestroy, 16),
        (A::NamespaceRecreate, 17),
        (A::NamespaceInspect, 18),
        (A::DispatcherInspect, 19),
        (A::DispatcherPause, 20),
        (A::DispatcherResume, 21),
        (A::DispatcherOperationRead, 22),
        (A::EffectPlan, 23),
        (A::EffectReconcile, 24),
        (A::EffectRedrive, 25),
        (A::EffectTerminate, 26),
        (A::StateOperationRead, 27),
        (A::StateCheckpoint, 28),
        (A::PayloadPurge, 29),
        (A::CommandFloorRelease, 30),
        (A::CommandCancel, 31),
    ] {
        let wire = proto::Phase2AuditAttempt {
            action: enums::action(action),
            ..Default::default()
        };
        let bytes = wire.encode_to_vec();
        assert_eq!(wire.action, number);
        assert_eq!(
            proto::Phase2AuditAttempt::decode(bytes.as_slice())
                .unwrap()
                .action,
            number
        );
        assert_eq!(
            proto::AuditControlAction::try_from(number).unwrap() as i32,
            number
        );
    }
    assert_eq!(
        proto::AuditControlAction::CommandCancel.as_str_name(),
        "AUDIT_CONTROL_ACTION_COMMAND_CANCEL"
    );
}
