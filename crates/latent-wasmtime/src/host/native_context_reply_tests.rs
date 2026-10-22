//! Planned actual-engine controls for only the six closed context reply buffers.
//! Test-controller typed outputs, opaque callback/fiber/queue storage are excluded.
use super::logging::BoundedLogSink;
use super::native_table_tests::denial;
use super::{accounting::InvocationAccounting, context, ActivationHostContext, HostState};
use crate::bindings::latent::context::context as wit;
use latent_core::{
    ActivationBudget, ActivationClock, ActivationId, BudgetProfile, ClockSample,
    EffectiveActivationBudget,
};
use latent_executor::ExecutionCancellation;
use std::future::Future;
use std::sync::Arc;
use std::task::{Context, Poll, Waker};
use std::time::Instant;
use wasmtime::component::{Component, Instance, Linker};
use wasmtime::{Config, Engine, Store};
#[path = "accounting/tests/support.rs"]
mod request_support;
const MIB: u64 = 1024 * 1024;
const FUEL: u64 = 1_000_000_000;
const COMPONENT: &[u8] = include_bytes!("native-context-replies.wasm");
struct Clock(Instant);
impl ActivationClock for Clock {
    fn sample(&self) -> ClockSample {
        ClockSample::new(9000, self.0)
    }
    fn monotonic_now(&self) -> Instant {
        self.0
    }
}
struct Cancellation {
    id: ActivationId,
    budget: ActivationBudget,
}
impl ExecutionCancellation for Cancellation {
    fn activation_id(&self) -> &ActivationId {
        &self.id
    }
    fn is_cancelled(&self) -> bool {
        false
    }
    fn reason(&self) -> Option<String> {
        None
    }
    fn budget_accounting(&self) -> Option<&ActivationBudget> {
        Some(&self.budget)
    }
}
fn ledger(profile: BudgetProfile) -> ActivationBudget {
    let mut resources = request_support::request().budget;
    resources.cpu_fuel = FUEL;
    resources.memory_bytes = MIB;
    resources.wall_time_limit_millis = Some(120000);
    resources.log_bytes = 0;
    let grant = EffectiveActivationBudget::admit_profile_at(
        profile,
        &resources,
        &resources,
        &resources,
        None,
        ClockSample::new(9000, Instant::now()),
    )
    .unwrap();
    ActivationBudget::with_profile(grant, profile).unwrap()
}
fn state(original: &ActivationBudget, empty: bool) -> HostState {
    let mut request = request_support::request();
    request.budget = original.granted().clone();
    request.activation.budget = request.budget.clone();
    request.cell.maximum_memory_bytes = MIB;
    request.activation.deadline_unix_millis = None;
    request.activation.activation_id = ActivationId("context-owned".to_owned());
    request.activation.root_activation_id = ActivationId("root-owned".to_owned());
    request.activation.parent_activation_id = Some(ActivationId("parent-owned".to_owned()));
    if !empty {
        request
            .activation
            .principal
            .claims
            .insert("visible".to_owned(), "claim".to_owned());
        request
            .activation
            .principal
            .claims
            .insert("private".to_owned(), "hidden".to_owned());
        request
            .activation
            .trace
            .baggage
            .insert("visible".to_owned(), "baggage".to_owned());
        request
            .activation
            .trace
            .baggage
            .insert("private".to_owned(), "hidden".to_owned());
        request
            .activation
            .metadata
            .insert("guest.a".to_owned(), "42".to_owned());
        request
            .activation
            .metadata
            .insert("guest.z".to_owned(), String::new());
        request
            .activation
            .metadata
            .insert("private".to_owned(), "hidden".to_owned());
    }
    let clock: Arc<dyn ActivationClock> = Arc::new(Clock(Instant::now()));
    let cancellation = Cancellation {
        id: request.activation.activation_id.clone(),
        budget: original.clone(),
    };
    let accounting = InvocationAccounting::new(&request, &cancellation, clock.as_ref()).unwrap();
    let context = ActivationHostContext::from_request_accounted(
        request,
        accounting.deadline().unix_millis(),
        original,
    )
    .unwrap();
    let mut policy = super::ContextExposurePolicy::default();
    policy.claim_keys = vec!["visible".to_owned()];
    policy.baggage_keys = vec!["visible".to_owned()];
    HostState::with_config(
        context,
        MIB as usize,
        &crate::WasmtimeConfig::default(),
        accounting,
        Arc::new(policy),
        clock.clone(),
        clock.monotonic_now(),
        BoundedLogSink::new(0, 0),
    )
}
fn engine() -> Engine {
    let mut config = Config::new();
    crate::WasmtimeConfig::default()
        .apply_engine(&mut config)
        .unwrap();
    config.consume_fuel(true);
    Engine::new(&config).unwrap()
}
fn store(engine: &Engine, original: &ActivationBudget, empty: bool) -> Store<HostState> {
    let state = state(original, empty);
    let mut store = if original.profile() == BudgetProfile::Phase1 {
        Store::new(engine, state)
    } else {
        Store::try_new_with_memory_binding(
            engine,
            state,
            crate::native_tables::binding(original).unwrap(),
        )
        .unwrap()
    };
    store.limiter(|state| &mut state.limiter);
    store.set_fuel(FUEL).unwrap();
    store.fuel_async_yield_interval(Some(1000)).unwrap();
    store
}
async fn instantiate(engine: &Engine, store: &mut Store<HostState>) -> Instance {
    let component = Component::new(engine, COMPONENT).unwrap();
    let mut linker = Linker::new(engine);
    context::install(&mut linker).unwrap();
    linker.instantiate_async(store, &component).await.unwrap()
}
async fn mode(instance: Instance, store: &mut Store<HostState>, value: u32) {
    instance
        .get_typed_func::<(u32,), ()>(&mut *store, "mode")
        .unwrap()
        .call_async(store, (value,))
        .await
        .unwrap();
}
async fn id(instance: Instance, store: &mut Store<HostState>) -> String {
    instance
        .get_typed_func::<(), (String,)>(&mut *store, "activation-id")
        .unwrap()
        .call_async(store, ())
        .await
        .unwrap()
        .0
}
#[tokio::test]
async fn actual_context_reply_six_shapes_and_scalars_fit_original_one_mib_and_billion_fuel() {
    let engine = engine();
    for profile in [BudgetProfile::Phase3, BudgetProfile::Phase4] {
        let original = ledger(profile);
        let mut store = store(&engine, &original, false);
        let instance = instantiate(&engine, &mut store).await;
        assert_eq!(id(instance, &mut store).await, "context-owned");
        assert_eq!(
            instance
                .get_typed_func::<(), (String,)>(&mut store, "root-activation-id")
                .unwrap()
                .call_async(&mut store, ())
                .await
                .unwrap()
                .0,
            "root-owned"
        );
        assert_eq!(
            instance
                .get_typed_func::<(), (Option<String>,)>(&mut store, "parent-activation-id")
                .unwrap()
                .call_async(&mut store, ())
                .await
                .unwrap()
                .0
                .as_deref(),
            Some("parent-owned")
        );
        let p = instance
            .get_typed_func::<(), (wit::InvocationPrincipal,)>(&mut store, "principal")
            .unwrap()
            .call_async(&mut store, ())
            .await
            .unwrap()
            .0;
        assert_eq!(p.subject, "user");
        assert_eq!(p.kind, "user");
        assert_eq!(p.tenant.as_deref(), Some("tenant"));
        assert!(p.service.is_none());
        assert_eq!(p.claims, [("visible".to_owned(), "claim".to_owned())]);
        let trace = instance
            .get_typed_func::<(), (wit::TraceContext,)>(&mut store, "trace")
            .unwrap()
            .call_async(&mut store, ())
            .await
            .unwrap()
            .0;
        assert_eq!(trace.trace_id, "trace");
        assert_eq!(trace.span_id, "span");
        assert_eq!(trace.trace_flags, 1);
        assert_eq!(
            trace.baggage,
            [("visible".to_owned(), "baggage".to_owned())]
        );
        let metadata = instance
            .get_typed_func::<(), (Vec<(String, String)>,)>(&mut store, "metadata")
            .unwrap()
            .call_async(&mut store, ())
            .await
            .unwrap()
            .0;
        assert_eq!(
            metadata,
            [
                ("guest.a".to_owned(), "42".to_owned()),
                ("guest.z".to_owned(), String::new())
            ]
        );
        assert_eq!(
            instance
                .get_typed_func::<(), (Option<u64>,)>(&mut store, "deadline-unix-millis")
                .unwrap()
                .call_async(&mut store, ())
                .await
                .unwrap()
                .0,
            Some(129000)
        );
        let remaining = instance
            .get_typed_func::<(), (wit::ResourceBudget,)>(&mut store, "remaining-budget")
            .unwrap()
            .call_async(&mut store, ())
            .await
            .unwrap()
            .0;
        assert!(remaining.cpu_fuel < FUEL);
        assert!(remaining.memory_bytes <= MIB);
        assert!(store.get_fuel().unwrap() < FUEL);
        assert_eq!(original.granted().memory_bytes, MIB);
        assert_eq!(original.granted().cpu_fuel, FUEL);
        // Controller-owned lifted return copies are not the original host reply R.
        drop((p, trace, metadata));
        drop(store);
        assert_eq!(original.host_memory_bytes(), 0);
        assert_eq!(original.outstanding_reservations(), 0);
    }
}

struct Padding {
    _bytes: Vec<u8>,
    _owner: Box<dyn wasmtime::NativeAllocation>,
}
#[tokio::test]
async fn actual_context_reply_original_refusal_keeps_exact_error_and_fresh_same_grant() {
    let engine = engine();
    let original = ledger(BudgetProfile::Phase3);
    let mut first = store(&engine, &original, false);
    let instance = instantiate(&engine, &mut first).await;
    let function = instance
        .get_typed_func::<(), (String,)>(&mut first, "activation-id")
        .unwrap();
    assert_eq!(
        function.call_async(&mut first, ()).await.unwrap().0,
        "context-owned"
    );
    // Warm the identical call path, then pad physically allocated backing. Fixed
    // linear pages are the actual limiter observation, not a guessed prefix sum.
    let reply = super::policy::reply_string_charge("context-owned").unwrap() as u64
        + crate::native_tables::OWNER_ESCROW as u64;
    let linear = first.data().limiter.peak_memory_bytes();
    let consumed = original.host_memory_bytes() + linear;
    let bytes = MIB - consumed - reply + 1 - crate::native_tables::OWNER_ESCROW as u64;
    let mut owner = crate::native_tables::reserve(&original, bytes as usize)
        .unwrap()
        .unwrap();
    let allocation = vec![0u8; bytes as usize];
    assert_eq!(allocation.capacity(), bytes as usize);
    owner.allocated();
    let padding = Padding {
        _bytes: allocation,
        _owner: owner,
    };
    let consumed = original.host_memory_bytes() + linear;
    assert_eq!(consumed + reply, MIB + 1);
    let error = function.call_async(&mut first, ()).await.unwrap_err();
    denial(&error, MIB, consumed, reply);
    drop(error);
    drop(padding);
    drop(first);
    assert_eq!(original.host_memory_bytes(), 0);
    let mut fresh = store(&engine, &original, false);
    let fresh_instance = instantiate(&engine, &mut fresh).await;
    assert_eq!(id(fresh_instance, &mut fresh).await, "context-owned");
    drop(fresh);
    assert_eq!(original.host_memory_bytes(), 0);
    assert_eq!(original.outstanding_reservations(), 0);
}
#[tokio::test]
async fn actual_context_reply_pending_lower_cancellation_cannot_credit_another_store() {
    let engine = engine();
    let a = ledger(BudgetProfile::Phase3);
    let b = ledger(BudgetProfile::Phase3);
    let mut first = store(&engine, &a, false);
    let mut second = store(&engine, &b, false);
    let ai = instantiate(&engine, &mut first).await;
    let bi = instantiate(&engine, &mut second).await;
    let af = ai
        .get_typed_func::<(), (String,)>(&mut first, "activation-id")
        .unwrap();
    let bf = bi
        .get_typed_func::<(), (String,)>(&mut second, "activation-id")
        .unwrap();
    assert_eq!(
        af.call_async(&mut first, ()).await.unwrap().0,
        "context-owned"
    );
    assert_eq!(
        bf.call_async(&mut second, ()).await.unwrap().0,
        "context-owned"
    );
    mode(ai, &mut first, 2).await;
    mode(bi, &mut second, 2).await;
    let abase = a.host_memory_bytes();
    let bbase = b.host_memory_bytes();
    let reply = super::policy::reply_string_charge("context-owned").unwrap() as u64
        + crate::native_tables::OWNER_ESCROW as u64;
    let mut acall = Box::pin(af.call_async(&mut first, ()));
    let mut bcall = Box::pin(bf.call_async(&mut second, ()));
    let mut cx = Context::from_waker(Waker::noop());
    assert!(matches!(acall.as_mut().poll(&mut cx), Poll::Pending));
    assert!(matches!(bcall.as_mut().poll(&mut cx), Poll::Pending));
    // Before first Core fuel yield the bridge/realloc prefix is <1000 operators.
    // Both actual String R owners exist inside pure-Core allocator loops; no
    // forbidden allocator import or completed result handoff can satisfy this.
    assert!(a.host_memory_bytes() >= abase + reply);
    assert!(b.host_memory_bytes() >= bbase + reply);
    let live_b = b.host_memory_bytes();
    drop(acall);
    drop(first);
    assert_eq!(a.host_memory_bytes(), 0);
    assert_eq!(a.outstanding_reservations(), 0);
    assert_eq!(b.host_memory_bytes(), live_b);
    drop(bcall);
    drop(second);
    assert_eq!(b.host_memory_bytes(), 0);
    assert_eq!(b.outstanding_reservations(), 0);
}
#[tokio::test]
async fn actual_context_reply_guest_realloc_error_is_unchanged_and_owner_retires() {
    let engine = engine();
    let original = ledger(BudgetProfile::Phase3);
    let mut first = store(&engine, &original, false);
    let instance = instantiate(&engine, &mut first).await;
    assert_eq!(id(instance, &mut first).await, "context-owned");
    mode(instance, &mut first, 1).await;
    let error = instance
        .get_typed_func::<(), (String,)>(&mut first, "activation-id")
        .unwrap()
        .call_async(&mut first, ())
        .await
        .unwrap_err();
    assert_eq!(
        error.downcast_ref::<wasmtime::Trap>(),
        Some(&wasmtime::Trap::UnreachableCodeReached)
    );
    drop(error);
    drop(first);
    assert_eq!(original.host_memory_bytes(), 0);
    assert_eq!(original.outstanding_reservations(), 0);
    let mut fresh = store(&engine, &original, false);
    let instance = instantiate(&engine, &mut fresh).await;
    assert_eq!(id(instance, &mut fresh).await, "context-owned");
    drop(fresh);
    assert_eq!(original.host_memory_bytes(), 0);
}
#[tokio::test]
async fn actual_context_reply_empty_selection_and_phase1_keep_lazy_legacy_behavior() {
    let engine = engine();
    for profile in [
        BudgetProfile::Phase3,
        BudgetProfile::Phase4,
        BudgetProfile::Phase1,
    ] {
        let original = ledger(profile);
        let mut store = store(&engine, &original, true);
        let instance = instantiate(&engine, &mut store).await;
        assert_eq!(
            store
                .data()
                .context_policy
                .metadata_reply_charge(&store.data().context.metadata)
                .unwrap(),
            0
        );
        assert_eq!(id(instance, &mut store).await, "context-owned");
        let result = instance
            .get_typed_func::<(), (Vec<(String, String)>,)>(&mut store, "metadata")
            .unwrap()
            .call_async(&mut store, ())
            .await
            .unwrap()
            .0;
        assert!(result.is_empty());
        assert_eq!(result.capacity(), 0);
        if profile == BudgetProfile::Phase1 {
            assert_eq!(original.host_memory_bytes(), 0);
            assert_eq!(original.outstanding_reservations(), 0);
        }
        drop(result);
        drop(store);
        assert_eq!(original.host_memory_bytes(), 0);
        assert_eq!(original.outstanding_reservations(), 0);
    }
}
