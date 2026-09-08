use latent_core::Metadata;
use tonic::Code;

use super::*;

fn mutation(operation: &str) -> ErrorDetail {
    ErrorDetail {
        kind: "deployment-mutation".to_owned(),
        fields: Metadata::from([
            ("deployment_id".to_owned(), "private-record".to_owned()),
            ("object_generation".to_owned(), u64::MAX.to_string()),
            ("catalog_generation".to_owned(), u64::MAX.to_string()),
            ("operation".to_owned(), operation.to_owned()),
            ("committed".to_owned(), "true".to_owned()),
        ]),
    }
}

fn catalog(reason: &str) -> ErrorDetail {
    ErrorDetail {
        kind: "deployment-catalog".to_owned(),
        fields: Metadata::from([("reason".to_owned(), reason.to_owned())]),
    }
}

fn failure(details: Vec<ErrorDetail>) -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::Unavailable,
        message: "filesystem /private/tenant/catalog.json failed".to_owned(),
        retryable: true,
        details,
    }
}

fn decoded(status: &Status) -> proto::PlatformError {
    assert!(!status.details().is_empty());
    proto::PlatformError::decode(status.details()).unwrap()
}

#[test]
fn public_error_retains_commit_receipt_and_redacts_private_diagnostics() {
    let mut receipt = mutation("apply");
    receipt
        .fields
        .insert("path".to_owned(), "/private/catalog.json".to_owned());
    let status = platform_status(
        failure(vec![
            catalog("commit-durability-uncertain"),
            receipt,
            ErrorDetail {
                kind: "private-diagnostics".to_owned(),
                fields: Metadata::from([("secret".to_owned(), "private-value".to_owned())]),
            },
        ]),
        &ManagementLimits::default(),
    );
    assert_eq!(status.code(), Code::Unavailable);
    let wire = decoded(&status);
    assert_eq!(wire.code, "unavailable");
    assert!(wire.retryable);
    assert_eq!(wire.message, status.message());
    assert_eq!(wire.detail_items.len(), 2);
    assert_eq!(
        wire.detail_items[0].fields["reason"],
        "commit-durability-uncertain"
    );
    assert_eq!(wire.detail_items[1].fields.len(), 4);
    assert_eq!(wire.detail_items[1].fields["committed"], "true");
    assert_eq!(wire.detail_items[1].fields["operation"], "apply");
    let public = format!("{status:?} {wire:?}");
    for private in [
        "/private/",
        "private-record",
        "private-value",
        "private-diagnostics",
    ] {
        assert!(!public.contains(private));
    }
}

#[test]
fn fixed_receipt_schema_and_exact_stamps_ignore_small_caller_string_limits() {
    let limits = ManagementLimits {
        max_string_bytes: 1,
        ..ManagementLimits::default()
    };
    limits.validate().unwrap();
    for operation in ["apply", "delete"] {
        let mut source = mutation(operation);
        // This caller identifier is valid under its own ceiling and is redacted.
        source
            .fields
            .insert("deployment_id".to_owned(), "x".repeat(limits.max_id_bytes));
        let wire = decoded(&platform_status(failure(vec![source]), &limits));
        assert_eq!(wire.detail_items.len(), 1);
        let receipt = &wire.detail_items[0];
        assert_eq!(receipt.kind, "deployment-mutation");
        assert_eq!(receipt.fields["object_generation"], u64::MAX.to_string());
        assert_eq!(receipt.fields["catalog_generation"], u64::MAX.to_string());
        assert_eq!(receipt.fields["operation"], operation);
        assert_eq!(receipt.fields["committed"], "true");
    }
}

#[test]
fn malformed_commit_receipts_are_omitted_atomically() {
    let limits = ManagementLimits::default();
    for missing in [
        "operation",
        "committed",
        "object_generation",
        "catalog_generation",
    ] {
        let mut receipt = mutation("apply");
        receipt.fields.remove(missing);
        assert!(decoded(&platform_status(failure(vec![receipt]), &limits))
            .detail_items
            .is_empty());
    }
    for (key, invalid) in [
        ("operation", "publish"),
        ("committed", "false"),
        ("object_generation", "18446744073709551616"),
        ("object_generation", "0"),
        ("object_generation", "-1"),
        ("object_generation", "+1"),
        ("catalog_generation", "1 "),
        ("catalog_generation", ""),
        ("catalog_generation", "000000000000000000001"),
    ] {
        let mut receipt = mutation("delete");
        receipt.fields.insert(key.to_owned(), invalid.to_owned());
        assert!(decoded(&platform_status(failure(vec![receipt]), &limits))
            .detail_items
            .is_empty());
    }
}

#[test]
fn current_page_reason_names_survive_and_obsolete_names_do_not() {
    let limits = ManagementLimits::default();
    for reason in [
        "invalid-deployment-page-size",
        "invalid-deployment-page-scope",
        "invalid-deployment-page-token",
        "expired-deployment-page-token",
        "deployment-page-byte-limit",
        "deployment-generation-conflict",
    ] {
        let wire = decoded(&platform_status(failure(vec![catalog(reason)]), &limits));
        assert_eq!(wire.detail_items[0].fields["reason"], reason);
    }
    for reason in [
        "invalid-page-token",
        "catalog-publication-conflict",
        "/private/catalog.json",
    ] {
        let wire = decoded(&platform_status(failure(vec![catalog(reason)]), &limits));
        assert!(wire.detail_items.is_empty());
    }
}

fn bounded_response() -> ManagementLimits {
    ManagementLimits {
        max_response_bytes: 4096,
        max_metadata_bytes: 4096,
        max_page_token_bytes: 4096,
        ..ManagementLimits::default()
    }
}

#[test]
fn output_compacts_spare_capacity_and_obeys_one_aggregate_retained_budget() {
    let limits = bounded_response();
    limits.validate().unwrap();
    let mut source = Vec::with_capacity(16);
    for _ in 0..16 {
        let mut receipt = mutation("apply");
        receipt.kind.reserve_exact(4096 - receipt.kind.len());
        receipt.fields = receipt
            .fields
            .into_iter()
            .map(|(mut key, mut value)| {
                if key != "deployment_id" {
                    value.reserve_exact(4096 - value.len());
                }
                key.reserve_exact(4096 - key.len());
                (key, value)
            })
            .collect();
        source.push(receipt);
    }
    let output = public_details(source, &limits, 128);
    assert!(!output.is_empty() && output.len() < 16);
    let mut retained = 128 + output.capacity() * std::mem::size_of::<proto::ErrorDetail>();
    for detail in &output {
        assert!(detail.kind.capacity() <= 64);
        retained += detail.kind.capacity() + detail.fields.capacity() * 128;
        for (key, value) in &detail.fields {
            assert!(key.capacity() <= 64 && value.capacity() <= 20);
            retained += key.capacity() + value.capacity();
        }
    }
    assert!(retained <= limits.max_response_bytes);
    let status = platform_status(failure(vec![mutation("apply"); 16]), &limits);
    assert!(status.details().len() <= limits.max_response_bytes.min(MAX_ENCODED_ERROR_BYTES));
    assert_eq!(decoded(&status).code, "unavailable");
}

#[test]
fn excessive_source_counts_and_capacity_take_a_bounded_fallback() {
    let limits = bounded_response();
    let mut sparse =
        Vec::with_capacity(limits.max_response_bytes / std::mem::size_of::<ErrorDetail>() + 1);
    sparse.push(mutation("apply"));
    assert!(public_details(sparse, &limits, 128).is_empty());
    assert!(public_details(vec![mutation("apply"); 17], &limits, 128).is_empty());
    let mut source = mutation("apply");
    source.kind = String::with_capacity(4097);
    source.kind.push_str("deployment-mutation");
    assert!(public_details(vec![source], &limits, 128).is_empty());
    let mut restricted = limits;
    restricted.auth.max_platform_error_fields = 4;
    assert!(public_details(vec![mutation("apply")], &restricted, 128).is_empty());
}
