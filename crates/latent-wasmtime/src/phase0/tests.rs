use super::*;
use crate::config::Phase0InstanceAllocator;
use crate::values::{self, ValueCodecLimits};
use latent_core::{BudgetConsumption, DeclaredError};
use latent_executor::{ExecutionCleanup, GuestInterruptionKind, GuestTrap};

#[test]
fn profiles_explicit_bounded_allocator_and_cow_experiments() {
    let on_demand = Phase0WasmtimeConfig::default();
    let on_demand_factory =
        Phase0WasmtimeEngineFactory::new(on_demand.clone()).expect("default factory builds");
    assert!(!on_demand_factory.profile().pooling_allocator);
    assert!(on_demand_factory.profile().copy_on_write_images);
    assert_eq!(on_demand_factory.profile().id, BACKEND_ID);
    assert_eq!(
        on_demand_factory.profile().configuration["instance-allocation-strategy"],
        "on_demand"
    );

    let pooling = Phase0WasmtimeConfig {
        instance_allocator: Phase0InstanceAllocator::Pooling,
        copy_on_write_images: false,
        pooling_maximum_instances: 2,
        ..on_demand
    };
    let pooling_factory =
        Phase0WasmtimeEngineFactory::new(pooling).expect("bounded pooling factory builds");
    assert!(pooling_factory.profile().pooling_allocator);
    assert!(!pooling_factory.profile().copy_on_write_images);
    assert_eq!(
        pooling_factory.profile().configuration["pooling-linear-memory-keep-resident-bytes"],
        "0"
    );
}

#[test]
fn rejects_an_unbounded_pooling_experiment() {
    let config = Phase0WasmtimeConfig {
        instance_allocator: Phase0InstanceAllocator::Pooling,
        pooling_maximum_instances: 0,
        ..Phase0WasmtimeConfig::default()
    };
    assert!(Phase0WasmtimeEngineFactory::new(config).is_err());
}

#[test]
fn typed_echo_error_keeps_code_payload_and_media_type_out_of_success() {
    let error = adapter::echo_declared_error(
        "empty-message",
        "the echo message must not be empty",
        br#"{"error":"empty-message"}"#,
    );
    assert_eq!(error.code, "empty-message");
    assert_eq!(error.payload, br#"{"error":"empty-message"}"#);
    assert_eq!(error.media_type, ECHO_DOMAIN_ERROR_MEDIA_TYPE);
}

#[test]
fn legacy_input_preserves_text_and_bounds_the_escaped_parameter_buffer() {
    let text = "quote: \" and newline:\n and snowman: \u{2603}";
    let bytes = adapter::encode_input(text.as_bytes().to_vec(), ValueCodecLimits::default())
        .expect("valid UTF-8 becomes one positional parameter");
    assert_eq!(
        serde_json::from_slice::<[String; 1]>(&bytes).unwrap(),
        [text]
    );

    let limits = ValueCodecLimits {
        max_input_bytes: 6,
        ..ValueCodecLimits::default()
    };
    assert_eq!(
        adapter::encode_input(b"ab".to_vec(), limits).unwrap(),
        br#"["ab"]"#
    );
    // Both raw inputs fit; escaping the newline crosses the encoded ceiling.
    assert_eq!(
        adapter::encode_input(b"a\n".to_vec(), limits)
            .unwrap_err()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    let error = adapter::encode_input(vec![0xff], ValueCodecLimits::default()).unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::InvalidArgument);
    assert_eq!(error.message, "the Phase 0 echo input must be valid UTF-8");
}

fn consumption() -> BudgetConsumption {
    BudgetConsumption {
        cpu_fuel: 23,
        peak_memory_bytes: 4096,
        wall_time_micros: 17,
        log_bytes: 9,
        ..BudgetConsumption::default()
    }
}

fn returned(payload: &[u8]) -> GuestOutcome {
    GuestOutcome::Returned {
        output: payload.to_vec(),
        output_media_type: values::MEDIA_TYPE.to_owned(),
        consumption: consumption(),
    }
}

fn declared(payload: &[u8]) -> GuestOutcome {
    GuestOutcome::DeclaredError {
        error: DeclaredError {
            code: "declared-error".to_owned(),
            message: "component returned a declared error".to_owned(),
            payload: payload.to_vec(),
            media_type: values::MEDIA_TYPE.to_owned(),
            metadata: Metadata::new(),
        },
        consumption: consumption(),
    }
}

#[test]
fn dynamic_results_preserve_legacy_success_domain_errors_and_consumption() {
    let limits = ValueCodecLimits::default();
    assert_eq!(
        adapter::outcome(returned(br#"[{"ok":"line\nquote\""}]"#), limits),
        GuestOutcome::Returned {
            output: b"line\nquote\"".to_vec(),
            output_media_type: ECHO_SUCCESS_MEDIA_TYPE.to_owned(),
            consumption: consumption(),
        }
    );
    for (code, message, payload, frame) in [
        (
            "empty-message",
            "the echo message must not be empty",
            br#"{"error":"empty-message"}"#.as_slice(),
            br#"[{"err":{"case":"empty-message"}}]"#.as_slice(),
        ),
        (
            "message-too-large",
            "the echo message exceeds the declared byte limit",
            br#"{"error":"message-too-large"}"#.as_slice(),
            br#"[{"err":{"case":"message-too-large"}}]"#.as_slice(),
        ),
    ] {
        assert_eq!(
            adapter::outcome(declared(frame), limits),
            GuestOutcome::DeclaredError {
                error: adapter::echo_declared_error(code, message, payload),
                consumption: consumption(),
            }
        );
    }
}

#[test]
fn wrong_result_framing_never_becomes_success_or_overrides_cleanup() {
    let limits = ValueCodecLimits::default();
    for payload in [
        b"[]".as_slice(),
        br#"[{"ok":"a"},{"ok":"b"}]"#.as_slice(),
        br#"[{"ok":"a","ok":"b"}]"#.as_slice(),
        br#"[{"ok":"a","err":"empty-message"}]"#.as_slice(),
        br#"[{"ok":3}]"#.as_slice(),
        br#"[{"err":"empty-message"}]"#.as_slice(),
    ] {
        let report = ExecutionReport::quarantine(Ok(returned(payload)), "retain original proof");
        let mapped = adapter::report(report, limits);
        assert_adapter_trap(mapped.outcome.unwrap(), "invalid-component-result");
        assert_eq!(
            mapped.cleanup,
            ExecutionCleanup::Quarantine {
                reason: "retain original proof".to_owned(),
            }
        );
    }
    for payload in [
        br#"[{"err":{"case":"unknown-error"}}]"#.as_slice(),
        br#"[{"err":{"case":"empty-message","value":null}}]"#.as_slice(),
        br#"[{"err":{"case":"empty-message","extra":true}}]"#.as_slice(),
        br#"[{"err":{"case":"empty-message","case":"message-too-large"}}]"#.as_slice(),
        br#"[{"err":"empty-message"}]"#.as_slice(),
        br#"[{"ok":"success"}]"#.as_slice(),
    ] {
        assert_adapter_trap(
            adapter::outcome(declared(payload), limits),
            "invalid-component-result",
        );
    }
    assert_adapter_trap(
        adapter::outcome(
            returned(br#"[{"ok":"hello"}]"#),
            ValueCodecLimits {
                max_output_bytes: 4,
                ..limits
            },
        ),
        "result-limit-exceeded",
    );
}

fn assert_adapter_trap(outcome: GuestOutcome, expected_code: &str) {
    let GuestOutcome::Trapped {
        trap,
        consumption: actual,
    } = outcome
    else {
        panic!("post-execution adaptation failure must remain a guest outcome");
    };
    assert_eq!(trap.code, expected_code);
    assert_eq!(actual, consumption());
    assert!(trap.message.len() <= 512);
    assert!(trap.guest_backtrace.is_empty());
}

#[test]
fn traps_interruptions_and_platform_failures_preserve_shared_backend_reports() {
    let limits = ValueCodecLimits::default();
    let trap = GuestOutcome::Trapped {
        trap: GuestTrap {
            code: "wasm-trap".to_owned(),
            message: "unreachable".to_owned(),
            guest_backtrace: Vec::new(),
            metadata: Metadata::new(),
        },
        consumption: consumption(),
    };
    let stopped = GuestOutcome::Interrupted {
        kind: GuestInterruptionKind::Cancelled,
        reason: "cancelled".to_owned(),
        consumption: consumption(),
    };
    for outcome in [trap, stopped] {
        let report = ExecutionReport::quarantine(Ok(outcome), "cleanup incomplete");
        assert_eq!(adapter::report(report.clone(), limits), report);
    }
    let report = ExecutionReport::reusable(Err(platform_error(
        PlatformErrorCode::Unavailable,
        "instance capacity is full",
        true,
    )));
    assert_eq!(adapter::report(report.clone(), limits), report);
}
