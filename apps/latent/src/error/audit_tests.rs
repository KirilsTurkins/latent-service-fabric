use super::*;
use latent_core::ErrorDetail;

#[test]
fn audit_reasons_are_closed_and_never_disclose_peer_text() {
    let error = |reason: &str| PlatformError {
        code: PlatformErrorCode::ResourceExhausted,
        message: "private /journal/path token=secret".into(),
        retryable: false,
        details: vec![ErrorDetail {
            kind: "audit-journal".into(),
            fields: [
                ("reason".into(), reason.into()),
                ("path".into(), "/private/journal".into()),
                ("token".into(), "private-token".into()),
                ("committed".into(), "false".into()),
            ]
            .into(),
        }],
    };
    for reason in [
        "audit-capacity",
        "audit-critical-pending",
        "audit-busy",
        "audit-unavailable",
        "audit-closed",
        "audit-corrupt",
    ] {
        let public = platform_value(&error(reason));
        assert_eq!(
            public["details"],
            json!([{"kind":"audit-journal", "fields":{"reason":reason}}])
        );
        assert!(!public.to_string().contains("private"));
        assert!(!public.to_string().contains("committed"));
    }
    for reason in ["", "audit-capacity\n", "AuditCapacity", "/private/path"] {
        assert_eq!(platform_value(&error(reason))["details"], json!([]));
    }
}

#[test]
fn audit_diagnostics_preserve_known_rejection_and_transport_uncertainty() {
    for (grpc, code, known) in [
        (Code::ResourceExhausted, "resource-exhausted", true),
        (Code::Unavailable, "unavailable", false),
        (Code::DeadlineExceeded, "deadline-exceeded", false),
        (Code::Cancelled, "cancelled", false),
    ] {
        let response = proto::PlatformError {
            code: code.into(),
            message: "private storage failure".into(),
            retryable: false,
            detail_items: vec![proto::ErrorDetail {
                kind: "audit-journal".into(),
                fields: [("reason".into(), "audit-capacity".into())].into(),
            }],
        };
        let status = Status::with_details(grpc, "private", response.encode_to_vec().into());
        let failure = Failure::from_status(&status);
        assert_eq!(failure.outcome_known, known);
        assert!(failure.request_dispatched);
        assert_eq!(failure.error["details"][0]["fields"]["reason"], "audit-capacity");
        assert!(!failure.error.to_string().contains("private"));
    }
    // A bare transport resource error is not the producer's typed rejection.
    let bare = Failure::from_status(&Status::resource_exhausted("audit-capacity"));
    assert!(!bare.outcome_known);
    assert!(bare.error.get("details").is_none());
}
