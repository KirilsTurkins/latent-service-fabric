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
