use super::*;
use latent_core::ErrorDetail;

#[test]
fn currentness_diagnostic_never_changes_mutation_certainty_or_exposes_peer_text() {
    for reason in latent_core::error::ADMISSION_CURRENTNESS_REASONS
        .iter()
        .copied()
        .chain(["unknown-private-reason"])
    {
        let error = proto::PlatformError {
            code: "unavailable".into(),
            message: "private".into(),
            retryable: true,
            detail_items: vec![proto::ErrorDetail {
                kind: "admission.currentness".into(),
                fields: [
                    ("reason".into(), reason.into()),
                    ("secret".into(), "private".into()),
                ]
                .into(),
            }],
        };
        let status =
            Status::with_details(Code::Unavailable, "private", error.encode_to_vec().into());
        let result = Failure::from_status(&status);
        assert!(!result.outcome_known);
        assert!(!result.error.to_string().contains("private"));
        if reason == "unknown-private-reason" {
            assert_eq!(result.error["details"], serde_json::json!([]));
        } else {
            assert_eq!(result.error["details"][0]["fields"]["reason"], reason);
        }
    }
}

#[test]
fn guest_trap_currentness_keeps_known_invocation_failure_and_closed_details() {
    for reason in latent_core::error::ADMISSION_CURRENTNESS_REASONS
        .iter()
        .copied()
        .chain(["unknown-private-reason"])
    {
        let error = PlatformError {
            code: PlatformErrorCode::GuestTrap,
            message: "private provider context /private/path".into(),
            retryable: false,
            details: vec![
                ErrorDetail {
                    kind: "activation.guest-trap".into(),
                    fields: [
                        ("code".into(), "guest-runtime-error".into()),
                        ("cell_id".into(), "private-cell".into()),
                        ("capabilityFailure".into(), "Unavailable".into()),
                        ("admissionCurrentnessReason".into(), reason.into()),
                    ]
                    .into(),
                },
                ErrorDetail {
                    kind: "admission.currentness".into(),
                    fields: [
                        ("reason".into(), reason.into()),
                        ("private-field".into(), "private-value".into()),
                    ]
                    .into(),
                },
            ],
        };
        let data = json!({"terminalState":"guest_trap", "consumption":{
            "cpuFuel":u64::MAX.to_string(), "peakMemoryBytes":"53018624"}});
        // This is the existing invocation-response projection, not an
        // ambiguous transport Status. The diagnostic cannot change its result.
        let outcome = crate::output::Outcome::platform_failure(data.clone(), &error);
        assert_eq!(outcome.exit_code(), 4);
        let details = if reason == "unknown-private-reason" {
            json!([])
        } else {
            json!([{"kind":"admission.currentness", "fields":{"reason":reason}}])
        };
        assert_eq!(
            outcome.document("invoke"),
            json!({"schemaVersion":"latent.cli.result.v1", "command":"invoke",
                "category":"platform-failure", "data":data,
                "error":{"code":"guest-trap", "message":"The platform reported a failure.",
                    "retryable":false, "details":details},
                "requestDispatched":false, "outcomeKnown":true})
        );
        assert!(!outcome.document("invoke").to_string().contains("private"));
    }
}

#[test]
fn guest_trap_private_metadata_cannot_expand_public_diagnostic_vocabulary() {
    for (kind, key, value) in [
        (
            "activation.guest-trap",
            "capabilityFailure",
            "Unavailable".to_owned(),
        ),
        (
            "activation.guest-trap",
            "classification",
            "runtime-error".to_owned(),
        ),
        (
            "activation.guest-trap",
            "trap",
            "unreachable-code".to_owned(),
        ),
        (
            "admission.currentness",
            "admissionCurrentnessReason",
            "admission-authority-busy".to_owned(),
        ),
        (
            "admission.currentness",
            "reason",
            "admission-authority-busy private".to_owned(),
        ),
        (
            "admission.currentness",
            "reason",
            "admission-authority-busy ".to_owned(),
        ),
        ("admission.currentness", "reason", "private".repeat(172)),
    ] {
        let error = PlatformError {
            code: PlatformErrorCode::GuestTrap,
            message: "private".into(),
            retryable: false,
            details: vec![ErrorDetail {
                kind: kind.into(),
                fields: [(key.into(), value)].into(),
            }],
        };
        let public = platform_value(&error);
        assert_eq!(public["details"], json!([]));
        assert_eq!(public["code"], "guest-trap");
        assert_eq!(public["retryable"], false);
        assert!(!public.to_string().contains("private"));
    }
}

#[test]
fn guest_trap_currentness_never_makes_an_ambiguous_transport_failure_known() {
    let error = proto::PlatformError {
        code: "guest-trap".into(),
        message: "private runtime context".into(),
        retryable: false,
        detail_items: vec![proto::ErrorDetail {
            kind: "admission.currentness".into(),
            fields: [("reason".into(), "admission-authority-busy".into())].into(),
        }],
    };
    let status = Status::with_details(Code::Internal, "private", error.encode_to_vec().into());
    let failure = Failure::from_status(&status);
    assert_eq!(failure.category, Category::PlatformError);
    assert!(!failure.outcome_known);
    assert!(failure.request_dispatched);
    assert_eq!(failure.error["code"], "guest-trap");
    assert_eq!(failure.error["retryable"], false);
    assert_eq!(
        failure.error["details"],
        json!([
            {"kind":"admission.currentness", "fields":{"reason":"admission-authority-busy"}}
        ])
    );
    assert!(!failure.error.to_string().contains("private"));
}

#[test]
fn status_text_is_never_a_diagnostic_and_ambiguity_is_explicit() {
    for code in [
        Code::Unavailable,
        Code::DeadlineExceeded,
        Code::Cancelled,
        Code::Internal,
        Code::Unknown,
    ] {
        let failure =
            Failure::from_status(&Status::new(code, "secret-token /private/path backtrace"));
        assert_eq!(failure.category, Category::TransportError);
        assert!(!failure.outcome_known);
        assert!(!failure.error.to_string().contains("secret-token"));
    }
    let failure = Failure::from_status(&Status::not_found("private foreign ID"));
    assert_eq!(failure.category, Category::NotFound);
    assert!(failure.outcome_known);
}

#[test]
fn typed_committed_receipt_survives_without_private_diagnostics() {
    let error = proto::PlatformError {
        code: "unavailable".into(),
        message: "private path".into(),
        retryable: false,
        detail_items: vec![proto::ErrorDetail {
            kind: "deployment-mutation".into(),
            fields: [
                ("committed", "true"),
                ("operation", "apply"),
                ("object_generation", "9007199254740993"),
                ("catalog_generation", "9007199254740994"),
                ("deployment_id", "private-id"),
            ]
            .into_iter()
            .map(|(k, v)| (k.into(), v.into()))
            .collect(),
        }],
    };
    let status = Status::with_details(Code::Unavailable, "private", error.encode_to_vec().into());
    let failure = Failure::from_status(&status);
    assert_eq!(failure.category, Category::PlatformError);
    assert!(failure.outcome_known);
    assert_eq!(
        failure.error["details"][0]["fields"]["object_generation"],
        "9007199254740993"
    );
    assert!(!failure.error.to_string().contains("private"));
}

#[test]
fn malformed_unknown_and_inconsistent_typed_errors_are_protocol_failures() {
    let mut error = proto::PlatformError {
        code: "future-secret".into(),
        message: String::new(),
        retryable: false,
        detail_items: vec![],
    };
    for details in [vec![255], vec![0; 8193], error.encode_to_vec()] {
        let failure = Failure::from_status(&Status::with_details(
            Code::Internal,
            "private",
            details.into(),
        ));
        assert_eq!(failure.category, Category::TransportError);
        assert!(!failure.error.to_string().contains("future-secret"));
    }
    error.code = "not-found".into();
    assert_eq!(
        Failure::from_status(&Status::with_details(
            Code::Internal,
            "private",
            error.encode_to_vec().into()
        ))
        .category,
        Category::TransportError
    );
}

#[test]
fn bare_client_limit_codes_are_ambiguous_but_typed_limits_are_platform_failures() {
    for code in [Code::ResourceExhausted, Code::OutOfRange, Code::DataLoss] {
        let failure = Failure::from_status(&Status::new(code, "private decoding diagnostic"));
        assert_eq!(failure.category, Category::TransportError, "{code:?}");
        assert!(!failure.outcome_known, "{code:?}");
        assert!(!failure.error.to_string().contains("private"));
    }
    let error = proto::PlatformError {
        code: "resource-exhausted".to_owned(),
        message: "private bounded platform diagnostic".to_owned(),
        retryable: false,
        detail_items: Vec::new(),
    };
    let failure = Failure::from_status(&Status::with_details(
        Code::ResourceExhausted,
        "private",
        error.encode_to_vec().into(),
    ));
    assert_eq!(failure.category, Category::PlatformError);
    assert!(failure.outcome_known);
    assert_eq!(failure.error["code"], "resource-exhausted");
    assert!(!failure.error.to_string().contains("private"));
}

#[test]
fn definitive_bare_application_rejections_remain_known_without_remote_text() {
    for code in [
        Code::InvalidArgument,
        Code::PermissionDenied,
        Code::Unauthenticated,
        Code::AlreadyExists,
        Code::FailedPrecondition,
        Code::Aborted,
        Code::Unimplemented,
    ] {
        let failure = Failure::from_status(&Status::new(code, "private remote diagnostic"));
        assert_eq!(failure.category, Category::PlatformError, "{code:?}");
        assert!(failure.outcome_known, "{code:?}");
        assert!(!failure.error.to_string().contains("private"));
    }
}

#[test]
fn malformed_commit_details_cannot_turn_an_ambiguous_failure_into_known_commit() {
    for (key, value) in [
        ("committed", "false"),
        ("operation", "unknown-private-operation"),
        ("object_generation", "0"),
        ("object_generation", "18446744073709551616"),
        ("catalog_generation", "01"),
    ] {
        let mut fields = [
            ("committed", "true"),
            ("operation", "apply"),
            ("object_generation", "1"),
            ("catalog_generation", "2"),
        ]
        .into_iter()
        .map(|(key, value)| (key.to_owned(), value.to_owned()))
        .collect::<std::collections::HashMap<_, _>>();
        fields.insert(key.to_owned(), value.to_owned());
        let error = proto::PlatformError {
            code: "unavailable".to_owned(),
            message: String::new(),
            retryable: false,
            detail_items: vec![proto::ErrorDetail {
                kind: "deployment-mutation".to_owned(),
                fields,
            }],
        };
        let failure = Failure::from_status(&Status::with_details(
            Code::Unavailable,
            "private",
            error.encode_to_vec().into(),
        ));
        assert_eq!(failure.category, Category::PlatformError);
        assert!(!failure.outcome_known, "{key}={value}");
        assert_eq!(failure.error["details"], json!([]));
    }
}
