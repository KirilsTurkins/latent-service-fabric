use super::super::{proto, response};
use serde_json::json;
use std::collections::HashMap;

const MAXIMUM: usize = 4 * 1024 * 1024;

fn success() -> proto::InvokeResponse {
    proto::InvokeResponse {
        activation_id: "known".to_owned(),
        revision_id: "revision".to_owned(),
        release_digest: format!("sha256:{}", "1".repeat(64)),
        route_generation: u64::MAX,
        result: Some(proto::invoke_response::Result::Success(proto::Success {
            payload: vec![0, 255, 10],
            media_type: "application/octet-stream".to_owned(),
            committed_state_version: Some("state-version".to_owned()),
            effect_ids: vec!["effect-1".to_owned()],
            metadata: HashMap::default(),
        })),
        consumption: Some(used()),
    }
}

fn used() -> proto::BudgetConsumption {
    proto::BudgetConsumption {
        cpu_fuel: u64::MAX,
        peak_memory_bytes: u64::MAX,
        wall_time_micros: u64::MAX,
        state_read_bytes: u64::MAX,
        state_write_bytes: u64::MAX,
        blob_read_bytes: u64::MAX,
        blob_write_bytes: u64::MAX,
        log_bytes: u64::MAX,
        child_calls: u32::MAX,
        outbound_requests: u32::MAX,
        effect_count: u32::MAX,
    }
}

#[test]
fn success_preserves_full_bytes_optional_receipt_fields_and_every_integer() {
    let result = response::invocation(success(), Some("known"), MAXIMUM)
        .ok()
        .unwrap();
    assert_eq!(result.exit_code(), 0);
    assert_eq!(result.data["activationId"], "known");
    assert_eq!(
        result.data["resolvedRevision"]["routeGeneration"],
        u64::MAX.to_string()
    );
    assert_eq!(
        result.data["payload"],
        json!({"encoding":"base64", "mediaType":"application/octet-stream", "data":"AP8K", "byteLength":"3"})
    );
    assert_eq!(result.data["committedStateVersion"], "state-version");
    assert_eq!(result.data["effectIds"], json!(["effect-1"]));
    for field in [
        "cpuFuel",
        "peakMemoryBytes",
        "wallTimeMicros",
        "stateReadBytes",
        "stateWriteBytes",
        "blobReadBytes",
        "blobWriteBytes",
        "logBytes",
    ] {
        assert_eq!(result.data["consumption"][field], u64::MAX.to_string());
    }
    for field in ["childCalls", "outboundRequests", "effectCount"] {
        assert_eq!(result.data["consumption"][field], u32::MAX);
    }
}

#[test]
fn declared_and_unresolved_platform_failures_keep_distinct_typed_outcomes() {
    let mut value = success();
    value.result = Some(proto::invoke_response::Result::DeclaredError(
        proto::DeclaredError {
            code: "invalid-value".to_owned(),
            message: "requested domain detail\nsecond line".to_owned(),
            payload: br#"{"case":"empty"}"#.to_vec(),
            media_type: "application/json".to_owned(),
            metadata: HashMap::default(),
        },
    ));
    let result = response::invocation(value, None, MAXIMUM).ok().unwrap();
    assert_eq!(result.exit_code(), 3);
    assert_eq!(result.data["declaredError"]["code"], "invalid-value");
    assert_eq!(
        result.data["declaredError"]["payload"]["data"],
        "eyJjYXNlIjoiZW1wdHkifQ=="
    );
    assert_eq!(result.data["consumption"]["cpuFuel"], u64::MAX.to_string());

    let value = proto::InvokeResponse {
        activation_id: "known".to_owned(),
        result: Some(proto::invoke_response::Result::PlatformFailure(
            proto::PlatformError {
                code: "state-conflict".to_owned(),
                message: "private stack-like remote diagnostic".to_owned(),
                retryable: true,
                detail_items: Vec::new(),
            },
        )),
        consumption: Some(used()),
        ..proto::InvokeResponse::default()
    };
    let result = response::invocation(value, Some("known"), MAXIMUM)
        .ok()
        .unwrap();
    assert_eq!(result.exit_code(), 4);
    assert_eq!(result.data["resolvedRevision"], serde_json::Value::Null);
    assert_eq!(result.data["terminalState"], "state_conflict");
}

#[test]
fn malformed_unknown_or_wrong_identity_responses_are_protocol_failures() {
    for kind in 0..7 {
        let mut value = success();
        match kind {
            0 => value.consumption = None,
            1 => value.revision_id.clear(),
            2 => value.result = None,
            3 => value.activation_id = "another".to_owned(),
            4 => {
                value.result = Some(proto::invoke_response::Result::PlatformFailure(
                    proto::PlatformError {
                        code: "future-unknown-code".to_owned(),
                        ..proto::PlatformError::default()
                    },
                ));
            }
            5 => {
                if let Some(proto::invoke_response::Result::Success(result)) = value.result.as_mut()
                {
                    result.metadata = (0..65).map(|n| (n.to_string(), String::new())).collect();
                }
            }
            _ => value.activation_id = "x".repeat(513),
        }
        assert!(response::invocation(value, Some("known"), MAXIMUM).is_err());
    }
    assert!(response::invocation(success(), None, 1).is_err());
}

#[test]
fn status_retains_nullable_active_fields_and_exact_terminal_diagnostics() {
    let active = proto::ActivationStatus {
        activation_id: "known".to_owned(),
        phase: "queued".to_owned(),
        last_updated_unix_millis: u64::MAX,
        ..proto::ActivationStatus::default()
    };
    let result = response::status(active, "known", MAXIMUM).ok().unwrap();
    assert_eq!(result.data["phase"], "queued");
    assert!(
        result.data["terminalState"].is_null()
            && result.data["terminalOutcome"].is_null()
            && result.data["finalConsumption"].is_null()
    );
    assert_eq!(result.data["lastUpdatedUnixMillis"], u64::MAX.to_string());
    let terminal = proto::ActivationStatus {
        activation_id: "known".to_owned(),
        phase: "running".to_owned(),
        terminal_state: Some("cancelled".to_owned()),
        last_updated_unix_millis: u64::MAX,
        terminal_at_unix_millis: Some(u64::MAX),
        final_consumption: Some(used()),
        terminal_outcome: Some(proto::activation_status::TerminalOutcome::PlatformFailure(
            proto::PlatformError {
                code: "cancelled".to_owned(),
                message: "private remote message".to_owned(),
                retryable: false,
                detail_items: Vec::new(),
            },
        )),
        metadata: HashMap::default(),
    };
    let result = response::status(terminal.clone(), "known", MAXIMUM)
        .ok()
        .unwrap();
    assert_eq!(
        result.exit_code(),
        0,
        "status reads are successful even when the retained activation failed"
    );
    assert_eq!(result.data["terminalState"], "cancelled");
    assert_eq!(result.data["terminalAtUnixMillis"], u64::MAX.to_string());
    assert!(!result.data.to_string().contains("private remote message"));
    assert!(response::status(terminal.clone(), "different", MAXIMUM).is_err());
    let mut malformed = terminal;
    malformed.final_consumption = None;
    assert!(response::status(malformed, "known", MAXIMUM).is_err());
}

#[test]
fn all_cancel_dispositions_and_terminal_spelling_survive_without_boolean_coercion() {
    for (disposition, state, name, exit) in [
        (1, None, "accepted", 0),
        (2, Some("deadline_exceeded"), "already_terminal", 0),
        (3, None, "not_found", 6),
    ] {
        let value = proto::CancelResponse {
            disposition,
            terminal_state: state.map(str::to_owned),
        };
        let result = response::cancellation(value, "known", MAXIMUM)
            .ok()
            .unwrap();
        assert_eq!(result.exit_code(), exit);
        assert_eq!(result.data["activationId"], "known");
        assert_eq!(result.data["disposition"], name);
        assert_eq!(result.data["terminalState"], json!(state));
    }
    for (disposition, state) in [
        (0, None),
        (99, None),
        (1, Some("completed")),
        (2, None),
        (2, Some("future-state")),
        (3, Some("cancelled")),
    ] {
        assert!(response::cancellation(
            proto::CancelResponse {
                disposition,
                terminal_state: state.map(str::to_owned)
            },
            "known",
            MAXIMUM
        )
        .is_err());
    }
}
