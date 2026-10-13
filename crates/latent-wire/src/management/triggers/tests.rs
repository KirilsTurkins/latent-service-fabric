use super::*;
use latent_core::{InvocationPrincipal, PrincipalKind, TenantId};

fn captured_transaction_request() -> proto::ApplyTriggerRequest {
    use latent_manifest::{JsonManifestCodec, ManifestCodec};
    let manifest = JsonManifestCodec::default()
        .decode_trigger(include_bytes!(
            "tests/fixtures/phase4-transaction-trigger.json"
        ))
        .unwrap();
    proto::ApplyTriggerRequest {
        trigger: Some(conversion::manifest_to_proto(manifest, 0)),
        expected_generation: Some(0),
        operation: Some(proto::TriggerOperationPrecondition {
            operation_id: "transaction-trigger-control".into(),
            expected_state_version: Some(2),
        }),
    }
}

fn captured_actor() -> InvocationPrincipal {
    let mut value = principal();
    value.tenant = Some(TenantId("examples".into()));
    value
}

fn phase4_profile() -> latent_manifest::ManifestValidationProfile {
    latent_manifest::ManifestValidationProfile::phase4(
        latent_core::BudgetProfile::Phase4,
        latent_core::PHASE4_HOST_ABI_V1,
        &latent_manifest::phase4_host_abi_digest(),
    )
    .unwrap()
}

#[test]
fn transaction_trigger_requires_trusted_phase4_and_preserves_captured_store_grammar() {
    let request = captured_transaction_request();
    let limits = super::super::ManagementLimits::default();
    assert_eq!(
        validation::apply(request.clone(), captured_actor(), &limits)
            .unwrap_err()
            .code(),
        tonic::Code::InvalidArgument
    );
    let profile = phase4_profile();
    let selected =
        validation::apply_with_profile(request.clone(), captured_actor(), &limits, profile)
            .unwrap();
    let TriggerOperationRequest::Apply {
        context,
        manifest,
        expected_generation,
    } = selected
    else {
        panic!("expected apply");
    };
    assert_eq!(context.expected_state_version, 2);
    assert_eq!(expected_generation, 0);
    assert_eq!(context.tenant.0, "examples");
    let normalized =
        latent_control_store::http_routes::normalize_http_trigger(manifest.clone()).unwrap();
    assert_eq!(manifest, normalized);
    let wire = conversion::manifest_to_proto(manifest.clone(), 0);
    assert_eq!(wire, request.trigger.unwrap());
    assert_eq!(http_trigger_from_proto(wire).unwrap(), manifest);
    for mode in ["command", "query", "result"] {
        let mut request = captured_transaction_request();
        let configuration = &mut request.trigger.as_mut().unwrap().configuration;
        if mode == "command" {
            configuration.insert("entity".into(), "entity-control".into());
            assert_eq!(configuration.len(), 15);
        } else {
            configuration.insert("transactionMode".into(), mode.into());
            configuration.insert("method".into(), "GET".into());
            configuration.remove("preconditionKey");
            assert_eq!(configuration.len(), 13);
        }
        let expected = request.trigger.clone().unwrap();
        let TriggerOperationRequest::Apply { manifest, .. } =
            validation::apply_with_profile(request, captured_actor(), &limits, profile).unwrap()
        else {
            panic!("expected apply");
        };
        assert_eq!(conversion::manifest_to_proto(manifest.clone(), 0), expected);
        assert_eq!(
            latent_control_store::http_routes::normalize_http_trigger(manifest.clone()).unwrap(),
            manifest
        );
    }
}

fn invalid_transaction_request(change: &str) -> proto::ApplyTriggerRequest {
    let mut request = captured_transaction_request();
    let trigger = request.trigger.as_mut().unwrap();
    match change {
        "unknown" => {
            trigger
                .configuration
                .insert("unknown".into(), "value".into());
        }
        "schema" => {
            trigger
                .configuration
                .insert("stateSchema".into(), "wrong".into());
        }
        "incarnation" => {
            trigger
                .configuration
                .insert("incarnation".into(), "0".into());
        }
        "method" => {
            trigger.configuration.insert("method".into(), "GET".into());
        }
        "key" => {
            trigger
                .configuration
                .insert("preconditionKey".into(), "%%%".into());
        }
        "namespace" => {
            trigger.configuration.remove("namespace");
        }
        "profile" => {
            trigger
                .configuration
                .insert("profile".into(), "buffered-v1".into());
        }
        "static" => {
            trigger.target.as_mut().unwrap().kind = proto::TriggerTargetKind::StaticWeb as i32;
        }
        "operation" => request.operation = None,
        "generation" => request.expected_generation = None,
        "state-version" => request.operation.as_mut().unwrap().expected_state_version = None,
        "tenant" => {
            trigger.metadata.as_mut().unwrap().tenant = Some("foreign".into());
            trigger
                .target
                .as_mut()
                .unwrap()
                .publication
                .as_mut()
                .unwrap()
                .tenant = "foreign".into();
        }
        _ => unreachable!(),
    }
    request
}

#[test]
fn transaction_trigger_retains_closed_fields_target_scope_cas_and_allocation_limits() {
    let profile = phase4_profile();
    let limits = super::super::ManagementLimits::default();
    for change in [
        "unknown",
        "schema",
        "incarnation",
        "method",
        "key",
        "namespace",
        "profile",
        "static",
        "operation",
        "generation",
        "state-version",
        "tenant",
    ] {
        let request = invalid_transaction_request(change);
        let expected = if change == "tenant" {
            tonic::Code::PermissionDenied
        } else {
            tonic::Code::InvalidArgument
        };
        assert_eq!(
            validation::apply_with_profile(request, captured_actor(), &limits, profile)
                .unwrap_err()
                .code(),
            expected,
            "{change}"
        );
    }
    let mut request = captured_transaction_request();
    let schema = request
        .trigger
        .as_mut()
        .unwrap()
        .configuration
        .get_mut("stateSchema")
        .unwrap();
    let original = schema.clone();
    *schema = String::with_capacity(72);
    schema.push_str(&original);
    assert_eq!(
        validation::apply_with_profile(request, captured_actor(), &limits, profile)
            .unwrap_err()
            .code(),
        tonic::Code::ResourceExhausted
    );
    let request = captured_transaction_request();
    let mut tight = limits;
    tight.max_request_bytes = prost::Message::encoded_len(&request);
    assert_eq!(
        validation::apply_with_profile(request, captured_actor(), &tight, profile)
            .unwrap_err()
            .code(),
        tonic::Code::ResourceExhausted
    );
}

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
    let target = manifest.target.application().expect("application target");
    assert_eq!(target.deployment_generation, Some(1));
    assert!(target.publication.is_some());
    let limits = super::super::ManagementLimits::default();
    for kind in [proto::TriggerTargetKind::Unspecified as i32, 999] {
        let mut invalid = request();
        invalid
            .trigger
            .as_mut()
            .unwrap()
            .target
            .as_mut()
            .unwrap()
            .kind = kind;
        assert_eq!(
            validation::apply(invalid.clone(), principal(), &limits)
                .unwrap_err()
                .code(),
            tonic::Code::InvalidArgument
        );
        assert_eq!(
            conversion::manifest(invalid.trigger.unwrap())
                .unwrap_err()
                .code(),
            tonic::Code::InvalidArgument
        );
    }
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
fn static_web_wire_has_no_application_target_fields_and_rejects_hybrids() {
    let mut value = request();
    let trigger = value.trigger.as_mut().unwrap();
    let target = trigger.target.as_mut().unwrap();
    target.kind = proto::TriggerTargetKind::StaticWeb as i32;
    target.service.clear();
    target.contract.clear();
    target.function.clear();
    target.route = None;
    target.revision = None;
    target.deployment_generation = None;
    trigger
        .configuration
        .insert("profile".into(), "static-site-v1".into());
    let validated = validation::apply(
        value.clone(),
        principal(),
        &super::super::ManagementLimits::default(),
    )
    .unwrap();
    let TriggerOperationRequest::Apply { manifest, .. } = validated else {
        panic!("apply")
    };
    assert!(manifest.target.static_web().is_some());

    value
        .trigger
        .as_mut()
        .unwrap()
        .target
        .as_mut()
        .unwrap()
        .service = "hybrid".into();
    assert!(validation::apply(
        value,
        principal(),
        &super::super::ManagementLimits::default()
    )
    .is_err());
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
