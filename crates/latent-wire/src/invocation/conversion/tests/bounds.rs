use crate::invocation::validation::{validate_runtime_response, validate_runtime_status};
use tonic::Code;

use super::*;

#[test]
fn owned_public_conversion_moves_payload_effect_and_metadata_allocations() {
    let value = response(success());
    validate_runtime_response(&value, &InvocationLimits::default()).unwrap();
    let ActivationOutcome::Succeeded(success) = &value.outcome else {
        unreachable!()
    };
    let payload = success.output.as_ptr();
    let effects = success.effect_ids.as_ptr();
    let version = success.committed_state_version.as_ref().unwrap().as_ptr();
    let metadata = success.metadata.get("result").unwrap().as_ptr();
    let wire = public_invocation_response_to_proto(value, &InvocationLimits::default());
    let proto::invoke_response::Result::Success(success) = wire.result.unwrap() else {
        unreachable!()
    };
    assert_eq!(success.payload.as_ptr(), payload);
    assert_eq!(success.effect_ids.as_ptr(), effects);
    assert_eq!(
        success.committed_state_version.as_ref().unwrap().as_ptr(),
        version
    );
    assert_eq!(success.metadata.get("result").unwrap().as_ptr(), metadata);

    let value = status(&declared());
    let Some(RetainedActivationOutcome::DeclaredError(error)) = &value.terminal_outcome else {
        unreachable!()
    };
    let payload = error.payload.as_ptr();
    let wire = public_activation_status_to_proto(value, &InvocationLimits::default());
    let Some(proto::activation_status::TerminalOutcome::DeclaredError(error)) =
        wire.terminal_outcome
    else {
        unreachable!()
    };
    assert_eq!(error.payload.as_ptr(), payload);
}

#[test]
fn public_errors_redact_only_platform_diagnostics_and_keep_safe_detail_values() {
    let mut value = response(failure(PlatformErrorCode::ResourceExhausted));
    let ActivationOutcome::Failed { error, .. } = &mut value.outcome else {
        unreachable!()
    };
    error.details = vec![
        ErrorDetail {
            kind: "resource.limit".into(),
            fields: Metadata::from([
                ("resource".into(), "memory".into()),
                ("requested".into(), "2048".into()),
                ("limit".into(), "1024".into()),
                ("credential".into(), "secret\nmultiline".into()),
            ]),
        },
        ErrorDetail {
            kind: "engine.backtrace".into(),
            fields: Metadata::from([("frame".into(), "/srv/private\nframe2".into())]),
        },
    ];
    validate_runtime_response(&value, &InvocationLimits::default()).unwrap();
    let expected = error_detail_resource();
    let wire = public_invocation_response_to_proto(value, &InvocationLimits::default());
    let Some(proto::invoke_response::Result::PlatformFailure(error)) = wire.result else {
        unreachable!()
    };
    assert_eq!(error.code, "resource-exhausted");
    assert_eq!(
        error.message,
        public_platform_message(PlatformErrorCode::ResourceExhausted)
    );
    assert!(error.retryable);
    assert_eq!(error.detail_items, vec![expected]);
    let rendered = format!("{error:?}");
    for secret in ["secret", "private", "backtrace", "credential"] {
        assert!(!rendered.contains(secret));
    }

    let value = response(declared());
    assert_eq!(
        public_invocation_response_to_proto(value.clone(), &InvocationLimits::default()),
        invocation_response_to_proto(&value).unwrap()
    );
}

fn error_detail_resource() -> proto::ErrorDetail {
    proto::ErrorDetail {
        kind: "resource.limit".into(),
        fields: [
            ("resource".into(), "memory".into()),
            ("requested".into(), "2048".into()),
            ("limit".into(), "1024".into()),
        ]
        .into_iter()
        .collect(),
    }
}

#[test]
fn unknown_error_details_cannot_bypass_the_examined_detail_bound() {
    let limits = InvocationLimits {
        max_platform_error_details: 1,
        ..InvocationLimits::default()
    };
    let error = PlatformError {
        code: PlatformErrorCode::Internal,
        message: "secret".into(),
        retryable: false,
        details: vec![
            ErrorDetail {
                kind: "unknown".into(),
                fields: Metadata::new(),
            },
            ErrorDetail {
                kind: "retry".into(),
                fields: Metadata::from([("retry_after_millis".into(), "1".into())]),
            },
        ],
    };
    // The boundary rejects this input, and redaction also limits examined input
    // if called internally without that check; it cannot skip unbounded rows.
    let value = response(ActivationOutcome::Failed {
        terminal_state: ActivationTerminalState::PlatformFailed,
        error: error.clone(),
        consumption: consumption(),
    });
    assert_eq!(
        validate_runtime_response(&value, &limits)
            .unwrap_err()
            .code(),
        Code::ResourceExhausted
    );
    assert!(public_platform_error(error, &limits).details.is_empty());
}

#[test]
fn omitted_response_fields_and_spare_capacity_are_bounded_before_conversion() {
    let limits = InvocationLimits {
        max_string_bytes: 32,
        max_metadata_entries: 2,
        ..InvocationLimits::default()
    };
    let mut value = response(success());
    let ActivationOutcome::Succeeded(result) = &mut value.outcome else {
        unreachable!()
    };
    result.committed_state_version = Some("x".repeat(33));
    assert_eq!(
        validate_runtime_response(&value, &limits)
            .unwrap_err()
            .code(),
        Code::ResourceExhausted
    );
    let mut value = response(declared());
    let ActivationOutcome::DeclaredError { error, .. } = &mut value.outcome else {
        unreachable!()
    };
    error.message = "x".repeat(33);
    assert_eq!(
        validate_runtime_response(&value, &limits)
            .unwrap_err()
            .code(),
        Code::ResourceExhausted
    );

    let mut value = response(success());
    let ActivationOutcome::Succeeded(result) = &mut value.outcome else {
        unreachable!()
    };
    result.effect_ids = Vec::with_capacity(300);
    result.effect_ids.push("effect".into());
    let small = InvocationLimits {
        max_message_bytes: 4096,
        ..InvocationLimits::default()
    };
    assert_eq!(
        validate_runtime_response(&value, &small)
            .unwrap_err()
            .code(),
        Code::ResourceExhausted
    );

    let mut retained = status(&declared());
    let Some(RetainedActivationOutcome::DeclaredError(error)) = &mut retained.terminal_outcome
    else {
        unreachable!()
    };
    error.payload = Vec::with_capacity(65);
    error.payload.push(1);
    let small = InvocationLimits {
        max_payload_bytes: 64,
        ..InvocationLimits::default()
    };
    assert_eq!(
        validate_runtime_status(&retained, &ActivationId("activation-1".into()), &small)
            .unwrap_err()
            .code(),
        Code::ResourceExhausted
    );
}

#[test]
fn generated_catalog_identity_is_independent_of_short_caller_name_limit() {
    let mut value = response(success());
    value
        .receipt
        .resolved_revision
        .as_mut()
        .unwrap()
        .revision_id = RevisionId("r".repeat(83));
    let limits = InvocationLimits {
        max_id_bytes: 16,
        ..InvocationLimits::default()
    };
    validate_runtime_response(&value, &limits).unwrap();
    value.receipt.activation_id = ActivationId("a".repeat(44));
    validate_runtime_response(&value, &limits).unwrap();
    value.receipt.activation_id = ActivationId("a".repeat(45));
    assert_eq!(
        validate_runtime_response(&value, &limits)
            .unwrap_err()
            .code(),
        Code::ResourceExhausted
    );
}

#[test]
fn public_admission_details_use_the_current_owner_schema() {
    let error = PlatformError {
        code: PlatformErrorCode::AdmissionRejected,
        message: "private".into(),
        retryable: true,
        details: vec![ErrorDetail {
            kind: "admission.limit".into(),
            fields: Metadata::from([
                ("scope".into(), "tenant".into()),
                ("dimension".into(), "concurrency".into()),
                ("reason".into(), "capacity-exhausted".into()),
                ("private".into(), "hidden".into()),
            ]),
        }],
    };
    let public = public_platform_error(error, &InvocationLimits::default());
    assert_eq!(
        public.details[0].fields,
        Metadata::from([
            ("scope".into(), "tenant".into()),
            ("dimension".into(), "concurrency".into()),
            ("reason".into(), "capacity-exhausted".into()),
        ])
    );
}

#[test]
fn recognized_detail_keys_cannot_publish_unknown_atoms_or_non_u64_numbers() {
    let error = PlatformError {
        code: PlatformErrorCode::AdmissionRejected,
        message: "private".into(),
        retryable: true,
        details: vec![
            ErrorDetail {
                kind: "admission.limit".into(),
                fields: Metadata::from([
                    ("scope".into(), "SECRETABC123".into()),
                    ("reason".into(), "SECRETABC123".into()),
                    ("dimension".into(), "concurrency".into()),
                ]),
            },
            ErrorDetail {
                kind: "resource.limit".into(),
                fields: Metadata::from([
                    ("resource".into(), "memory".into()),
                    ("requested".into(), "18446744073709551616".into()),
                    ("limit".into(), u64::MAX.to_string()),
                ]),
            },
            ErrorDetail {
                kind: "state.conflict".into(),
                fields: Metadata::from([("expected_version".into(), "SECRETABC123".into())]),
            },
        ],
    };
    assert_eq!(
        platform_error_from_proto(platform_error_to_proto(&error)).unwrap(),
        error
    );
    let public = public_platform_error(error, &InvocationLimits::default());
    assert_eq!(public.details.len(), 2);
    assert_eq!(
        public.details[0].fields,
        Metadata::from([("dimension".into(), "concurrency".into())])
    );
    assert_eq!(
        public.details[1].fields,
        Metadata::from([
            ("resource".into(), "memory".into()),
            ("limit".into(), u64::MAX.to_string())
        ])
    );
    assert!(!format!("{public:?}").contains("SECRETABC123"));
}
