//! Actual component controls for a callback inside the admitted engine future.
//! The probe is test-controller storage; it is not a production budget or RSS.
use super::{Accessor, InlineConcurrentHost};
use crate::component::{Component, Linker};
use crate::{
    AsContextMut, Config, Engine, NativeAllocation, NativeMemory, NativeMemoryBinding, Store,
};
use std::alloc::{GlobalAlloc, Layout, System};
use std::boxed::Box;
use std::cell::Cell;
use std::future::Future;
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering::SeqCst};
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll, Waker};

// These tests use the current-thread Tokio executor. Only this thread's
// allocations are watched, so unrelated parallel tests cannot steal the
// pointer by allocating a block with the same size.
struct WatchingAllocator;
#[derive(Clone, Copy, Default)]
struct Watch {
    size: usize,
    armed: bool,
    pointer: usize,
    freed: bool,
}
std::thread_local! {
    static WATCH: Cell<Watch> = const { Cell::new(Watch { size: 0, armed: false, pointer: 0, freed: false }) };
}
static TEST_LOCK: Mutex<()> = Mutex::new(());

#[global_allocator]
static GLOBAL: WatchingAllocator = WatchingAllocator;
unsafe impl GlobalAlloc for WatchingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let ptr = unsafe { System.alloc(layout) };
        let _ = WATCH.try_with(|cell| {
            let mut watch = cell.get();
            if watch.armed && layout.size() == watch.size && watch.pointer == 0 {
                watch.pointer = ptr as usize;
                cell.set(watch);
            }
        });
        ptr
    }
    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        let _ = WATCH.try_with(|cell| {
            let mut watch = cell.get();
            if ptr as usize == watch.pointer && !ptr.is_null() {
                watch.freed = true;
                cell.set(watch);
            }
        });
        unsafe { System.dealloc(ptr, layout) }
    }
}

const COMPONENT: &str = r#"
(component
  (type $wait-type (func async (result u32)))
  (import "wait" (func $wait (type $wait-type)))
  (core func $wait-core (canon lower (func $wait)))
  (core module $guest
    (import "host" "wait" (func $wait (result i32)))
    (func (export "run") (result i32) call $wait))
  (core instance $host (export "wait" (func $wait-core)))
  (core instance $guest (instantiate $guest (with "host" (instance $host))))
  (type $run-type (func async (result u32)))
  (func (export "run") (type $run-type)
    (canon lift (core func $guest "run"))))
"#;

#[derive(Default)]
struct State {
    factory: AtomicUsize,
    polls: AtomicUsize,
    drops: AtomicUsize,
    factory_dropped: AtomicUsize,
    binding_released: AtomicUsize,
    inline_bytes: AtomicUsize,
    inline_active: AtomicUsize,
    inline_confirmed: AtomicUsize,
    inline_released: AtomicUsize,
    inline_refuse: AtomicBool,
    inline_physical_first: AtomicBool,
    callback_address: AtomicUsize,
}

struct Memory(Arc<State>);
struct Allocation {
    state: Arc<State>,
    inline: bool,
}
impl NativeMemory for Memory {
    fn reserve(&self, bytes: usize) -> crate::Result<Box<dyn NativeAllocation>> {
        let inline =
            self.0.inline_bytes.load(SeqCst) != 0 && bytes == self.0.inline_bytes.load(SeqCst);
        if inline && self.0.inline_refuse.load(SeqCst) {
            return Err(crate::Error::msg("original inline admission refused"));
        }
        if inline {
            self.0.inline_active.fetch_add(1, SeqCst);
            WATCH.with(|cell| {
                let mut watch = cell.get();
                watch.armed = true;
                cell.set(watch);
            });
        }
        Ok(Box::new(Allocation {
            state: self.0.clone(),
            inline,
        }))
    }
}
impl Drop for Memory {
    fn drop(&mut self) {
        self.0.factory_dropped.fetch_add(1, SeqCst);
    }
}
impl NativeAllocation for Allocation {
    fn allocated(&mut self) {
        if self.inline {
            self.state.inline_confirmed.fetch_add(1, SeqCst);
        }
    }
}
impl Drop for Allocation {
    fn drop(&mut self) {
        if self.inline {
            self.state
                .inline_physical_first
                .store(WATCH.with(|cell| cell.get().freed), SeqCst);
            self.state.inline_active.fetch_sub(1, SeqCst);
            self.state.inline_released.fetch_add(1, SeqCst);
        }
    }
}
struct BindingOwner(Arc<State>);
impl NativeAllocation for BindingOwner {
    fn allocated(&mut self) {}
}
impl Drop for BindingOwner {
    fn drop(&mut self) {
        self.0.binding_released.fetch_add(1, SeqCst);
    }
}

#[derive(Clone, Copy)]
enum Mode {
    Ready,
    Pending,
    Error,
    PanicDrop,
}
struct Callback<'a> {
    accessor: &'a Accessor<()>,
    state: Arc<State>,
    mode: Mode,
    payload: [u8; 8192],
}
impl Future for Callback<'_> {
    type Output = crate::Result<(u32,)>;
    fn poll(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.get_mut();
        this.state.polls.fetch_add(1, SeqCst);
        std::hint::black_box(&this.payload);
        this.accessor.with(|_| ());
        match this.mode {
            Mode::Ready => Poll::Ready(Ok((42,))),
            Mode::Error => Poll::Ready(Err(crate::Error::msg("original callback error"))),
            Mode::Pending | Mode::PanicDrop => Poll::Pending,
        }
    }
}
impl Drop for Callback<'_> {
    fn drop(&mut self) {
        assert_eq!(self.state.inline_active.load(SeqCst), 1);
        let address = self as *mut Self as usize;
        self.state.callback_address.store(address, SeqCst);
        self.state.drops.fetch_add(1, SeqCst);
        if matches!(self.mode, Mode::PanicDrop) {
            panic!("original callback destructor panic");
        }
    }
}

fn reset_watch() {
    WATCH.with(|cell| cell.set(Watch::default()));
}

struct InlineHandler {
    state: Arc<State>,
    mode: Mode,
}
impl InlineConcurrentHost<(), (), (u32,)> for InlineHandler {
    fn invoke<'a>(
        &'a self,
        accessor: &'a Accessor<()>,
        (): (),
    ) -> impl Future<Output = crate::Result<(u32,)>> + Send + 'a {
        self.state.factory.fetch_add(1, SeqCst);
        Callback {
            accessor,
            state: self.state.clone(),
            mode: self.mode,
            payload: [7; 8192],
        }
    }
}

fn boxed_callback<'a>(
    accessor: &'a Accessor<()>,
    state: Arc<State>,
    mode: Mode,
) -> Pin<Box<dyn Future<Output = crate::Result<(u32,)>> + Send + 'a>> {
    Box::pin(Callback {
        accessor,
        state,
        mode,
        payload: [7; 8192],
    })
}

async fn inline_instance(
    mode: Mode,
) -> (
    Store<()>,
    crate::component::TypedFunc<(), (u32,)>,
    Arc<State>,
    usize,
    usize,
) {
    reset_watch();
    let state = Arc::new(State::default());
    let mut config = Config::new();
    config
        .wasm_component_model(true)
        .wasm_component_model_async(true)
        .concurrency_support(true);
    let engine = Engine::new(&config).unwrap();
    let component = Component::new(&engine, COMPONENT).unwrap();
    let binding =
        NativeMemoryBinding::new(Memory(state.clone()), Box::new(BindingOwner(state.clone())));
    let mut store = Store::try_new_with_memory_binding(&engine, (), binding).unwrap();
    let handler = Arc::new(InlineHandler {
        state: state.clone(),
        mode,
    });
    // The identical monomorphized wrapper is passed by the real registration
    // to HostFuture::new; its concrete size includes the callback state.
    let measured = store.as_context_mut().wrap_inline_call(handler.clone(), ());
    let inline_size = std::mem::size_of_val(&measured);
    drop(measured);
    let legacy_state = state.clone();
    let legacy = store
        .as_context_mut()
        .wrap_call(move |access| boxed_callback(access, legacy_state.clone(), mode));
    let legacy_size = std::mem::size_of_val(&legacy);
    drop(legacy);
    assert!(inline_size > std::mem::size_of::<Callback<'static>>());
    assert!(inline_size > legacy_size);
    state.inline_bytes.store(inline_size, SeqCst);
    WATCH.with(|cell| {
        let mut watch = cell.get();
        watch.size = inline_size;
        cell.set(watch);
    });
    let mut linker = Linker::new(&engine);
    linker
        .root()
        .func_wrap_concurrent_inline(
            "wait",
            InlineHandler {
                state: state.clone(),
                mode,
            },
        )
        .unwrap();
    let instance = linker
        .instantiate_async(&mut store, &component)
        .await
        .unwrap();
    let function = instance.get_typed_func(&mut store, "run").unwrap();
    (store, function, state, inline_size, legacy_size)
}

fn assert_inline_allocation_retired(state: &State, bytes: usize) {
    let base = WATCH.with(|cell| cell.get().pointer);
    let callback = state.callback_address.load(SeqCst);
    assert_ne!(base, 0);
    assert!(
        callback >= base && callback < base + bytes,
        "callback must be inside the admitted outer Box"
    );
    assert_eq!(state.inline_confirmed.load(SeqCst), 1);
    assert_eq!(state.inline_active.load(SeqCst), 0);
    assert_eq!(state.inline_released.load(SeqCst), 1);
    assert!(state.inline_physical_first.load(SeqCst));
}

#[tokio::test]
async fn real_inline_component_prepays_exact_containing_box_and_preserves_result() {
    let _serial = TEST_LOCK.lock().unwrap();
    for mode in [Mode::Ready, Mode::Error] {
        let (mut store, function, state, inline, legacy) = inline_instance(mode).await;
        let result = function.call_async(&mut store, ()).await;
        match mode {
            Mode::Ready => assert_eq!(result.unwrap(), (42,)),
            Mode::Error => {
                assert!(format!("{:#}", result.unwrap_err()).contains("original callback error"))
            }
            _ => unreachable!(),
        }
        assert_eq!(state.factory.load(SeqCst), 1);
        assert_eq!(state.drops.load(SeqCst), 1);
        assert_inline_allocation_retired(&state, inline);
        println!(
            "INLINE_CALLBACK_LAYOUT_V1 outer={} legacy_outer={} legacy_callback={}",
            inline,
            legacy,
            std::mem::size_of::<Callback<'static>>()
        );
        drop(store);
        assert_eq!(state.factory_dropped.load(SeqCst), 1);
        assert_eq!(state.binding_released.load(SeqCst), 1);
    }
}

#[tokio::test]
async fn real_inline_refuses_at_original_outer_admission_before_callback() {
    let _serial = TEST_LOCK.lock().unwrap();
    let (mut store, function, state, _, _) = inline_instance(Mode::Ready).await;
    state.inline_refuse.store(true, SeqCst);
    let error = function.call_async(&mut store, ()).await.unwrap_err();
    assert!(format!("{error:#}").contains("original inline admission refused"));
    assert_eq!(state.factory.load(SeqCst), 0);
    assert_eq!(state.polls.load(SeqCst), 0);
    assert_eq!(state.inline_active.load(SeqCst), 0);
    assert_eq!(state.inline_confirmed.load(SeqCst), 0);
    assert_eq!(state.drops.load(SeqCst), 0);
    drop(store);
    assert_eq!(state.factory_dropped.load(SeqCst), 1);
}

#[tokio::test]
async fn real_inline_cancel_and_destructor_panic_preserve_physical_first_refund() {
    let _serial = TEST_LOCK.lock().unwrap();
    for mode in [Mode::Pending, Mode::PanicDrop] {
        let (mut store, function, state, inline, _) = inline_instance(mode).await;
        let mut call = Box::pin(function.call_async(&mut store, ()));
        assert!(
            call.as_mut()
                .poll(&mut Context::from_waker(Waker::noop()))
                .is_pending()
        );
        assert_eq!(state.inline_active.load(SeqCst), 1);
        let call_result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(call)));
        let store_result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(store)));
        assert_eq!(
            call_result.is_err() || store_result.is_err(),
            matches!(mode, Mode::PanicDrop)
        );
        assert_eq!(state.drops.load(SeqCst), 1);
        assert_inline_allocation_retired(&state, inline);
    }
}

#[tokio::test]
async fn real_inline_cancellation_cannot_credit_a_different_live_store() {
    let _serial = TEST_LOCK.lock().unwrap();
    let (mut first, first_fn, first_state, first_bytes, _) = inline_instance(Mode::Pending).await;
    let (mut second, second_fn, second_state, _, _) = inline_instance(Mode::Pending).await;
    let mut first_call = Box::pin(first_fn.call_async(&mut first, ()));
    let mut second_call = Box::pin(second_fn.call_async(&mut second, ()));
    assert!(
        first_call
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop()))
            .is_pending()
    );
    assert!(
        second_call
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop()))
            .is_pending()
    );
    assert_eq!(first_state.inline_active.load(SeqCst), 1);
    assert_eq!(second_state.inline_active.load(SeqCst), 1);
    drop(first_call);
    drop(first);
    assert_inline_allocation_retired(&first_state, first_bytes);
    assert_eq!(second_state.inline_active.load(SeqCst), 1);
    assert_eq!(second_state.inline_released.load(SeqCst), 0);
    drop(second_call);
    drop(second);
    assert_eq!(second_state.inline_active.load(SeqCst), 0);
    assert_eq!(second_state.inline_released.load(SeqCst), 1);
    assert_eq!(first_state.factory_dropped.load(SeqCst), 1);
    assert_eq!(second_state.factory_dropped.load(SeqCst), 1);
}
