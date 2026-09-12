use super::{platform_status, proto, ManagementLimits};
use latent_core::{ErrorDetail, Metadata, PlatformError, PlatformErrorCode};
use prost::Message;

fn detail() -> ErrorDetail {
    ErrorDetail {
        kind: "release-operation".to_owned(),
        fields: Metadata::from([
            ("operation_id".to_owned(), "retained-op".to_owned()),
            ("disposition".to_owned(), "uncertain".to_owned()),
            ("reason".to_owned(), "operator-revocation".to_owned()),
            ("generation".to_owned(), "7".to_owned()),
        ]),
    }
}
fn convert(detail: ErrorDetail) -> proto::PlatformError {
    let status = platform_status(
        PlatformError {
            code: PlatformErrorCode::Unavailable,
            message: "secret/path".to_owned(),
            retryable: false,
            details: vec![detail],
        },
        &ManagementLimits::default(),
    );
    proto::PlatformError::decode(status.details()).unwrap()
}

#[test]
fn release_operation_details_preserve_uncertainty_and_strip_private_messages() {
    let wire = convert(detail());
    assert_eq!(wire.detail_items[0].fields["disposition"], "uncertain");
    assert_eq!(wire.detail_items[0].fields["generation"], "7");
    assert!(!format!("{wire:?}").contains("secret/path"));
    let mut without = detail();
    without.fields.remove("generation");
    assert_eq!(convert(without).detail_items.len(), 1);
    for (disposition, reason) in [
        ("rejected", "content-conflict"),
        ("uncertain", "mutation-uncertain"),
        ("committed", "evidence-reclamation-pending"),
    ] {
        let mut value = detail();
        value
            .fields
            .insert("disposition".to_owned(), disposition.to_owned());
        value.fields.insert("reason".to_owned(), reason.to_owned());
        let wire = convert(value);
        assert_eq!(wire.detail_items[0].fields["reason"], reason);
    }
}

#[test]
fn release_operation_details_reject_missing_unknown_and_oversized_fields() {
    for missing in ["operation_id", "disposition", "reason"] {
        let mut changed = detail();
        changed.fields.remove(missing);
        assert!(convert(changed).detail_items.is_empty());
    }
    for (key, value) in [
        ("operation_id", ""),
        ("operation_id", "bad id"),
        ("disposition", "rollback"),
        ("reason", "private-error"),
        ("generation", "0"),
        ("generation", "07"),
        ("generation", "18446744073709551616"),
        ("path", "secret"),
    ] {
        let mut changed = detail();
        changed.fields.insert(key.to_owned(), value.to_owned());
        assert!(convert(changed).detail_items.is_empty());
    }
    let mut changed = detail();
    let mut excess = String::with_capacity(129);
    excess.push_str("short");
    changed.fields.insert("operation_id".to_owned(), excess);
    assert!(convert(changed).detail_items.is_empty());
}
