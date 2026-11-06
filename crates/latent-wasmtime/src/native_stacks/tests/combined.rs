use super::*;
use crate::component_threading::{Authentication, METADATA, RUST_COMBINED_HTTP_PROFILE};
use latent_core::{Metadata, ReleaseDigest};
use latent_executor::{PreparationKey, PreparedComponent};

fn descriptor() -> PreparedComponent {
    PreparedComponent {
        key: PreparationKey {
            release: ReleaseDigest(format!("sha256:{}", "1".repeat(64))),
            publication: None,
            engine_version: "test".into(),
            engine_configuration_digest: "test".into(),
            target_triple: "test".into(),
            cpu_feature_set: "test".into(),
        },
        backend: "test".into(),
        opaque_handle: "test".into(),
        metadata: Metadata::from([
            (METADATA.into(), RUST_COMBINED_HTTP_PROFILE.into()),
            ("component-digest".into(), format!("sha256:{}", "1".repeat(64))),
        ]),
    }
}

fn context(budget: &ActivationBudget, runtime: &ActivationRuntime, maximum: usize) -> Arc<StackContext> {
    StackContext::with_combined_http(
        budget.clone(), runtime.clone(), 64 * 1024, maximum,
        &Authentication::RustCombinedHttpVerified([0x11; 32]), &descriptor(),
    ).unwrap()
}

#[test]
fn combined_workers_require_matching_immutable_proof_before_reservation() {
    let (budget, runtime) = owners(4, 4 * 1024 * 1024);
    let before = budget.host_memory_bytes();
    for proof in [Authentication::Disabled, Authentication::CVerified([0x11; 32]),
                  Authentication::RustSyncVerified([0x11; 32]),
                  Authentication::RustCombinedHttpVerified([0x22; 32])] {
        assert!(StackContext::with_combined_http(budget.clone(), runtime.clone(), 64 * 1024,
                                               4, &proof, &descriptor()).is_err());
        assert_eq!(budget.host_memory_bytes(), before);
        assert_eq!(runtime.snapshot().owners[6], 0);
    }
    let proof = Authentication::RustCombinedHttpVerified([0x11; 32]);
    for key in [METADATA, "component-digest"] {
        let mut changed = descriptor();
        changed.metadata.remove(key);
        assert!(StackContext::with_combined_http(budget.clone(), runtime.clone(), 64 * 1024,
                                               4, &proof, &changed).is_err());
        assert_eq!(budget.host_memory_bytes(), before);
        assert_eq!(runtime.snapshot().owners[6], 0);
    }
}

#[test]
fn combined_workers_share_original_native_ceiling_and_keep_child_starts_affine() {
    let (budget, runtime) = owners(3, 4 * 1024 * 1024);
    let task = runtime.register(OwnerKind::Task, None).unwrap();
    let context = context(&budget, &runtime, 3);
    let guard = PollGuard::enter(&context);
    let root = Creator.new_stack(64 * 1024, true).unwrap();
    context.reserve_child(task.token()).unwrap();
    let child = Creator.new_stack(64 * 1024, true).unwrap();
    let worker = Creator.new_stack(64 * 1024, true).unwrap();
    let charged = budget.host_memory_bytes();
    assert_eq!(runtime.snapshot().owners[6], 3);
    assert!(Creator.new_stack(64 * 1024, true).is_err());
    assert!(context.reserve_child(task.token()).is_err());
    assert_eq!(runtime.snapshot().owners[6], 3);
    assert_eq!(budget.host_memory_bytes(), charged);
    drop(child);
    assert!(context.reserve_child(task.token()).is_err());
    let replacement = Creator.new_stack(64 * 1024, true).unwrap();
    assert_eq!(runtime.snapshot().owners[6], 3);
    drop(task);
    runtime.begin_drain();
    context.finish_logical().unwrap();
    assert!(Creator.new_stack(64 * 1024, true).is_err());
    assert!(context.after_store_dropped().is_err());
    drop(root);
    drop(worker);
    assert!(!context.physically_retired());
    drop(replacement);
    context.after_store_dropped().unwrap();
    assert_eq!(runtime.snapshot().phase, RuntimePhase::Retired);
    drop(guard);
    drop(context);
    drop(runtime);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}

#[test]
fn combined_worker_memory_failure_rolls_back_without_refunding_cached_child_capacity() {
    let (budget, runtime) = owners(3, 210 * 1024);
    let task = runtime.register(OwnerKind::Task, None).unwrap();
    let next = runtime.register(OwnerKind::Task, None).unwrap();
    let context = context(&budget, &runtime, 3);
    let guard = PollGuard::enter(&context);
    let root = Creator.new_stack(64 * 1024, true).unwrap();
    context.reserve_child(task.token()).unwrap();
    let child = Creator.new_stack(64 * 1024, true).unwrap();
    let charged = budget.host_memory_bytes();
    assert!(Creator.new_stack(64 * 1024, true).is_err());
    assert_eq!(budget.host_memory_bytes(), charged);
    assert_eq!(runtime.snapshot().owners[6], 2);
    drop(child);
    context.reserve_child(next.token()).unwrap();
    drop(task);
    drop(next);
    runtime.begin_drain();
    context.finish_logical().unwrap();
    drop(root);
    assert_eq!(runtime.snapshot().owners[6], 1);
    assert!(!context.physically_retired());
    context.after_store_dropped().unwrap();
    assert_eq!(runtime.snapshot().owners[6], 0);
    drop(guard);
    drop(context);
    drop(runtime);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}

#[tokio::test]
async fn combined_child_and_actual_nested_engine_workers_keep_one_original_ledger() {
    let (budget, runtime) = owners(4, 4 * 1024 * 1024);
    let task = runtime.register(OwnerKind::Task, None).unwrap();
    let context = context(&budget, &runtime, 4);
    let guard = PollGuard::enter(&context);
    let root = Creator.new_stack(64 * 1024, true).unwrap();
    context.reserve_child(task.token()).unwrap();
    let child = Creator.new_stack(64 * 1024, true).unwrap();
    drop(guard);
    let mut config = wasmtime::Config::new();
    config.async_stack_size(64 * 1024).max_wasm_stack(32 * 1024)
          .with_host_stack(Arc::new(Creator));
    let engine = Engine::new(&config).unwrap();
    let mut linker = Linker::<()>::new(&engine);
    let observed = runtime.clone();
    linker.func_wrap_async("host", "wait", move |mut caller, (): ()| {
        let observed = observed.clone();
        Box::new(async move {
            let leaf = caller.get_export("leaf").and_then(wasmtime::Extern::into_func).unwrap();
            assert_eq!(leaf.typed::<(), i32>(&caller)?.call_async(&mut caller, ()).await?, 7);
            assert_eq!(observed.snapshot().owners[6], 4);
            Ok(())
        })
    }).unwrap();
    let code = nested_module(&engine);
    let mut store = Store::new(&engine, ());
    let call = async {
        let instance = linker.instantiate_async(&mut store, &code).await?;
        instance.get_typed_func::<(), i32>(&mut store, "answer")?.call_async(&mut store, ()).await
    };
    assert_eq!(scoped(Arc::clone(&context), call).unwrap().await.unwrap(), 42);
    drop(task);
    runtime.begin_drain();
    context.finish_logical().unwrap();
    drop(store);
    assert!(context.after_store_dropped().is_err());
    drop(child);
    drop(root);
    context.after_store_dropped().unwrap();
    assert!(context.physically_retired());
    drop(linker);
    drop(code);
    drop(engine);
    drop(context);
    drop(runtime);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}
