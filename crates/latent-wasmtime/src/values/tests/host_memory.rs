//! Codec/ownership controls use the actual original ledger and codec. The
//! type-only fixture supplies composite Type identities; it executes no guest.
use super::*;
use latent_core::{
    ActivationBudget, BudgetProfile, ClockSample, EffectiveActivationBudget, ResourceBudget,
};
use std::time::Instant;

pub(super) fn original_budget() -> ActivationBudget {
    let limits = ResourceBudget {
        cpu_fuel: 1_000_000_000,
        memory_bytes: 64 * 1024 * 1024,
        wall_time_limit_millis: Some(120_000),
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 0,
        effect_count: 0,
    };
    let grant = EffectiveActivationBudget::admit_profile_at(
        BudgetProfile::Phase3,
        &limits,
        &limits,
        &limits,
        None,
        ClockSample::new(1000, Instant::now()),
    )
    .unwrap();
    ActivationBudget::with_profile(grant, BudgetProfile::Phase3).unwrap()
}
fn peak(budget: &ActivationBudget) -> u64 {
    budget.snapshot_at(Instant::now()).peak_memory_bytes
}

#[test]
fn host_codec_input_uses_original_memory_and_drops_values_before_refund() {
    let budget = original_budget();
    let json = br#"["ordinary\u0000text"]"#;
    let values = decode_params_accounted(
        &[Type::String],
        json,
        MEDIA_TYPE,
        ValueCodecLimits::default(),
        &budget,
    )
    .unwrap();
    assert!(matches!(&values.as_slice()[0], Val::String(s) if s == "ordinary\0text"));
    assert!(budget.host_memory_bytes() > 0);
    assert!(peak(&budget) < 16 * 1024); // payload-scaled; never maxDecoded16MiB
    let occupied = budget.host_memory_bytes();
    assert!(budget
        .reserve_runtime_memory(budget.granted().memory_bytes - occupied + 1)
        .is_err());
    drop(values);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}

#[test]
fn host_codec_original_refusal_cannot_retry_the_legacy_allocator() {
    let budget = original_budget();
    let held = budget
        .reserve_host_memory(budget.granted().memory_bytes - 64)
        .unwrap();
    let result = decode_params_accounted(
        &[Type::String],
        br#"["not-allocated"]"#,
        MEDIA_TYPE,
        ValueCodecLimits::default(),
        &budget,
    );
    let error = match result {
        Err(error) => error,
        Ok(_) => panic!("must refuse before parser allocation"),
    };
    assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
    assert_eq!(
        budget.host_memory_bytes(),
        budget.granted().memory_bytes - 64
    );
    assert_eq!(budget.outstanding_reservations(), 1);
    drop(held);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[test]
fn host_codec_tiny_dynamic_string_and_declared_result_preserve_normal_64mib_profile() {
    for (signature, json) in [
        (Type::String, r#"["tiny"]"#),
        (types()["record"].clone(), r#"[{"name":"tiny","count":7}]"#),
        (types()["result"].clone(), r#"[{"ok":"tiny"}]"#),
        (types()["result"].clone(), r#"[{"err":{"case":"empty"}}]"#),
    ] {
        let budget = original_budget();
        budget
            .reserve_runtime_memory(16 * 1024 * 1024)
            .unwrap()
            .confirm();
        let limits = ValueCodecLimits::default();
        let signature = [signature];
        let plan = validate_signature(&signature, limits, 128 * 1024).unwrap();
        let bound = if plan.has_dynamic_values {
            plan.maximum_lift_bytes
        } else {
            plan.static_lift_bytes
        };
        assert!(bound < 1024 * 1024);
        let mut output = OwnedValues::output(1, bound, &budget).unwrap();
        assert_eq!(budget.host_memory_bytes(), bound as u64);
        assert!(peak(&budget) < 16 * 1024 * 1024 + 4096);
        output.begin_lift();
        // This control isolates codec/owner transfer, not Wasmtime execution.
        // The separate actual malformed-lift case exercises the real Func path.
        output.as_mut_slice()[0] = decode(&signature, json).remove(0);
        output.finish_lift(true).unwrap();
        assert!(budget.host_memory_bytes() < 4096);
        let encoded =
            encode_result_accounted(&signature, output.as_slice(), limits, &budget).unwrap();
        assert!(peak(&budget) < 16 * 1024 * 1024 + 16 * 1024);
        let bytes = match encoded {
            EncodedResult::Returned(bytes) => bytes,
            EncodedResult::DeclaredError(error) => {
                assert_eq!(error.code, "declared-error");
                error.payload
            }
        };
        assert_eq!(bytes.as_ref(), json.as_bytes());
        let clone = bytes.clone();
        let wire = bytes.into_bytes();
        let pointer = wire.as_ptr();
        assert_eq!(clone.as_ptr(), pointer);
        drop(output);
        assert!(budget.host_memory_bytes() > 0);
        drop(clone);
        assert!(budget.host_memory_bytes() > 0);
        drop(wire);
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(budget.outstanding_reservations(), 0);
    }
}

#[test]
fn host_codec_failed_and_abandoned_lifts_keep_conservative_capacity_attribution() {
    for finish in [false, true] {
        let budget = original_budget();
        let bound = validate_signature(&[Type::String], ValueCodecLimits::default(), 128 * 1024)
            .unwrap()
            .maximum_lift_bytes;
        let mut output = OwnedValues::output(1, bound, &budget).unwrap();
        output.begin_lift();
        // Native lifting may destroy an unpublished partial tree before it can
        // be inspected. Treat that branch conservatively, never as zero cost.
        if finish {
            output.finish_lift(false).unwrap();
        } else {
            assert_eq!(budget.host_memory_bytes(), bound as u64);
        }
        drop(output);
        assert_eq!(peak(&budget), bound as u64);
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(budget.outstanding_reservations(), 0);
    }
}

#[test]
fn host_codec_rejection_oracle_preserves_original_typed_error_precedence() {
    let record = types()["record"].clone();
    for (signature, json) in [
        (Type::String, r#"[false]"#),
        (record.clone(), r#"[{"name":"x"}]"#),
        (record, r#"[{"count":7,"name":"x","name":"x"}]"#),
    ] {
        let budget = original_budget();
        let limits = ValueCodecLimits::default();
        let old =
            decode_params(&[signature.clone()], json.as_bytes(), MEDIA_TYPE, limits).unwrap_err();
        let new = match decode_params_accounted(
            &[signature],
            json.as_bytes(),
            MEDIA_TYPE,
            limits,
            &budget,
        ) {
            Err(error) => error,
            Ok(_) => panic!("invalid input must retain original rejection"),
        };
        assert_eq!(new, old);
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(budget.outstanding_reservations(), 0);
    }
}

#[test]
fn host_codec_encoder_refuses_original_memory_without_losing_live_values() {
    let budget = original_budget();
    let mut output = OwnedValues::output(1, 4096, &budget).unwrap();
    output.begin_lift();
    output.as_mut_slice()[0] = Val::String("still-owned".into());
    output.finish_lift(true).unwrap();
    let original = budget.host_memory_bytes();
    let held = budget
        .reserve_host_memory(budget.granted().memory_bytes - original)
        .unwrap();
    let error = match encode_result_accounted(
        &[Type::String],
        output.as_slice(),
        ValueCodecLimits::default(),
        &budget,
    ) {
        Err(error) => error,
        Ok(_) => panic!("encoder must refuse original memory"),
    };
    assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
    assert!(error
        .details
        .iter()
        .any(|detail| detail.fields.get("dimension").map(String::as_str) == Some("memory-bytes")));
    assert_eq!(budget.host_memory_bytes(), budget.granted().memory_bytes);
    assert!(matches!(&output.as_slice()[0], Val::String(value) if value == "still-owned"));
    drop(held);
    drop(output);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}

#[tokio::test]
async fn host_codec_actual_malformed_string_lift_keeps_the_original_envelope() {
    let budget = original_budget();
    let mut config = Config::new();
    config.wasm_component_model(true);
    config.wasm_component_model_async(true);
    config.concurrency_support(true);
    let engine = Engine::new(&config).unwrap();
    let component = Component::new(
        &engine,
        include_bytes!("../host-memory-malformed-string.wasm"),
    )
    .unwrap();
    let linker = wasmtime::component::Linker::<()>::new(&engine);
    let mut store = wasmtime::Store::new(&engine, ());
    store.set_hostcall_fuel(128 * 1024);
    let instance = linker
        .instantiate_async(&mut store, &component)
        .await
        .unwrap();
    let function = instance.get_func(&mut store, "run").unwrap();
    let bound = validate_signature(&[Type::String], ValueCodecLimits::default(), 128 * 1024)
        .unwrap()
        .maximum_lift_bytes;
    let mut output = OwnedValues::output(1, bound, &budget).unwrap();
    output.begin_lift();
    let result = function
        .call_async(&mut store, &[], output.as_mut_slice())
        .await;
    assert!(result.is_err()); // invalid UTF-8 never becomes an invented result
    output.finish_lift(false).unwrap();
    assert_eq!(peak(&budget), bound as u64);
    drop(result);
    drop(store);
    drop(output);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}

#[tokio::test]
async fn host_codec_actual_pending_call_cancellation_keeps_envelope_until_native_drop() {
    use std::{
        future::Future,
        sync::{
            atomic::{AtomicBool, Ordering},
            Arc,
        },
        task::{Context, Wake, Waker},
    };
    struct Noop;
    impl Wake for Noop {
        fn wake(self: Arc<Self>) {}
    }
    let budget = original_budget();
    let mut config = Config::new();
    config.wasm_component_model(true);
    config.wasm_component_model_async(true);
    config.concurrency_support(true);
    let engine = Engine::new(&config).unwrap();
    let component = Component::new(
        &engine,
        include_bytes!("../host-memory-pending-string.wasm"),
    )
    .unwrap();
    let mut linker = wasmtime::component::Linker::<()>::new(&engine);
    let entered = Arc::new(AtomicBool::new(false));
    let observed = entered.clone();
    linker
        .root()
        .func_wrap_async("wait", move |_, (): ()| {
            observed.store(true, Ordering::SeqCst);
            Box::new(std::future::pending::<wasmtime::Result<()>>())
        })
        .unwrap();
    let mut store = wasmtime::Store::new(&engine, ());
    store.set_hostcall_fuel(128 * 1024);
    let instance = linker
        .instantiate_async(&mut store, &component)
        .await
        .unwrap();
    let function = instance.get_func(&mut store, "run").unwrap();
    let bound = validate_signature(&[Type::String], ValueCodecLimits::default(), 128 * 1024)
        .unwrap()
        .maximum_lift_bytes;
    let mut output = OwnedValues::output(1, bound, &budget).unwrap();
    output.begin_lift();
    let mut call = Box::pin(function.call_async(&mut store, &[], output.as_mut_slice()));
    let waker = Waker::from(Arc::new(Noop));
    assert!(call
        .as_mut()
        .poll(&mut Context::from_waker(&waker))
        .is_pending());
    assert!(entered.load(Ordering::SeqCst));
    assert_eq!(budget.host_memory_bytes(), bound as u64);
    drop(call); // actual suspended native future is destroyed before buffer owner
    assert_eq!(budget.host_memory_bytes(), bound as u64);
    drop(store);
    drop(output);
    assert_eq!(peak(&budget), bound as u64); // conservative, never a zero-cost claim
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}

#[test]
fn host_codec_scalar_and_numeric_stack_formatting_keep_original_bytes_and_small_peak() {
    let budget = original_budget();
    for (signature, value, expected) in [
        (Type::U32, Val::U32(7), "[7]"),
        (Type::U64, Val::U64(u64::MAX), "[\"18446744073709551615\"]"),
        (Type::S64, Val::S64(i64::MIN), "[\"-9223372036854775808\"]"),
        (Type::Float32, Val::Float32(f32::NEG_INFINITY), "[\"-inf\"]"),
        (Type::Float64, Val::Float64(f64::NAN), "[\"nan\"]"),
    ] {
        let signature = [signature];
        let plan = validate_signature(&signature, ValueCodecLimits::default(), 128 * 1024).unwrap();
        assert!(!plan.has_dynamic_values);
        let mut output = OwnedValues::output(1, plan.static_lift_bytes, &budget).unwrap();
        output.begin_lift();
        output.as_mut_slice()[0] = value;
        output.finish_lift(true).unwrap();
        let encoded = encode_result_accounted(
            &signature,
            output.as_slice(),
            ValueCodecLimits::default(),
            &budget,
        )
        .unwrap();
        let EncodedResult::Returned(encoded) = encoded else {
            panic!("scalar is a success")
        };
        assert_eq!(encoded.as_ref(), expected.as_bytes());
        assert!(peak(&budget) < 4096);
        drop(encoded);
        drop(output);
        assert_eq!(budget.host_memory_bytes(), 0);
    }
    // Finite extremal/subnormal f64 formatting fits the fixed stack buffer and
    // matches the original Rust Display representation used by the codec.
    for value in [
        f64::MAX,
        f64::MIN,
        f64::MIN_POSITIVE,
        f64::from_bits(1),
        -0.0,
    ] {
        let encoded = encode_result_accounted(
            &[Type::Float64],
            &[Val::Float64(value)],
            ValueCodecLimits::default(),
            &budget,
        )
        .unwrap();
        let EncodedResult::Returned(encoded) = encoded else {
            unreachable!()
        };
        assert_eq!(encoded.as_ref(), format!("[\"{value}\"]").as_bytes());
        drop(encoded);
        assert_eq!(budget.host_memory_bytes(), 0);
    }
}
