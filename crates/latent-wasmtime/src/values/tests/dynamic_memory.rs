//! Actual pinned engine allocation hooks, without a guest SDK/toolchain build.
use super::*;
use latent_core::{ActivationBudget, BudgetProfile, ClockSample, EffectiveActivationBudget};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::time::Instant;

fn budget(memory: u64) -> ActivationBudget {
    let mut limits = super::host_memory::original_budget().granted().clone();
    limits.memory_bytes = memory;
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
async fn fixture(
    name: &str,
    pending: bool,
) -> (
    wasmtime::Store<()>,
    wasmtime::component::Func,
    Arc<AtomicBool>,
) {
    let mut config = Config::new();
    config
        .wasm_component_model(true)
        .wasm_component_model_async(true)
        .concurrency_support(true);
    let engine = Engine::new(&config).unwrap();
    let component =
        Component::new(&engine, include_bytes!("../host-memory-accounted.wasm")).unwrap();
    let entered = Arc::new(AtomicBool::new(false));
    let observed = entered.clone();
    let mut linker = wasmtime::component::Linker::<()>::new(&engine);
    linker
        .root()
        .func_wrap_async("wait", move |_, (): ()| {
            observed.store(true, Ordering::SeqCst);
            Box::new(async move {
                if pending {
                    std::future::pending::<()>().await;
                }
                Ok(())
            })
        })
        .unwrap();
    let mut store = wasmtime::Store::new(&engine, ());
    store.set_hostcall_fuel(128 * 1024);
    let instance = linker
        .instantiate_async(&mut store, &component)
        .await
        .unwrap();
    let function = instance.get_func(&mut store, name).unwrap();
    (store, function, entered)
}
fn peak(budget: &ActivationBudget) -> u64 {
    budget.snapshot_at(Instant::now()).peak_memory_bytes
}

#[tokio::test]
async fn actual_dynamic_declared_tiny_result_fits_original_one_mib_without_maximum_escrow() {
    let budget = budget(1024 * 1024);
    // Existing original runtime occupancy leaves much less than the old 525056
    // signature envelope. The real backend/child gate independently owns the
    // actual Store/linear-memory accounting; this control isolates the lift.
    budget.reserve_runtime_memory(900 * 1024).unwrap().confirm();
    let (mut store, function, _) = fixture("declared", false).await;
    let mut output = OwnedValues::output_accounted(1, &budget).unwrap();
    let scope = output.lift_memory().unwrap();
    function
        .call_async_with_memory(&mut store, &[], output.as_mut_slice(), scope)
        .await
        .unwrap();
    output.finish_lift(true).unwrap();
    assert!(
        matches!(&output.as_slice()[0], Val::Result(Err(Some(value))) if matches!(value.as_ref(), Val::String(s) if s == "tiny"))
    );
    assert!(peak(&budget) < 900 * 1024 + 4096);
    drop(store);
    assert!(budget.host_memory_bytes() > 0);
    drop(output);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}

#[tokio::test]
async fn actual_utf8_utf16_latin1_prepass_preserves_exact_original_fuel_and_capacity() {
    for (name, expected, fuel) in [
        ("utf8", "tiny", 4),
        ("utf16", "é😀", 6),
        ("latin1", "éÿ", 2),
    ] {
        for admitted in [true, false] {
            let budget = budget(1024 * 1024);
            let (mut store, function, _) = fixture(name, false).await;
            store.set_hostcall_fuel(if admitted { fuel } else { fuel - 1 });
            let mut output = OwnedValues::output_accounted(1, &budget).unwrap();
            let scope = output.lift_memory().unwrap();
            let result = function
                .call_async_with_memory(&mut store, &[], output.as_mut_slice(), scope)
                .await;
            assert_eq!(result.is_ok(), admitted, "{name}");
            output.finish_lift(result.is_ok()).unwrap();
            if admitted {
                let Val::String(value) = &output.as_slice()[0] else {
                    panic!("string result")
                };
                assert_eq!(value, expected);
                assert_eq!(value.capacity(), expected.len());
            }
            assert!(peak(&budget) < 4096);
            drop(result);
            drop(store);
            drop(output);
            assert_eq!(budget.host_memory_bytes(), 0);
        }
    }
}

#[tokio::test]
async fn actual_nested_names_flags_and_variant_box_hold_original_memory_until_values_die() {
    let budget = budget(1024 * 1024);
    let (mut store, function, _) = fixture("nested", false).await;
    let signature = function.ty(&store).results().collect::<Vec<_>>();
    let mut output = OwnedValues::output_accounted(1, &budget).unwrap();
    let scope = output.lift_memory().unwrap();
    function
        .call_async_with_memory(&mut store, &[], output.as_mut_slice(), scope)
        .await
        .unwrap();
    output.finish_lift(true).unwrap();
    let encoded = encode_result_accounted(
        &signature,
        output.as_slice(),
        ValueCodecLimits::default(),
        &budget,
    )
    .unwrap();
    let EncodedResult::Returned(encoded) = encoded else {
        panic!("record result")
    };
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&encoded).unwrap(),
        serde_json::json!([{"name":"tiny","permissions":["read","admin"],"choice":{"case":"one","value":"tiny"}}])
    );
    assert!(budget.host_memory_bytes() > 512);
    assert!(peak(&budget) < 8192);
    drop(store);
    drop(encoded);
    assert!(budget.host_memory_bytes() > 512);
    drop(output);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[tokio::test]
async fn actual_lift_refusal_retains_original_memory_bytes_error_and_does_not_allocate_string() {
    let budget = budget(1024 * 1024);
    let (mut store, function, _) = fixture("large", false).await;
    let mut output = OwnedValues::output_accounted(1, &budget).unwrap();
    let scope = output.lift_memory().unwrap();
    // Permit the independent empty parameter scope. After its physical drop,
    // the actual 1024-byte string cannot fit behind the result slot vector.
    let held = budget
        .reserve_host_memory(budget.granted().memory_bytes - budget.host_memory_bytes() - 256)
        .unwrap();
    let before = budget.host_memory_bytes();
    let error = function
        .call_async_with_memory(&mut store, &[], output.as_mut_slice(), scope)
        .await
        .unwrap_err();
    let original = error
        .chain()
        .find_map(|cause| cause.downcast_ref::<super::super::LiftMemoryError>())
        .map(|error| &error.0)
        .expect("original callback error and complete budget metadata");
    assert_eq!(
        original.code,
        latent_core::PlatformErrorCode::ResourceExhausted
    );
    assert!(original.details.iter().any(|detail| detail
        .fields
        .get("dimension")
        .map(String::as_str)
        == Some("memory-bytes")));
    assert!(matches!(&output.as_slice()[0], Val::Bool(false)));
    assert!(budget.host_memory_bytes() >= before);
    drop(error);
    drop(store);
    drop(held);
    drop(output);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[tokio::test]
async fn actual_partial_failed_lift_reports_only_allocated_tree_and_retires_after_native_unwind() {
    let budget = budget(1024 * 1024);
    let (mut store, function, _) = fixture("partial", false).await;
    let mut output = OwnedValues::output_accounted(1, &budget).unwrap();
    let scope = output.lift_memory().unwrap();
    let error = function
        .call_async_with_memory(&mut store, &[], output.as_mut_slice(), scope)
        .await
        .unwrap_err();
    output.finish_lift(false).unwrap();
    assert!(peak(&budget) > 512);
    assert!(peak(&budget) < 8192); // no fictitious 0.5 MiB maximum attribution
    drop(error);
    drop(store);
    drop(output);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}

#[tokio::test]
async fn actual_parameter_copy_refunds_before_lift_and_abandoned_post_return_keeps_result_owner() {
    use std::{
        future::Future,
        task::{Context, Wake, Waker},
    };
    struct Noop;
    impl Wake for Noop {
        fn wake(self: Arc<Self>) {}
    }
    let budget = budget(1024 * 1024);
    let (mut store, function, entered) = fixture("echo-post", true).await;
    let json = serde_json::to_vec(&vec!["x".repeat(8192)]).unwrap();
    let input = decode_params_accounted(
        &[Type::String],
        &json,
        MEDIA_TYPE,
        ValueCodecLimits::default(),
        &budget,
    )
    .unwrap();
    let input_bytes = budget.host_memory_bytes();
    let mut output = OwnedValues::output_accounted(1, &budget).unwrap();
    let scope = output.lift_memory().unwrap();
    let mut call = Box::pin(function.call_async_with_memory(
        &mut store,
        input.as_slice(),
        output.as_mut_slice(),
        scope,
    ));
    let waker = Waker::from(Arc::new(Noop));
    assert!(call
        .as_mut()
        .poll(&mut Context::from_waker(&waker))
        .is_pending());
    assert!(entered.load(Ordering::SeqCst));
    assert!(peak(&budget) >= input_bytes + 8192); // actual simultaneous deep copy
    assert!(budget.host_memory_bytes() < input_bytes + 4096); // copied parameters actually gone
    drop(call);
    drop(input);
    drop(output);
    assert!(budget.host_memory_bytes() > 0); // Store-owned post-return result remains
    drop(store);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}
