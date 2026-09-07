use latent_core::{ActivationId, Metadata, ReleaseDigest, RevisionId, RouteGeneration};
use prost::Message;

use super::*;

mod bounds;

fn consumption() -> BudgetConsumption {
    BudgetConsumption {
        cpu_fuel: 1,
        peak_memory_bytes: 2,
        wall_time_micros: 3,
        child_calls: 4,
        outbound_requests: 5,
        state_read_bytes: 6,
        state_write_bytes: 7,
        blob_read_bytes: 8,
        blob_write_bytes: 9,
        log_bytes: 10,
        effect_count: 11,
    }
}

fn success() -> ActivationOutcome {
    ActivationOutcome::Succeeded(ActivationSuccess {
        output: b"binary\0payload".to_vec(),
        output_media_type: "application/octet-stream".into(),
        consumption: consumption(),
        committed_state_version: Some("state-3".into()),
        effect_ids: vec!["effect-1".into(), "effect-2".into()],
        metadata: Metadata::from([("result".into(), "preserved".into())]),
    })
}

fn declared() -> ActivationOutcome {
    ActivationOutcome::DeclaredError {
        error: DeclaredError {
            code: "business-rejection".into(),
            message: "component message".into(),
            payload: b"opaque\0declared".to_vec(),
            media_type: "application/octet-stream".into(),
            metadata: Metadata::from([("detail".into(), "kept".into())]),
        },
        consumption: consumption(),
    }
}

fn failure(code: PlatformErrorCode) -> ActivationOutcome {
    ActivationOutcome::Failed {
        terminal_state: terminal_state_for_platform_error(code),
        error: PlatformError {
            code,
            message: "private /srv/key credential=secret".into(),
            retryable: true,
            details: vec![ErrorDetail {
                kind: "retry".into(),
                fields: Metadata::from([("retry_after_millis".into(), "7".into())]),
            }],
        },
        consumption: consumption(),
    }
}

fn response(outcome: ActivationOutcome) -> InvocationResponse {
    InvocationResponse {
        receipt: InvocationReceipt {
            activation_id: ActivationId("activation-1".into()),
            resolved_revision: Some(InvocationRevision {
                revision_id: RevisionId("revision-1".into()),
                release_digest: ReleaseDigest("sha256:1234".into()),
                route_generation: RouteGeneration(0),
            }),
        },
        outcome,
    }
}

fn status(outcome: &ActivationOutcome) -> ActivationStatus {
    let state = match outcome {
        ActivationOutcome::Succeeded(_) | ActivationOutcome::DeclaredError { .. } => {
            ActivationTerminalState::Completed
        }
        ActivationOutcome::Failed { terminal_state, .. } => *terminal_state,
    };
    ActivationStatus {
        activation_id: ActivationId("activation-1".into()),
        phase: ActivationPhase::Running,
        terminal_state: Some(state),
        terminal_outcome: Some(outcome.retained_terminal_outcome()),
        final_consumption: Some(consumption()),
        last_updated_unix_millis: 123,
        terminal_at_unix_millis: Some(123),
        metadata: Metadata::from([("retained".into(), "yes".into())]),
    }
}

#[test]
fn all_outcomes_preserve_fields_and_generated_wire_encoding() {
    for outcome in [
        success(),
        declared(),
        failure(PlatformErrorCode::DependencyFailed),
    ] {
        let response = response(outcome.clone());
        let wire = invocation_response_to_proto(&response).unwrap();
        let decoded = proto::InvokeResponse::decode(wire.encode_to_vec().as_slice()).unwrap();
        assert_eq!(invocation_response_from_proto(decoded).unwrap(), response);
        let status = status(&outcome);
        let wire = activation_status_to_proto(&status).unwrap();
        let decoded = proto::ActivationStatus::decode(wire.encode_to_vec().as_slice()).unwrap();
        assert_eq!(activation_status_from_proto(decoded).unwrap(), status);
    }
}

#[test]
fn absent_pin_is_exactly_empty_empty_zero_for_platform_failure() {
    let mut value = response(failure(PlatformErrorCode::RouteUnavailable));
    value.receipt.resolved_revision = None;
    let wire = invocation_response_to_proto(&value).unwrap();
    assert_eq!(
        (
            &*wire.revision_id,
            &*wire.release_digest,
            wire.route_generation
        ),
        ("", "", 0)
    );
    assert_eq!(invocation_response_from_proto(wire.clone()).unwrap(), value);

    // Explicit proto3 default scalar encodings are indistinguishable after decode.
    let mut bytes = wire.encode_to_vec();
    bytes.extend_from_slice(&[0x12, 0, 0x1a, 0, 0x20, 0]);
    assert_eq!(
        invocation_response_from_proto(proto::InvokeResponse::decode(bytes.as_slice()).unwrap())
            .unwrap(),
        value
    );
    for (revision, release, generation) in [("", "release", 0), ("revision", "", 0), ("", "", 1)] {
        let mut malformed = wire.clone();
        malformed.revision_id = revision.into();
        malformed.release_digest = release.into();
        malformed.route_generation = generation;
        assert!(invocation_response_from_proto(malformed).is_err());
    }
    for outcome in [success(), declared()] {
        let mut value = response(outcome);
        let mut encoded = invocation_response_to_proto(&value).unwrap();
        value.receipt.resolved_revision = None;
        assert!(invocation_response_to_proto(&value).is_err());
        encoded.revision_id.clear();
        encoded.release_digest.clear();
        encoded.route_generation = 0;
        assert!(invocation_response_from_proto(encoded).is_err());
    }
}

#[test]
fn platform_terminal_inference_matches_the_current_lifecycle_for_every_code() {
    use ActivationTerminalState as T;
    use PlatformErrorCode as C;
    for (code, terminal) in [
        (C::Unavailable, T::DependencyFailed),
        (C::RouteUnavailable, T::DependencyFailed),
        (C::DependencyFailed, T::DependencyFailed),
        (C::DeadlineExceeded, T::DeadlineExceeded),
        (C::Cancelled, T::Cancelled),
        (C::ResourceExhausted, T::ResourceExhausted),
        (C::GuestTrap, T::GuestTrap),
        (C::StateConflict, T::StateConflict),
        (C::PermissionDenied, T::Rejected),
        (C::Unauthenticated, T::Rejected),
        (C::InvalidArgument, T::Rejected),
        (C::NotFound, T::Rejected),
        (C::AlreadyExists, T::Rejected),
        (C::IncompatibleContract, T::Rejected),
        (C::CorruptArtifact, T::Rejected),
        (C::AdmissionRejected, T::Rejected),
        (C::Internal, T::PlatformFailed),
    ] {
        let value = response(ActivationOutcome::Failed {
            terminal_state: terminal,
            error: PlatformError {
                code,
                message: "exact".into(),
                retryable: true,
                details: vec![],
            },
            consumption: consumption(),
        });
        assert_eq!(
            invocation_response_from_proto(invocation_response_to_proto(&value).unwrap()).unwrap(),
            value
        );
    }
    let mut impossible = response(failure(C::RouteUnavailable));
    if let ActivationOutcome::Failed { terminal_state, .. } = &mut impossible.outcome {
        *terminal_state = T::Rejected;
    }
    assert!(invocation_response_to_proto(&impossible).is_err());
}

#[test]
fn contradictory_status_presence_and_category_are_rejected() {
    let valid = status(&success());
    for field in 0..4 {
        let mut malformed = valid.clone();
        match field {
            0 => malformed.terminal_state = None,
            1 => malformed.terminal_outcome = None,
            2 => malformed.final_consumption = None,
            _ => malformed.terminal_at_unix_millis = None,
        }
        assert!(activation_status_to_proto(&malformed).is_err());
    }
    let mut malformed = activation_status_to_proto(&valid).unwrap();
    malformed.terminal_state = Some("cancelled".into());
    assert!(activation_status_from_proto(malformed).is_err());
    let mut explicit = status(&failure(PlatformErrorCode::Unavailable));
    explicit.terminal_state = Some(ActivationTerminalState::Rejected);
    // Unlike InvokeResponse, status carries its own explicit terminal state.
    assert_eq!(
        activation_status_from_proto(activation_status_to_proto(&explicit).unwrap()).unwrap(),
        explicit
    );
}

#[test]
fn cancellation_dispositions_preserve_terminal_state_and_reject_contradictions() {
    for value in [
        CancelDisposition::Accepted,
        CancelDisposition::NotFound,
        CancelDisposition::AlreadyTerminal(ActivationTerminalState::Completed),
    ] {
        assert_eq!(
            cancel_disposition_from_proto(cancel_disposition_to_proto(value)).unwrap(),
            value
        );
    }
    for (disposition, terminal_state) in [
        (0, None),
        (1, Some("completed".into())),
        (2, None),
        (3, Some("cancelled".into())),
        (42, None),
    ] {
        assert!(cancel_disposition_from_proto(proto::CancelResponse {
            disposition,
            terminal_state
        })
        .is_err());
    }
}

#[test]
fn trusted_request_round_trip_preserves_optional_identity_and_every_budget_dimension() {
    let wire = proto::InvokeRequest {
        activation_id: Some(String::new()),
        parent_activation_id: Some("opaque-parent".into()),
        root_activation_id: Some("opaque-root".into()),
        target: Some(proto::InvocationTarget {
            tenant: "tenant".into(),
            service: "service".into(),
            contract: "contract".into(),
            function: "function".into(),
            route: Some("route".into()),
        }),
        payload: b"payload".to_vec(),
        media_type: "text/plain".into(),
        deadline_unix_millis: Some(999),
        priority: 255,
        idempotency_key: Some("opaque".into()),
        budget: Some(proto::ResourceBudget {
            cpu_fuel: 1,
            memory_bytes: 2,
            child_calls: 3,
            outbound_requests: 4,
            state_read_bytes: 5,
            state_write_bytes: 6,
            blob_read_bytes: 7,
            blob_write_bytes: 8,
            log_bytes: 9,
            effect_count: 10,
            wall_time_limit_millis: Some(11),
        }),
        metadata: [("key".into(), "value".into())].into_iter().collect(),
    };
    let domain = invocation_request_from_proto(wire.clone()).unwrap();
    assert_eq!(invocation_request_to_proto(&domain), wire);
    assert_eq!(
        domain.requested_activation_id,
        Some(ActivationId(String::new()))
    );
    let mut absent = wire;
    absent.activation_id = None;
    assert_eq!(
        invocation_request_from_proto(absent)
            .unwrap()
            .requested_activation_id,
        None
    );
}

#[test]
fn trusted_platform_error_round_trip_preserves_distinct_detail_items_and_unknown_fields() {
    let error = PlatformError {
        code: PlatformErrorCode::DependencyFailed,
        message: "exact private message".into(),
        retryable: true,
        details: vec![
            ErrorDetail {
                kind: "future.kind".into(),
                fields: Metadata::from([
                    ("shared".into(), "first".into()),
                    ("opaque".into(), "line1\nline2".into()),
                ]),
            },
            ErrorDetail {
                kind: "future.kind".into(),
                fields: Metadata::from([("shared".into(), "second".into())]),
            },
        ],
    };
    let wire = platform_error_to_proto(&error);
    assert_eq!(wire.detail_items.len(), 2);
    assert_eq!(platform_error_from_proto(wire).unwrap(), error);
}
