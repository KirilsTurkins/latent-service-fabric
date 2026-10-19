use latent_core::error::GuestTrapKind;

use crate::invocation::validation::{validate_runtime_response, validate_runtime_status};
use tonic::Code;

use super::*;

fn trap_failure(details: Vec<ErrorDetail>) -> ActivationOutcome {
    let mut outcome = failure(PlatformErrorCode::GuestTrap);
    let ActivationOutcome::Failed { error, .. } = &mut outcome else {
        unreachable!()
    };
    error.details = details;
    outcome
}

fn trap_detail(kind: &str) -> ErrorDetail {
    ErrorDetail {
        kind: "activation.guest-trap-kind".into(),
        fields: Metadata::from([("kind".into(), kind.into())]),
    }
}

fn private_details(kind: GuestTrapKind) -> Vec<ErrorDetail> {
    let mut detail = trap_detail(kind.wire_name());
    detail
        .fields
        .insert("credential".into(), "private-secret".into());
    detail
        .fields
        .insert("frame".into(), "/private/request/body".into());
    vec![
        detail,
        ErrorDetail {
            kind: "activation.guest-trap".into(),
            fields: Metadata::from([("message".into(), "private engine text".into())]),
        },
    ]
}

#[test]
fn known_trap_kinds_survive_public_invocation_encoding_without_private_fields() {
    let limits = InvocationLimits::default();
    for kind in GuestTrapKind::ALL {
        let value = response(trap_failure(private_details(*kind)));
        validate_runtime_response(&value, &limits).unwrap();
        let mut expected = value.clone();
        let ActivationOutcome::Failed { error, .. } = &mut expected.outcome else {
            unreachable!()
        };
        error.message = public_platform_message(error.code).into();
        error.details = vec![trap_detail(kind.wire_name())];
        let encoded = public_invocation_response_to_proto(value, &limits).encode_to_vec();
        let decoded = proto::InvokeResponse::decode(encoded.as_slice()).unwrap();
        assert_eq!(invocation_response_from_proto(decoded).unwrap(), expected);
    }
}

#[test]
fn known_trap_kinds_survive_retained_status_encoding_without_private_fields() {
    let limits = InvocationLimits::default();
    for kind in GuestTrapKind::ALL {
        let value = status(&trap_failure(private_details(*kind)));
        validate_runtime_status(&value, &value.activation_id, &limits).unwrap();
        let mut expected = value.clone();
        let Some(RetainedActivationOutcome::PlatformFailure(error)) =
            &mut expected.terminal_outcome
        else {
            unreachable!()
        };
        error.message = public_platform_message(error.code).into();
        error.details = vec![trap_detail(kind.wire_name())];
        let encoded = public_activation_status_to_proto(value, &limits).encode_to_vec();
        let decoded = proto::ActivationStatus::decode(encoded.as_slice()).unwrap();
        assert_eq!(activation_status_from_proto(decoded).unwrap(), expected);
    }
}

#[test]
fn arbitrary_trap_kinds_and_secret_fields_are_removed_from_public_outcomes() {
    let limits = InvocationLimits::default();
    for kind in [
        "",
        "future-trap",
        "RuntimeError",
        " runtime-error",
        "runtime-error ",
        "unreachable-code\n",
        "unreachable-code /private/credential=secret",
        "runt\u{0456}me-error",
        "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    ] {
        let outcome = trap_failure(vec![trap_detail(kind)]);
        validate_runtime_response(&response(outcome.clone()), &limits).unwrap();
        let retained = status(&outcome);
        validate_runtime_status(&retained, &retained.activation_id, &limits).unwrap();
        let wire = public_invocation_response_to_proto(response(outcome.clone()), &limits);
        let Some(proto::invoke_response::Result::PlatformFailure(error)) = wire.result else {
            unreachable!()
        };
        assert!(error.detail_items.is_empty());
        let wire = public_activation_status_to_proto(status(&outcome), &limits);
        let Some(proto::activation_status::TerminalOutcome::PlatformFailure(error)) =
            wire.terminal_outcome
        else {
            unreachable!()
        };
        assert!(error.detail_items.is_empty());
    }
    let unknown = ErrorDetail {
        kind: "activation.guest-trap-kind".into(),
        fields: Metadata::from([("credential".into(), "secret".into())]),
    };
    let ActivationOutcome::Failed { error, .. } = trap_failure(vec![unknown]) else {
        unreachable!()
    };
    assert!(public_platform_error(error, &limits).details.is_empty());
}

#[test]
fn trap_kind_projection_keeps_original_error_and_detail_bounds() {
    let detail = trap_detail(GuestTrapKind::UnreachableCode.wire_name());
    let ActivationOutcome::Failed { error, .. } = trap_failure(vec![detail.clone()]) else {
        unreachable!()
    };
    for limits in [
        InvocationLimits {
            max_platform_error_fields: 0,
            ..InvocationLimits::default()
        },
        InvocationLimits {
            max_platform_error_details: 0,
            ..InvocationLimits::default()
        },
        InvocationLimits {
            max_string_bytes: GuestTrapKind::UnreachableCode.wire_name().len() - 1,
            ..InvocationLimits::default()
        },
    ] {
        let public = public_platform_error(error.clone(), &limits);
        assert_eq!(public.code, error.code);
        assert_eq!(public.retryable, error.retryable);
        assert_eq!(public.message, public_platform_message(error.code));
        assert!(public.details.is_empty());
    }
    let limits = InvocationLimits {
        max_platform_error_details: 1,
        ..InvocationLimits::default()
    };
    let value = response(trap_failure(vec![
        ErrorDetail {
            kind: "engine.backtrace".into(),
            fields: Metadata::from([("frame".into(), "secret".into())]),
        },
        detail,
    ]));
    assert_eq!(
        validate_runtime_response(&value, &limits)
            .unwrap_err()
            .code(),
        Code::ResourceExhausted
    );
    let wire = public_invocation_response_to_proto(value, &limits);
    let Some(proto::invoke_response::Result::PlatformFailure(error)) = wire.result else {
        unreachable!()
    };
    assert!(error.detail_items.is_empty());
}

#[test]
fn fixed_backend_dispositions_survive_invocation_and_status_without_private_fields() {
    let limits = InvocationLimits::default();
    for code in [
        "guest-trap",
        "guest-runtime-error",
        "runtime-lifecycle-unproven",
        "budget-accounting-failed",
        "result-limit-exceeded",
        "invalid-component-result",
    ] {
        let detail = ErrorDetail {
            kind: "activation.guest-trap".into(),
            fields: Metadata::from([
                ("code".into(), code.into()),
                ("cell_id".into(), "private-cell".into()),
                ("message".into(), "private-engine-context".into()),
                ("credential".into(), "private-fixture-text".into()),
            ]),
        };
        let outcome = trap_failure(vec![detail]);
        let mut expected = outcome.clone();
        let ActivationOutcome::Failed { error, .. } = &mut expected else {
            unreachable!()
        };
        error.message = public_platform_message(error.code).into();
        error.details = vec![ErrorDetail {
            kind: "activation.guest-trap".into(),
            fields: Metadata::from([("code".into(), code.into())]),
        }];
        let value = response(outcome.clone());
        validate_runtime_response(&value, &limits).unwrap();
        let encoded = public_invocation_response_to_proto(value, &limits).encode_to_vec();
        let decoded = proto::InvokeResponse::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            invocation_response_from_proto(decoded).unwrap().outcome,
            expected
        );
        let retained = status(&outcome);
        validate_runtime_status(&retained, &retained.activation_id, &limits).unwrap();
        let encoded = public_activation_status_to_proto(retained, &limits).encode_to_vec();
        let decoded = proto::ActivationStatus::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            activation_status_from_proto(decoded)
                .unwrap()
                .terminal_outcome,
            Some(expected.retained_terminal_outcome())
        );
    }
}

#[test]
fn backend_disposition_rejects_arbitrary_tokens_and_preserves_projection_bounds() {
    let detail = |code: &str| ErrorDetail {
        kind: "activation.guest-trap".into(),
        fields: Metadata::from([("code".into(), code.into())]),
    };
    for code in [
        "",
        "future-failure",
        "GuestTrap",
        " guest-trap",
        "guest-trap ",
        "guest-trap\n",
        "guest-trap private-fixture-text",
        "guest-tr\u{0430}p",
    ] {
        let outcome = trap_failure(vec![detail(code)]);
        let wire = public_invocation_response_to_proto(
            response(outcome.clone()),
            &InvocationLimits::default(),
        );
        let Some(proto::invoke_response::Result::PlatformFailure(error)) = wire.result else {
            unreachable!()
        };
        assert!(error.detail_items.is_empty());
        let wire =
            public_activation_status_to_proto(status(&outcome), &InvocationLimits::default());
        let Some(proto::activation_status::TerminalOutcome::PlatformFailure(error)) =
            wire.terminal_outcome
        else {
            unreachable!()
        };
        assert!(error.detail_items.is_empty());
    }
    let ActivationOutcome::Failed { error, .. } =
        trap_failure(vec![detail("runtime-lifecycle-unproven")])
    else {
        unreachable!()
    };
    for limits in [
        InvocationLimits {
            max_platform_error_fields: 0,
            ..InvocationLimits::default()
        },
        InvocationLimits {
            max_platform_error_details: 0,
            ..InvocationLimits::default()
        },
        InvocationLimits {
            max_string_bytes: "runtime-lifecycle-unproven".len() - 1,
            ..InvocationLimits::default()
        },
    ] {
        let public = public_platform_error(error.clone(), &limits);
        assert_eq!(public.code, error.code);
        assert_eq!(public.retryable, error.retryable);
        assert!(public.details.is_empty());
    }
    let ActivationOutcome::Failed { error, .. } =
        trap_failure(vec![detail(&"private".repeat(1024))])
    else {
        unreachable!()
    };
    assert!(public_platform_error(error, &InvocationLimits::default())
        .details
        .is_empty());
}

#[test]
fn known_host_failure_codes_survive_invocation_status_and_foreign_envelopes() {
    let limits = InvocationLimits::default();
    for code in [
        PlatformErrorCode::Unavailable,
        PlatformErrorCode::DeadlineExceeded,
        PlatformErrorCode::Cancelled,
        PlatformErrorCode::ResourceExhausted,
        PlatformErrorCode::PermissionDenied,
        PlatformErrorCode::Unauthenticated,
        PlatformErrorCode::InvalidArgument,
        PlatformErrorCode::NotFound,
        PlatformErrorCode::AlreadyExists,
        PlatformErrorCode::IncompatibleContract,
        PlatformErrorCode::StateConflict,
        PlatformErrorCode::DependencyFailed,
        PlatformErrorCode::GuestTrap,
        PlatformErrorCode::CorruptArtifact,
        PlatformErrorCode::RouteUnavailable,
        PlatformErrorCode::AdmissionRejected,
        PlatformErrorCode::Internal,
    ] {
        let selected = ErrorDetail {
            kind: "activation.guest-host-failure".into(),
            fields: Metadata::from([("code".into(), code.wire_code().into())]),
        };
        let mut detail = selected.clone();
        for field in ["cell_id", "provider", "credential", "message", "backtrace"] {
            detail
                .fields
                .insert(field.into(), "private-fixture-text".into());
        }
        let outcome = trap_failure(vec![detail]);
        let mut expected = outcome.clone();
        let ActivationOutcome::Failed { error, .. } = &mut expected else {
            unreachable!()
        };
        error.message = public_platform_message(error.code).into();
        error.details = vec![selected];
        let expected_error = error.clone();
        let value = response(outcome.clone());
        validate_runtime_response(&value, &limits).unwrap();
        let encoded = public_invocation_response_to_proto(value, &limits).encode_to_vec();
        let decoded = proto::InvokeResponse::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            invocation_response_from_proto(decoded).unwrap().outcome,
            expected
        );
        let retained = status(&outcome);
        validate_runtime_status(&retained, &retained.activation_id, &limits).unwrap();
        let encoded = public_activation_status_to_proto(retained, &limits).encode_to_vec();
        let decoded = proto::ActivationStatus::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            activation_status_from_proto(decoded)
                .unwrap()
                .terminal_outcome,
            Some(expected.retained_terminal_outcome())
        );
        let ActivationOutcome::Failed { error, .. } = outcome else {
            unreachable!()
        };
        let foreign = sanitize_platform_error(error.into(), &limits).unwrap();
        let expected_proto: proto::PlatformError = expected_error.into();
        assert_eq!(foreign, expected_proto);
        assert!(!format!("{foreign:?}").contains("private-fixture-text"));
    }
}

#[test]
fn host_failure_projection_rejects_unknown_private_fields_and_preserves_bounds() {
    for (kind, key, value) in [
        ("activation.guest-host-failure", "code", ""),
        ("activation.guest-host-failure", "code", "Unavailable"),
        ("activation.guest-host-failure", "code", " unavailable"),
        ("activation.guest-host-failure", "code", "unavailable "),
        ("activation.guest-host-failure", "code", "unavailable\n"),
        ("activation.guest-host-failure", "code", "future-failure"),
        (
            "activation.guest-host-failure",
            "code",
            "unavail\u{0430}ble",
        ),
        (
            "activation.guest-host-failure",
            "code",
            "private-fixture-text",
        ),
        (
            "activation.guest-host-failure",
            "capabilityFailure",
            "unavailable",
        ),
        (
            "activation.guest-host-failure/private",
            "code",
            "unavailable",
        ),
    ] {
        let outcome = trap_failure(vec![ErrorDetail {
            kind: kind.into(),
            fields: Metadata::from([(key.into(), value.into())]),
        }]);
        let ActivationOutcome::Failed { error, .. } = outcome else {
            unreachable!()
        };
        let public =
            sanitize_platform_error(error.clone().into(), &InvocationLimits::default()).unwrap();
        assert_eq!(public.code, error.code.wire_code());
        assert_eq!(public.retryable, error.retryable);
        assert_eq!(public.message, public_platform_message(error.code));
        assert!(public.detail_items.is_empty());
    }
    let detail = |value: &str| ErrorDetail {
        kind: "activation.guest-host-failure".into(),
        fields: Metadata::from([("code".into(), value.into())]),
    };
    let ActivationOutcome::Failed { error, .. } = trap_failure(vec![detail("resource-exhausted")])
    else {
        unreachable!()
    };
    for limits in [
        InvocationLimits {
            max_platform_error_fields: 0,
            ..InvocationLimits::default()
        },
        InvocationLimits {
            max_platform_error_details: 0,
            ..InvocationLimits::default()
        },
        InvocationLimits {
            max_string_bytes: "resource-exhausted".len() - 1,
            ..InvocationLimits::default()
        },
    ] {
        let public = sanitize_platform_error(error.clone().into(), &limits).unwrap();
        assert_eq!(public.code, error.code.wire_code());
        assert_eq!(public.retryable, error.retryable);
        assert!(public.detail_items.is_empty());
    }
    let ActivationOutcome::Failed { error, .. } =
        trap_failure(vec![detail(&"private-fixture-text".repeat(1024))])
    else {
        unreachable!()
    };
    let public = sanitize_platform_error(error.into(), &InvocationLimits::default()).unwrap();
    assert!(public.detail_items.is_empty());
}

#[test]
fn runtime_phase_projection_is_closed_coupled_and_preserves_terminal_semantics() {
    let limits = InvocationLimits::default();
    let detail = |kind: &str, phase: &str| ErrorDetail {
        kind: "activation.guest-trap-kind".into(),
        fields: Metadata::from([
            ("kind".into(), kind.into()),
            ("phase".into(), phase.into()),
            ("provider".into(), "private-fixture-text".into()),
        ]),
    };
    for phase in ["instantiate", "export-lookup", "call-and-postreturn"] {
        let outcome = trap_failure(vec![detail("runtime-error", phase)]);
        let mut expected = outcome.clone();
        let ActivationOutcome::Failed { error, .. } = &mut expected else {
            unreachable!()
        };
        error.message = public_platform_message(error.code).into();
        error.details[0].fields.remove("provider");
        let expected_error = error.clone();
        let encoded =
            public_invocation_response_to_proto(response(outcome.clone()), &limits).encode_to_vec();
        let decoded = proto::InvokeResponse::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            invocation_response_from_proto(decoded).unwrap().outcome,
            expected
        );
        let encoded = public_activation_status_to_proto(status(&outcome), &limits).encode_to_vec();
        let decoded = proto::ActivationStatus::decode(encoded.as_slice()).unwrap();
        assert_eq!(
            activation_status_from_proto(decoded)
                .unwrap()
                .terminal_outcome,
            Some(expected.retained_terminal_outcome())
        );
        let ActivationOutcome::Failed { error, .. } = outcome else {
            unreachable!()
        };
        let public = sanitize_platform_error(error.into(), &limits).unwrap();
        let expected_proto: proto::PlatformError = expected_error.into();
        assert_eq!(public, expected_proto);
        assert!(!format!("{public:?}").contains("private-fixture-text"));
    }
    for (kind, phase) in [
        ("runtime-error", "Instantiate"),
        ("runtime-error", " instantiate"),
        ("runtime-error", "instantiate\n"),
        ("runtime-error", "private-fixture-text"),
        ("runtime-error", ""),
        ("unreachable-code", "instantiate"),
    ] {
        let ActivationOutcome::Failed { error, .. } = trap_failure(vec![detail(kind, phase)])
        else {
            unreachable!()
        };
        let expected_retryable = error.retryable;
        let public = sanitize_platform_error(error.into(), &limits).unwrap();
        assert_eq!(public.detail_items.len(), 1);
        assert_eq!(
            public.detail_items[0].fields,
            std::collections::HashMap::from([("kind".into(), kind.into())])
        );
        assert_eq!(public.code, "guest-trap");
        assert_eq!(public.retryable, expected_retryable);
    }
    let ActivationOutcome::Failed { error, .. } =
        trap_failure(vec![detail("runtime-error", "call-and-postreturn")])
    else {
        unreachable!()
    };
    for limits in [
        InvocationLimits {
            max_platform_error_fields: 1,
            ..Default::default()
        },
        InvocationLimits {
            max_platform_error_details: 0,
            ..Default::default()
        },
        InvocationLimits {
            max_string_bytes: 13,
            ..Default::default()
        },
    ] {
        let public = sanitize_platform_error(error.clone().into(), &limits).unwrap();
        assert!(public
            .detail_items
            .iter()
            .all(|item| !item.fields.contains_key("phase")));
        assert_eq!(public.code, "guest-trap");
        assert_eq!(public.retryable, error.retryable);
    }
}
