//! Planned actual-engine controls for only the concrete host callback-future Box.
//! Callback-owned boxes, typed values and scheduler frames remain outside scope.
use super::native_store_tests::{requests, store, Data, Observations, MIB, OWNER};
use super::native_table_tests::{budget, denial};
use std::future::{poll_fn, Future};
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll, Waker};
use wasmtime::component::{Component, Instance, Linker, TypedFunc, Val};
use wasmtime::{Config, Engine, Store};

const COMPONENT: &[u8] = include_bytes!("native-host-future.wasm");

// Explicit test-controller storage is not activation-owned memory evidence.
#[derive(Default)]
struct Gate {
    polls: AtomicUsize,
    ready: AtomicBool,
    fail: AtomicBool,
    waker: Mutex<Option<Waker>>,
}
impl Gate {
    async fn wait(&self) -> wasmtime::Result<()> {
        poll_fn(|cx| {
            self.polls.fetch_add(1, Ordering::SeqCst);
            if !self.ready.load(Ordering::SeqCst) {
                *self.waker.lock().unwrap() = Some(cx.waker().clone());
                return Poll::Pending;
            }
            if self.fail.load(Ordering::SeqCst) {
                Poll::Ready(Err(wasmtime::Error::msg(
                    "native-host-future-original-callback-error",
                )))
            } else {
                Poll::Ready(Ok(()))
            }
        })
        .await
    }
    fn finish(&self) {
        self.ready.store(true, Ordering::SeqCst);
        if let Some(waker) = self.waker.lock().unwrap().take() {
            waker.wake();
        }
    }
}

fn engine() -> Engine {
    Engine::new(
        Config::new()
            .wasm_component_model(true)
            .wasm_component_model_async(true)
            .concurrency_support(true)
            .consume_fuel(true),
    )
    .unwrap()
}

fn linker<T: 'static>(engine: &Engine, gate: &Arc<Gate>, dynamic: bool) -> Linker<T> {
    let mut linker = Linker::new(engine);
    let gate = gate.clone();
    if dynamic {
        linker
            .root()
            .func_new_concurrent("wait", move |_, _, params, results| {
                assert!(params.is_empty());
                assert_eq!(results.len(), 1);
                let gate = gate.clone();
                Box::pin(async move {
                    gate.wait().await?;
                    results[0] = Val::U32(42);
                    Ok(())
                })
            })
            .unwrap();
    } else {
        linker
            .root()
            .func_wrap_concurrent("wait", move |_, (): ()| {
                let gate = gate.clone();
                Box::pin(async move {
                    gate.wait().await?;
                    Ok((42u32,))
                })
            })
            .unwrap();
    }
    linker
}

async fn instance(
    linker: &Linker<Data>,
    component: &Component,
    store: &mut Store<Data>,
) -> (Instance, TypedFunc<(), (u32,)>) {
    store.set_fuel(1_000_000_000).unwrap();
    let instance = linker
        .instantiate_async(&mut *store, component)
        .await
        .unwrap();
    let function = instance.get_typed_func(&mut *store, "run").unwrap();
    (instance, function)
}

#[tokio::test]
async fn actual_host_future_typed_and_dynamic_boxes_retain_original_memory_while_pending() {
    let engine = engine();
    let component = Component::new(&engine, COMPONENT).unwrap();
    for dynamic in [false, true] {
        let original = budget(MIB);
        let observed = Arc::new(Observations::default());
        let mut store = store(&engine, &original, &observed).unwrap();
        let gate = Arc::new(Gate::default());
        let linker = linker(&engine, &gate, dynamic);
        let (_, function) = instance(&linker, &component, &mut store).await;
        let retained = original.host_memory_bytes();
        let before = requests(&observed).len();
        let mut call = Box::pin(function.call_async(&mut store, ()));
        assert!(call
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop()))
            .is_pending());
        assert!(gate.polls.load(Ordering::SeqCst) > 0);
        let allocated = requests(&observed);
        assert_eq!(allocated.len(), before + 1);
        assert!(allocated[before] > 0);
        assert_eq!(
            original.host_memory_bytes(),
            retained + allocated[before] as u64 + OWNER
        );
        gate.finish();
        // This concurrent typed API performs result lifting/post-return itself.
        assert_eq!(call.await.unwrap(), (42,));
        assert_eq!(original.host_memory_bytes(), retained);
        assert!(store.get_fuel().unwrap() < 1_000_000_000);
        drop(store);
        assert_eq!(observed.factory_drops.load(Ordering::SeqCst), 1);
        assert_eq!(original.host_memory_bytes(), 0);
        assert_eq!(original.outstanding_reservations(), 0);
    }
}

struct Padding {
    _bytes: Vec<u8>,
    _owner: Box<dyn wasmtime::NativeAllocation>,
}

#[tokio::test]
async fn actual_host_future_refusal_preserves_original_error_and_fresh_budget_reuse() {
    let engine = engine();
    let component = Component::new(&engine, COMPONENT).unwrap();
    for dynamic in [false, true] {
        let original = budget(MIB);
        let observed = Arc::new(Observations::default());
        let mut first = store(&engine, &original, &observed).unwrap();
        let gate = Arc::new(Gate::default());
        let linker = linker(&engine, &gate, dynamic);
        let (_, function) = instance(&linker, &component, &mut first).await;
        let before = requests(&observed).len();
        let padding = Arc::new(Mutex::new(None::<Padding>));
        let consumed = Arc::new(AtomicU64::new(0));
        let requested = Arc::new(AtomicU64::new(0));
        let kept = padding.clone();
        let kept_consumed = consumed.clone();
        let kept_requested = requested.clone();
        let invocation = original.clone();
        // Observe the actual concrete Future request. Real padding plus its
        // existing owner makes the original admission exceed MIB by one byte.
        // No fake error, summed historic prefix or increased grant is used.
        observed.before_request(before + 1, move |bytes| {
            let request = bytes as u64 + OWNER;
            let bytes = MIB - invocation.host_memory_bytes() - request + 1 - OWNER;
            let mut owner = crate::native_tables::reserve(&invocation, bytes as usize)
                .unwrap()
                .unwrap();
            let allocation = vec![0u8; bytes as usize];
            assert_eq!(allocation.capacity(), bytes as usize);
            owner.allocated();
            *kept.lock().unwrap() = Some(Padding {
                _bytes: allocation,
                _owner: owner,
            });
            kept_consumed.store(invocation.host_memory_bytes(), Ordering::SeqCst);
            kept_requested.store(request, Ordering::SeqCst);
        });
        let error = function.call_async(&mut first, ()).await.unwrap_err();
        denial(
            &error,
            MIB,
            consumed.load(Ordering::SeqCst),
            requested.load(Ordering::SeqCst),
        );
        assert_eq!(gate.polls.load(Ordering::SeqCst), 0);
        assert_eq!(requests(&observed).len(), before + 1);
        assert_eq!(
            consumed.load(Ordering::SeqCst) + requested.load(Ordering::SeqCst),
            MIB + 1
        );
        drop(error);
        drop(padding.lock().unwrap().take());
        drop(first);
        assert_eq!(original.host_memory_bytes(), 0);
        assert_eq!(original.outstanding_reservations(), 0);
        // A trapped component is not reused; a fresh Store uses the unchanged
        // original grant and succeeds after the real refused owners are gone.
        let mut fresh = store(&engine, &original, &observed).unwrap();
        let (_, function) = instance(&linker, &component, &mut fresh).await;
        gate.finish();
        assert_eq!(function.call_async(&mut fresh, ()).await.unwrap(), (42,));
        drop(fresh);
        assert_eq!(original.host_memory_bytes(), 0);
        assert_eq!(original.outstanding_reservations(), 0);
    }
}

#[tokio::test]
async fn actual_host_future_cancellation_cannot_credit_another_live_store() {
    let engine = engine();
    let component = Component::new(&engine, COMPONENT).unwrap();
    let a = budget(MIB);
    let b = budget(MIB);
    let observed_a = Arc::new(Observations::default());
    let observed_b = Arc::new(Observations::default());
    let mut first = store(&engine, &a, &observed_a).unwrap();
    let mut second = store(&engine, &b, &observed_b).unwrap();
    let gate_a = Arc::new(Gate::default());
    let gate_b = Arc::new(Gate::default());
    let linker_a = linker(&engine, &gate_a, false);
    let linker_b = linker(&engine, &gate_b, false);
    let (_, first_func) = instance(&linker_a, &component, &mut first).await;
    let (_, second_func) = instance(&linker_b, &component, &mut second).await;
    let baseline_a = a.host_memory_bytes();
    let baseline_b = b.host_memory_bytes();
    let mut first_call = Box::pin(first_func.call_async(&mut first, ()));
    let mut second_call = Box::pin(second_func.call_async(&mut second, ()));
    let mut context = Context::from_waker(Waker::noop());
    assert!(first_call.as_mut().poll(&mut context).is_pending());
    assert!(second_call.as_mut().poll(&mut context).is_pending());
    assert!(a.host_memory_bytes() > baseline_a);
    assert!(b.host_memory_bytes() > baseline_b);
    let live_b = b.host_memory_bytes();
    drop(first_call);
    // Physical cancellation may already destroy the first callback. Do not
    // demand artificial retention after the actual Future allocation dies.
    assert!(a.host_memory_bytes() >= baseline_a);
    drop(first);
    assert_eq!(a.host_memory_bytes(), 0);
    assert_eq!(b.host_memory_bytes(), live_b);
    drop(second_call);
    drop(second);
    assert_eq!(b.host_memory_bytes(), 0);
    assert_eq!(a.outstanding_reservations(), 0);
    assert_eq!(b.outstanding_reservations(), 0);
}

#[tokio::test]
async fn actual_host_future_callback_error_is_unchanged_and_its_box_retires() {
    let engine = engine();
    let component = Component::new(&engine, COMPONENT).unwrap();
    for dynamic in [false, true] {
        let original = budget(MIB);
        let observed = Arc::new(Observations::default());
        let mut store = store(&engine, &original, &observed).unwrap();
        let gate = Arc::new(Gate::default());
        gate.fail.store(true, Ordering::SeqCst);
        gate.finish();
        let linker = linker(&engine, &gate, dynamic);
        let (_, function) = instance(&linker, &component, &mut store).await;
        let retained = original.host_memory_bytes();
        let before = requests(&observed).len();
        let error = function.call_async(&mut store, ()).await.unwrap_err();
        assert!(format!("{error:#}").contains("native-host-future-original-callback-error"));
        assert!(gate.polls.load(Ordering::SeqCst) > 0);
        let allocated = requests(&observed);
        assert_eq!(allocated.len(), before + 1);
        assert!(
            original
                .snapshot_at(std::time::Instant::now())
                .peak_memory_bytes
                >= retained + allocated[before] as u64 + OWNER
        );
        drop(error);
        drop(store);
        assert_eq!(original.host_memory_bytes(), 0);
        assert_eq!(original.outstanding_reservations(), 0);
    }
}

#[tokio::test]
async fn actual_host_future_legacy_unaccounted_embedding_keeps_original_scalar_result() {
    let engine = engine();
    let component = Component::new(&engine, COMPONENT).unwrap();
    for dynamic in [false, true] {
        let mut store = Store::new(&engine, ());
        store.set_fuel(1_000_000_000).unwrap();
        let gate = Arc::new(Gate::default());
        gate.finish();
        let linker = linker(&engine, &gate, dynamic);
        let instance = linker
            .instantiate_async(&mut store, &component)
            .await
            .unwrap();
        let function = instance
            .get_typed_func::<(), (u32,)>(&mut store, "run")
            .unwrap();
        assert_eq!(function.call_async(&mut store, ()).await.unwrap(), (42,));
        assert!(store.get_fuel().unwrap() < 1_000_000_000);
    }
}
