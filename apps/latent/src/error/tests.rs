use super::*;

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
