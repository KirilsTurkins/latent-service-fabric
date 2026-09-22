use super::*;
use latent_core::{InvocationPrincipal, PrincipalKind, TenantId};

fn principal() -> InvocationPrincipal {
    InvocationPrincipal {
        subject: "tenant-admin".into(),
        kind: PrincipalKind::Administrator,
        service: None,
        tenant: Some(TenantId("alice".into())),
        claims: latent_core::Metadata::new(),
    }
}
fn request() -> proto::ApplyTriggerRequest {
    proto::ApplyTriggerRequest {
        trigger: Some(proto::Trigger {
            id: "browser".into(),
            kind: "HttpTrigger".into(),
            generation: 999,
            metadata: Some(proto::ObjectMetadata {
                name: "browser".into(),
                tenant: Some("alice".into()),
                ..Default::default()
            }),
            target: Some(proto::TriggerTarget {
                service: "echo".into(),
                contract: "latent:web/application@0.1.0".into(),
                function: "handle".into(),
                route: Some("web".into()),
                publication: Some(proto::PublicationRef {
                    id: format!("publication:sha256:{}", "a".repeat(64)),
                    tenant: "alice".into(),
                }),
                revision: Some(format!("revision-v1:sha256:{}", "b".repeat(64))),
                deployment_generation: Some(1),
                kind: proto::TriggerTargetKind::Application as i32,
            }),
            configuration: [
                ("profile", "buffered-v1"),
                ("scheme", "https"),
                ("host", "alice.example.test"),
                ("path", "/"),
                ("pathMatch", "prefix"),
                ("method", "GET"),
            ]
            .into_iter()
            .map(|(k, v)| (k.into(), v.into()))
            .collect(),
        }),
        expected_generation: Some(0),
        operation: Some(proto::TriggerOperationPrecondition {
            operation_id: "create".into(),
            expected_state_version: Some(1),
        }),
    }
}
#[test]
fn trigger_wire_derives_actor_and_preserves_explicit_cas_and_publication() {
    let result = validation::apply(
        request(),
        principal(),
        &super::super::ManagementLimits::default(),
    )
    .unwrap();
    assert_eq!(result.context().actor.subject, "tenant-admin");
    assert_eq!(result.expected_generation(), 0);
    let TriggerOperationRequest::Apply { manifest, .. } = result else {
        panic!("apply")
    };
    assert_eq!(manifest.target.deployment_generation, Some(1));
    assert!(manifest.target.publication.is_some());
    let limits = super::super::ManagementLimits::default();
    let mut missing = request();
    missing.operation.as_mut().unwrap().expected_state_version = None;
    assert!(validation::apply(missing, principal(), &limits).is_err());
    let mut foreign = request();
    foreign
        .trigger
        .as_mut()
        .unwrap()
        .target
        .as_mut()
        .unwrap()
        .publication
        .as_mut()
        .unwrap()
        .tenant = "bob".into();
    assert!(validation::apply(foreign, principal(), &limits).is_err());
    let mut principal = principal();
    principal.tenant = Some(TenantId("bob".into()));
    assert_eq!(
        validation::apply(request(), principal, &limits)
            .unwrap_err()
            .code(),
        tonic::Code::PermissionDenied
    );
}
#[test]
fn trigger_native_wire_sparse_maps_and_reserved_strings_deny_before_conversion() {
    let mut huge = request();
    let config = &mut huge.trigger.as_mut().unwrap().configuration;
    config.reserve(100_000);
    assert_eq!(
        validation::apply(
            huge,
            principal(),
            &super::super::ManagementLimits::default()
        )
        .unwrap_err()
        .code(),
        tonic::Code::ResourceExhausted
    );
    let mut huge = request();
    huge.trigger.as_mut().unwrap().id.reserve(1_000_000);
    assert!(validation::apply(
        huge,
        principal(),
        &super::super::ManagementLimits::default()
    )
    .is_err());
}
