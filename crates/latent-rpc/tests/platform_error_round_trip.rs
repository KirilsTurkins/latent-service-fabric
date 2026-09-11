use std::collections::BTreeMap;

use latent_core::{ErrorDetail, PlatformError, PlatformErrorCode};
use latent_rpc::platform_error::TryIntoDomainPlatformError;
use latent_rpc::{control::v1 as control, invocation::v1 as invocation};
use prost::Message;

const PLATFORM_ERROR_CODES: &[(PlatformErrorCode, &str)] = &[
    (PlatformErrorCode::Unavailable, "unavailable"),
    (PlatformErrorCode::DeadlineExceeded, "deadline-exceeded"),
    (PlatformErrorCode::Cancelled, "cancelled"),
    (PlatformErrorCode::ResourceExhausted, "resource-exhausted"),
    (PlatformErrorCode::PermissionDenied, "permission-denied"),
    (PlatformErrorCode::Unauthenticated, "unauthenticated"),
    (PlatformErrorCode::InvalidArgument, "invalid-argument"),
    (PlatformErrorCode::NotFound, "not-found"),
    (PlatformErrorCode::AlreadyExists, "already-exists"),
    (
        PlatformErrorCode::IncompatibleContract,
        "incompatible-contract",
    ),
    (PlatformErrorCode::StateConflict, "state-conflict"),
    (PlatformErrorCode::DependencyFailed, "dependency-failed"),
    (PlatformErrorCode::GuestTrap, "guest-trap"),
    (PlatformErrorCode::CorruptArtifact, "corrupt-artifact"),
    (PlatformErrorCode::RouteUnavailable, "route-unavailable"),
    (PlatformErrorCode::AdmissionRejected, "admission-rejected"),
    (PlatformErrorCode::Internal, "internal"),
];

#[test]
fn every_domain_code_has_a_stable_invocation_wire_mapping_and_round_trips() {
    for (index, &(code, expected_wire_code)) in PLATFORM_ERROR_CODES.iter().enumerate() {
        let domain = PlatformError {
            code,
            message: format!("platform failure {index}"),
            retryable: index % 2 == 0,
            details: vec![
                ErrorDetail {
                    kind: "placement.failure".to_owned(),
                    fields: BTreeMap::from([
                        ("node".to_owned(), format!("node-{index}")),
                        ("zone".to_owned(), "zone-a".to_owned()),
                    ]),
                },
                ErrorDetail {
                    kind: "policy.decision".to_owned(),
                    fields: BTreeMap::from([
                        ("policy".to_owned(), "tenant-budget".to_owned()),
                        ("rule".to_owned(), "deny-overload".to_owned()),
                    ]),
                },
            ],
        };

        let wire = invocation::PlatformError::from(domain.clone());
        assert_eq!(wire.code, expected_wire_code);

        let encoded = Message::encode_to_vec(&wire);
        let decoded =
            invocation::PlatformError::decode(encoded.as_slice()).expect("decode invocation error");
        let reconstructed = decoded
            .try_into_domain()
            .expect("known invocation platform code");

        assert_eq!(reconstructed, domain);
    }
}

#[test]
fn empty_details_round_trip_through_both_generated_platform_error_types() {
    let domain = PlatformError {
        code: PlatformErrorCode::Unavailable,
        message: "temporarily unavailable".to_owned(),
        retryable: true,
        details: Vec::new(),
    };

    let invocation_wire = invocation::PlatformError::from(domain.clone());
    let invocation_bytes = Message::encode_to_vec(&invocation_wire);
    let invocation_decoded = invocation::PlatformError::decode(invocation_bytes.as_slice())
        .expect("decode invocation platform error");
    assert_eq!(
        invocation_decoded
            .try_into_domain()
            .expect("known invocation platform code"),
        domain
    );

    let control_wire = control::PlatformError::from(domain.clone());
    let control_bytes = Message::encode_to_vec(&control_wire);
    let control_decoded = control::PlatformError::decode(control_bytes.as_slice())
        .expect("decode control platform error");
    assert_eq!(
        control_decoded
            .try_into_domain()
            .expect("known control platform code"),
        domain
    );
}

#[test]
fn configured_boundary_length_diagnostics_survive_prost_exactly() {
    const MAX_MESSAGE_BYTES: usize = 512;
    const MAX_DETAILS: usize = 8;
    const MAX_FIELDS: usize = 16;
    const MAX_KIND_AND_FIELD_NAME_BYTES: usize = 64;
    const MAX_FIELD_VALUE_BYTES: usize = 256;

    let details = (0..MAX_DETAILS)
        .map(|detail_index| ErrorDetail {
            kind: padded(
                &format!("detail-{detail_index}-"),
                MAX_KIND_AND_FIELD_NAME_BYTES,
            ),
            fields: (0..MAX_FIELDS)
                .map(|field_index| {
                    (
                        padded(
                            &format!("field-{field_index}-"),
                            MAX_KIND_AND_FIELD_NAME_BYTES,
                        ),
                        padded(
                            &format!("value-{detail_index}-{field_index}-"),
                            MAX_FIELD_VALUE_BYTES,
                        ),
                    )
                })
                .collect(),
        })
        .collect();
    let domain = PlatformError {
        code: PlatformErrorCode::ResourceExhausted,
        message: "m".repeat(MAX_MESSAGE_BYTES),
        retryable: false,
        details,
    };

    let invocation_wire = invocation::PlatformError::from(&domain);
    let invocation_bytes = Message::encode_to_vec(&invocation_wire);
    let invocation_decoded = invocation::PlatformError::decode(invocation_bytes.as_slice())
        .expect("decode boundary invocation platform error");
    assert_eq!(
        invocation_decoded
            .try_into_domain()
            .expect("known invocation platform code"),
        domain
    );

    let control_wire = control::PlatformError::from(&domain);
    let control_bytes = Message::encode_to_vec(&control_wire);
    let control_decoded = control::PlatformError::decode(control_bytes.as_slice())
        .expect("decode boundary control platform error");
    assert_eq!(
        control_decoded
            .try_into_domain()
            .expect("known control platform code"),
        domain
    );
}

#[test]
fn unknown_wire_codes_are_rejected_without_coercion() {
    let wire = invocation::PlatformError {
        code: "future-platform-code".to_owned(),
        message: "newer sender classification".to_owned(),
        retryable: true,
        detail_items: vec![invocation::ErrorDetail {
            kind: "future.detail".to_owned(),
            fields: [("key".to_owned(), "value".to_owned())]
                .into_iter()
                .collect(),
        }],
    };
    let encoded = Message::encode_to_vec(&wire);
    let decoded =
        invocation::PlatformError::decode(encoded.as_slice()).expect("decode unknown code message");
    let error = decoded
        .try_into_domain()
        .expect_err("unknown code must not be coerced");

    assert_eq!(error.code(), "future-platform-code");
    assert_eq!(
        error.to_string(),
        "unknown platform error code: future-platform-code"
    );
}

fn padded(prefix: &str, length: usize) -> String {
    assert!(prefix.len() <= length);
    format!("{prefix}{}", "x".repeat(length - prefix.len()))
}
