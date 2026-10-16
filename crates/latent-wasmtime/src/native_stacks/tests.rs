#![cfg(all(target_os = "linux", target_arch = "x86_64"))]
use super::*;
use latent_core::activation_runtime::{RuntimeLimits, RuntimePhase};
use latent_core::{BudgetProfile, ClockSample, EffectiveActivationBudget, ResourceBudget};
use wasmtime::{Engine, Linker, Module, StackCreator, Store};

struct Signal;
impl latent_core::BudgetCancellationProbe for Signal {
    fn is_cancelled(&self) -> bool {
        false
    }
    fn cancelled(&self) -> latent_core::BoxFuture<'_, ()> {
        Box::pin(std::future::pending())
    }
    fn mark_terminal(&self) {}
}

fn owners(native: u32, memory: u64) -> (ActivationBudget, ActivationRuntime) {
    let limit = ResourceBudget {
        cpu_fuel: 10_000_000,
        memory_bytes: memory,
        wall_time_limit_millis: Some(5000),
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
        &limit,
        &limit,
        &limit,
        None,
        ClockSample::system_now(),
    )
    .unwrap();
    let budget = ActivationBudget::with_profile(grant, BudgetProfile::Phase3).unwrap();
    budget
        .enable_descendants(latent_core::DelegationLimits::default(), Arc::new(Signal))
        .unwrap();
    let runtime = ActivationRuntime::new(
        budget.clone(),
        RuntimeLimits {
            tasks: 2,
            executors: 1,
            queued_work: 1,
            waits: 2,
            timers: 2,
            results: 1,
            native_owners: native,
        },
    )
    .unwrap();
    (budget, runtime)
}

fn module(engine: &Engine) -> Module {
    use wasm_encoder::*;
    let mut module = wasm_encoder::Module::new();
    let mut types = TypeSection::new();
    types.ty().function([], []);
    types.ty().function([], [ValType::I32]);
    module.section(&types);
    let mut imports = ImportSection::new();
    imports.import("host", "wait", EntityType::Function(0));
    module.section(&imports);
    let mut functions = FunctionSection::new();
    functions.function(1);
    module.section(&functions);
    let mut exports = ExportSection::new();
    exports.export("answer", ExportKind::Func, 1);
    module.section(&exports);
    let mut body = Function::new([]);
    body.instruction(&Instruction::Call(0))
        .instruction(&Instruction::I32Const(42))
        .instruction(&Instruction::End);
    let mut code = CodeSection::new();
    code.function(&body);
    module.section(&code);
    wasmtime::Module::new(engine, module.finish()).unwrap()
}

#[test]
fn original_native_and_memory_limits_reject_before_mapping_and_roll_back_unstarted_permits() {
    let (budget, runtime) = owners(1, 1024 * 1024);
    let context = StackContext::new(budget.clone(), runtime.clone(), 64 * 1024).unwrap();
    let before = budget.host_memory_bytes();
    assert!(StackContext::new(budget.clone(), runtime.clone(), 64 * 1024).is_err());
    assert_eq!(budget.host_memory_bytes(), before);
    assert_eq!(runtime.snapshot().owners[6], 1);
    context.cancel_unstarted();
    assert!(context.physically_retired());
    assert_eq!(runtime.snapshot().owners[6], 0);
    drop(context);
    runtime.retire().unwrap();
    drop(runtime);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);

    let (budget, runtime) = owners(1, 32 * 1024);
    assert!(StackContext::new(budget.clone(), runtime.clone(), 64 * 1024).is_err());
    assert_eq!(runtime.snapshot().owners[6], 0);
    runtime.retire().unwrap();
    drop(runtime);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[test]
fn allocator_requires_poll_scoped_owner_and_never_reuses_a_consumed_prestart_permit() {
    assert!(Creator.new_stack(64 * 1024, true).is_err());
    let (budget, runtime) = owners(2, 1024 * 1024);
    let context = StackContext::new(budget.clone(), runtime.clone(), 64 * 1024).unwrap();
    let guard = PollGuard::enter(&context);
    let stack = Creator.new_stack(64 * 1024, true).unwrap();
    assert!(Creator.new_stack(64 * 1024, true).is_err());
    let range = stack.range();
    let guard_range = stack.guard_range();
    assert_eq!(range.start, guard_range.end as usize);
    assert_eq!(range.end, stack.top() as usize);
    assert_eq!(range.end - range.start, 64 * 1024);
    assert_eq!(runtime.snapshot().owners[6], 1);
    drop(guard);
    assert!(Creator.new_stack(64 * 1024, true).is_err());
    runtime.begin_drain();
    context.finish_logical().unwrap();
    assert!(!context.physically_retired());
    drop(stack);
    assert!(context.physically_retired());
    assert_eq!(runtime.snapshot().phase, RuntimePhase::Retired);
    drop(context);
    drop(runtime);
    assert_eq!(budget.host_memory_bytes(), 0);
}

#[test]
fn logical_finalization_cannot_hide_a_guest_owned_native_or_task_record() {
    for kind in [OwnerKind::Native, OwnerKind::Task] {
        let (budget, runtime) = owners(2, 1024 * 1024);
        let context = StackContext::new(budget.clone(), runtime.clone(), 64 * 1024).unwrap();
        let extra = runtime.register(kind, None).unwrap();
        runtime.begin_drain();
        assert!(context.finish_logical().is_err());
        drop(extra);
        context.finish_logical().unwrap();
        drop(context);
        drop(runtime);
        assert_eq!(budget.host_memory_bytes(), 0);
    }
}

#[tokio::test]
async fn actual_wasmtime_pending_stack_keeps_original_lease_until_native_drop() {
    pending_stack(false).await;
}

#[tokio::test]
async fn cancelling_actual_pending_call_keeps_original_lease_until_native_drop() {
    pending_stack(true).await;
}

async fn pending_stack(cancel: bool) {
    let (budget, runtime) = owners(1, 4 * 1024 * 1024);
    let context = StackContext::new(budget.clone(), runtime.clone(), 64 * 1024).unwrap();
    let mut config = wasmtime::Config::new();
    config
        .async_stack_size(64 * 1024)
        .max_wasm_stack(32 * 1024)
        .with_host_stack(Arc::new(Creator));
    let engine = Engine::new(&config).unwrap();
    let (send, receive) = tokio::sync::oneshot::channel::<()>();
    let receive = Arc::new(Mutex::new(Some(receive)));
    let mut linker = Linker::new(&engine);
    linker
        .func_wrap_async("host", "wait", move |_, (): ()| {
            let receive = receive.lock().unwrap().take().unwrap();
            Box::new(async move {
                receive.await.unwrap();
                Ok(())
            })
        })
        .unwrap();
    let mut store = Store::new(&engine, ());
    let code = module(&engine);
    let call = async {
        let instance = linker.instantiate_async(&mut store, &code).await.unwrap();
        instance
            .get_typed_func::<(), i32>(&mut store, "answer")
            .unwrap()
            .call_async(&mut store, ())
            .await
            .unwrap()
    };
    let mut call = Box::pin(scoped(Arc::clone(&context), call).unwrap());
    std::future::poll_fn(|cx| {
        assert!(call.as_mut().poll(cx).is_pending());
        Poll::Ready(())
    })
    .await;
    assert_eq!(context.active.load(Ordering::Acquire), 1);
    assert_eq!(runtime.snapshot().owners[6], 1);
    assert!(budget.host_memory_bytes() > 64 * 1024);
    if cancel {
        drop(call);
        drop(send);
    } else {
        send.send(()).unwrap();
        assert_eq!(call.await, 42);
    }
    runtime.begin_drain();
    context.finish_logical().unwrap();
    drop(store);
    assert!(context.physically_retired());
    assert_eq!(runtime.snapshot().owners[6], 0);
    drop(context);
    drop(runtime);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}

#[test]
fn controlled_profile_rejects_pooling_and_absent_runtime_and_binds_compatibility() {
    use crate::config::{DispatchMode, InstanceAllocator, WasmtimeConfig};
    let mut config = WasmtimeConfig {
        owned_native_stacks: true,
        ..WasmtimeConfig::default()
    };
    assert!(config.validate().is_err());
    config.activation_runtime = Some(RuntimeLimits {
        tasks: 1,
        executors: 1,
        queued_work: 1,
        waits: 1,
        timers: 1,
        results: 1,
        native_owners: 1,
    });
    assert!(config.validate().is_ok());
    let owned = config.configuration_digest(DispatchMode::Generic);
    config.owned_native_stacks = false;
    assert_ne!(owned, config.configuration_digest(DispatchMode::Generic));
    config.owned_native_stacks = true;
    config.instance_allocator = InstanceAllocator::Pooling;
    assert!(config.validate().is_err());
    config.instance_allocator = InstanceAllocator::OnDemand;
    config.owned_native_threads = true;
    assert!(config.validate().is_ok());
    let native = config.profile(DispatchMode::Generic);
    assert_eq!(
        native.configuration["host-abi-profile"],
        latent_core::PHASE3_HOST_ABI_V6.id
    );
    assert_eq!(
        native.configuration["native-thread-profile"],
        crate::host::native::PROFILE
    );
    config.owned_native_threads = false;
    let ordinary = config.profile(DispatchMode::Generic);
    assert_eq!(
        ordinary.configuration["host-abi-profile"],
        latent_core::PHASE3_HOST_ABI_V5.id
    );
    assert_ne!(
        native.configuration["configuration-digest"],
        ordinary.configuration["configuration-digest"]
    );
    config.owned_native_threads = true;
    config.owned_native_stacks = false;
    assert!(config.validate().is_err());
    config.owned_native_stacks = true;
    config.transactional_state = true;
    assert!(config.validate().is_err());
}

#[tokio::test]
async fn child_preadmission_and_exact_native_retirement_keep_original_wait_and_stack_owners() {
    let (budget, runtime) = owners(2, 4 * 1024 * 1024);
    let task = runtime.register(OwnerKind::Task, None).unwrap();
    let context =
        StackContext::with_children(budget.clone(), runtime.clone(), 64 * 1024, 1).unwrap();
    let guard = PollGuard::enter(&context);
    let root_stack = Creator.new_stack(64 * 1024, true).unwrap();
    let child = context.reserve_child(task.token()).unwrap();
    let before = budget.host_memory_bytes();
    assert!(context.reserve_child(task.token()).is_err());
    assert_eq!(budget.host_memory_bytes(), before);
    assert_eq!(runtime.snapshot().owners[6], 2);
    assert!(!child.physically_retired());
    assert!(context.reap_child(child.token()).is_err());
    child.prepare_wait(task.token()).unwrap();
    assert!(child.prepare_wait(task.token()).is_err());
    let child_stack = Creator.new_stack(64 * 1024, true).unwrap();
    assert!(Creator.new_stack(64 * 1024, true).is_err());
    let mapped_charge = budget.host_memory_bytes();
    let mut retired = Box::pin(child.changed());
    std::future::poll_fn(|cx| {
        assert!(retired.as_mut().poll(cx).is_pending());
        Poll::Ready(())
    })
    .await;
    drop(child_stack);
    retired.await;
    assert_eq!(
        budget.host_memory_bytes(),
        mapped_charge - context.mapped as u64
    );
    assert!(child.physically_retired());
    assert!(!child.retirement_failed());
    assert_eq!(runtime.snapshot().owners[6], 1);
    assert_eq!(runtime.snapshot().owners[3], 1);
    context.reap_child(child.token()).unwrap();
    assert!(context.child(child.token()).is_err());
    drop(child);
    assert_eq!(runtime.snapshot().owners[3], 0);
    drop(task);
    runtime.begin_drain();
    context.finish_logical().unwrap();
    drop(root_stack);
    drop(guard);
    assert!(context.physically_retired());
    drop(context);
    drop(runtime);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}
