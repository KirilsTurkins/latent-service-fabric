use super::*;
use tonic::Code;

fn audit(reason: &str) -> ErrorDetail {
    ErrorDetail {
        kind: "audit-journal".into(),
        fields: [("reason".into(), reason.into())].into(),
    }
}

fn failure(code: PlatformErrorCode, details: Vec<ErrorDetail>) -> PlatformError {
    PlatformError {
        code,
        message: "private storage failure at /private/audit".into(),
        retryable: false,
        details,
    }
}

fn decode(status: &Status) -> proto::PlatformError {
    proto::PlatformError::decode(status.details()).unwrap()
}

#[test]
fn audit_reasons_survive_management_without_private_fields_or_dispositions() {
    let limits = ManagementLimits {
        max_string_bytes: 1,
        ..ManagementLimits::default()
    };
    limits.validate().unwrap();
    for reason in [
        "audit-capacity",
        "audit-critical-pending",
        "audit-busy",
        "audit-unavailable",
        "audit-closed",
        "audit-corrupt",
    ] {
        let mut source = audit(reason);
        source.fields.insert("path".into(), "/private/audit".into());
        source.fields.insert("committed".into(), "false".into());
        let status = platform_status(
            failure(PlatformErrorCode::ResourceExhausted, vec![source]),
            &limits,
        );
        let wire = decode(&status);
        assert_eq!(status.code(), Code::ResourceExhausted);
        assert_eq!(wire.code, "resource-exhausted");
        assert!(!wire.retryable);
        assert_eq!(wire.detail_items.len(), 1);
        assert_eq!(wire.detail_items[0].kind, "audit-journal");
        assert_eq!(wire.detail_items[0].fields.len(), 1);
        assert_eq!(wire.detail_items[0].fields["reason"], reason);
        assert!(!format!("{status:?} {wire:?}").contains("/private/"));
    }
}

#[test]
fn unknown_audit_reasons_and_missing_reasons_are_not_public_diagnostics() {
    let limits = ManagementLimits::default();
    for reason in [
        "",
        "audit-capacity/private",
        "/private/audit",
        "audit-invalid",
    ] {
        let status = platform_status(
            failure(PlatformErrorCode::ResourceExhausted, vec![audit(reason)]),
            &limits,
        );
        assert!(decode(&status).detail_items.is_empty());
    }
    let mut missing = audit("audit-capacity");
    missing.fields.clear();
    assert!(public_details(vec![missing], &limits, 128).is_empty());
    let generic = platform_status(
        failure(PlatformErrorCode::ResourceExhausted, Vec::new()),
        &limits,
    );
    assert!(decode(&generic).detail_items.is_empty());
}

#[test]
fn audit_details_preserve_ambiguous_status_and_independent_committed_receipt() {
    let committed = ErrorDetail {
        kind: "deployment-mutation".into(),
        fields: [
            ("committed".into(), "true".into()),
            ("operation".into(), "apply".into()),
            ("object_generation".into(), "7".into()),
            ("catalog_generation".into(), "9".into()),
        ]
        .into(),
    };
    let status = platform_status(
        failure(
            PlatformErrorCode::Unavailable,
            vec![audit("audit-unavailable"), committed],
        ),
        &ManagementLimits::default(),
    );
    assert_eq!(status.code(), Code::Unavailable);
    let wire = decode(&status);
    assert_eq!(wire.code, "unavailable");
    assert_eq!(wire.detail_items.len(), 2);
    assert_eq!(wire.detail_items[0].fields.len(), 1);
    assert_eq!(wire.detail_items[0].fields["reason"], "audit-unavailable");
    assert_eq!(wire.detail_items[1].fields["committed"], "true");
    assert_eq!(wire.detail_items[1].fields["object_generation"], "7");
    assert_eq!(wire.detail_items[1].fields["catalog_generation"], "9");
}

#[test]
fn audit_details_obey_source_allocation_and_aggregate_response_bounds() {
    let limits = ManagementLimits {
        max_response_bytes: 4096,
        max_metadata_bytes: 4096,
        max_page_token_bytes: 4096,
        ..ManagementLimits::default()
    };
    limits.validate().unwrap();
    let mut oversized = audit("audit-capacity");
    let mut reason = String::with_capacity(limits.max_string_bytes.max(64) + 1);
    reason.push_str("audit-capacity");
    oversized.fields.insert("reason".into(), reason);
    assert!(public_details(vec![oversized], &limits, 128).is_empty());
    let mut restricted = limits.clone();
    restricted.auth.max_platform_error_fields = 1;
    let mut extra = audit("audit-capacity");
    extra.fields.insert("path".into(), "private".into());
    assert!(public_details(vec![extra], &restricted, 128).is_empty());
    assert!(public_details(vec![audit("audit-capacity"); 17], &limits, 128).is_empty());
    let output = public_details(vec![audit("audit-capacity"); 16], &limits, 128);
    assert!(!output.is_empty() && output.len() < 16);
    let mut retained = 128 + output.capacity() * std::mem::size_of::<proto::ErrorDetail>();
    for detail in &output {
        assert_eq!(detail.fields.len(), 1);
        retained += detail.kind.capacity() + detail.fields.capacity() * 128;
        for (key, value) in &detail.fields {
            retained += key.capacity() + value.capacity();
        }
    }
    assert!(retained <= limits.max_response_bytes);
    let status = platform_status(
        failure(
            PlatformErrorCode::ResourceExhausted,
            vec![audit("audit-capacity"); 16],
        ),
        &limits,
    );
    assert!(status.details().len() <= limits.max_response_bytes.min(MAX_ENCODED_ERROR_BYTES));
}
