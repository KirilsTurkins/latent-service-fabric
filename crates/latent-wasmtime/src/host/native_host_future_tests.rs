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
        // SOURCE-DERIVED v16 cold callbackless order, to be exercised here:
        // GuestCall, stub, ready, ORIGINAL callback Box, result reservation,
        // concrete outer Box, PushFuture, prepared unordered Task.
        // Publication retires entry7, not result/outer/call/task/header owners.
        assert_eq!(allocated.len(), before + 8);
        assert!(allocated[before..].iter().all(|bytes| *bytes > 0));
        assert_eq!(allocated[before], allocated[before + 6]);
        assert_eq!(allocated[before + 1], allocated[before + 7]);
        let live_call = [0, 1, 2, 3, 4, 5, 7]
            .iter()
            .map(|index| allocated[before + index] as u64 + OWNER)
            .sum::<u64>();
        let shared_headers = allocated[before + 1..before + 3]
            .iter()
            .map(|bytes| *bytes as u64 + OWNER)
            .sum::<u64>();
        assert_eq!(original.host_memory_bytes(), retained + live_call);
        gate.finish();
        // This concurrent typed API performs result lifting/post-return itself.
        assert_eq!(call.await.unwrap(), (42,));
        // Completed Task and both call entries are gone. The SAME set's stub
        // and ready headers intentionally survive until actual Store teardown.
        assert_eq!(original.host_memory_bytes(), retained + shared_headers);
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
        // Cold requests1..3 fund GuestCall and lazy stub/ready headers. The
        // FOURTH is the ORIGINAL concrete callback Box, before PushFuture/Task.
        // Source order, never byte size, identifies that original owner.
        // Real padding plus its
        // existing owner makes the original admission exceed MIB by one byte.
        // No fake error, summed historic prefix or increased grant is used.
        observed.before_request(before + 4, move |bytes| {
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
        assert_eq!(requests(&observed).len(), before + 4);
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
    let before_a = requests(&observed_a).len();
    let before_b = requests(&observed_b).len();
    let mut first_call = Box::pin(first_func.call_async(&mut first, ()));
    let mut second_call = Box::pin(second_func.call_async(&mut second, ()));
    let mut context = Context::from_waker(Waker::noop());
    assert!(first_call.as_mut().poll(&mut context).is_pending());
    assert!(second_call.as_mut().poll(&mut context).is_pending());
    assert!(a.host_memory_bytes() > baseline_a);
    assert!(b.host_memory_bytes() > baseline_b);
    let allocated_a = requests(&observed_a);
    let allocated_b = requests(&observed_b);
    let cold_a = &allocated_a[before_a..];
    let cold_b = &allocated_b[before_b..];
    for cold in [cold_a, cold_b] {
        // SOURCE-DERIVED v16 cold eight-request sequence as above:
        // GuestCall, stub, ready, callback Box, result, outer, PushFuture, Task.
        assert_eq!(cold.len(), 8);
        assert!(cold.iter().all(|bytes| *bytes > 0));
        assert_eq!(cold[0], cold[6]);
        assert_eq!(cold[1], cold[7]);
    }
    let escaped_a = cold_a[7] as u64 + cold_a[2] as u64 + 2 * OWNER;
    let escaped_b = cold_b[7] as u64 + cold_b[2] as u64 + 2 * OWNER;
    let live_b = b.host_memory_bytes();
    let live_b_reservations = b.outstanding_reservations();
    drop(first_call);
    // Physical cancellation may already destroy the first callback. Do not
    // demand artificial retention after the actual Future allocation dies.
    assert!(a.host_memory_bytes() >= baseline_a);
    drop(first);
    // The test Gate deliberately escaped a real Task waker. Its Task and weak
    // ready-queue backing remain paid after Store destruction, not refunded.
    assert_eq!(a.host_memory_bytes(), escaped_a);
    assert_eq!(b.host_memory_bytes(), live_b);
    assert_eq!(b.outstanding_reservations(), live_b_reservations);
    gate_a.finish(); // Real late wake consumes that SAME escaped waker.
    assert_eq!(a.host_memory_bytes(), 0);
    assert_eq!(a.outstanding_reservations(), 0);
    assert_eq!(b.host_memory_bytes(), live_b);
    assert_eq!(b.outstanding_reservations(), live_b_reservations);
    assert_eq!(requests(&observed_a), allocated_a);
    assert_eq!(requests(&observed_b), allocated_b);
    println!(
        "LSF_CANCELLED_HOST_FUTURE_ESCAPED_V1 store=a task-bytes={} ready-bytes={} owner-escrow={} retained={} late-wake-admissions=0 foreign-unchanged=true",
        cold_a[7], cold_a[2], OWNER, escaped_a
    );
    drop(second_call);
    drop(second);
    assert_eq!(b.host_memory_bytes(), escaped_b);
    assert_eq!(a.host_memory_bytes(), 0);
    gate_b.finish();
    assert_eq!(b.host_memory_bytes(), 0);
    assert_eq!(a.host_memory_bytes(), 0);
    assert_eq!(a.outstanding_reservations(), 0);
    assert_eq!(b.outstanding_reservations(), 0);
    assert_eq!(requests(&observed_a), allocated_a);
    assert_eq!(requests(&observed_b), allocated_b);
    println!(
        "LSF_CANCELLED_HOST_FUTURE_ESCAPED_V1 store=b task-bytes={} ready-bytes={} owner-escrow={} retained={} late-wake-admissions=0 foreign-unchanged=true",
        cold_b[7], cold_b[2], OWNER, escaped_b
    );
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
        // Immediate callback error still follows all eight pre-poll admissions;
        // the unused result reservation has no Box to confirm on input Err.
        assert_eq!(allocated.len(), before + 8);
        assert!(allocated[before..].iter().all(|bytes| *bytes > 0));
        let result_bytes = if dynamic {
            std::alloc::Layout::new::<Vec<Val>>().size()
        } else {
            std::alloc::Layout::new::<(u32,)>().size()
        };
        assert_eq!(allocated[before + 4], result_bytes);
        let live_call = allocated[before..]
            .iter()
            .map(|bytes| *bytes as u64 + OWNER)
            .sum::<u64>();
        // On input Err, result backing was never allocated/confirmed. Its
        // real boxed owner's OWNER escrow DID exist and stays in this sum.
        let physical_call = live_call - result_bytes as u64;
        assert!(
            original
                .snapshot_at(std::time::Instant::now())
                .peak_memory_bytes
                >= retained + physical_call
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

// Test-controller synchronization is outside the invocation backing claim.
struct AccessorProbeTask {
    gate: Arc<Gate>,
    entered: Arc<AtomicBool>,
    dropped: Arc<AtomicUsize>,
}
impl wasmtime::component::AccessorTask<Data> for AccessorProbeTask {
    fn run(
        self,
        _: &wasmtime::component::Accessor<Data>,
    ) -> impl Future<Output = wasmtime::Result<()>> + Send {
        // Observe the actual AccessorTask method call, not only its future poll.
        self.entered.store(true, Ordering::SeqCst);
        async move { self.gate.wait().await }
    }
}
impl Drop for AccessorProbeTask {
    fn drop(&mut self) {
        self.dropped.fetch_add(1, Ordering::SeqCst);
    }
}

#[tokio::test]
async fn actual_accessor_spawn_outer_box_refuses_before_run_and_retires_after_pending() {
    let engine = engine();
    let original = budget(MIB);
    let observed = Arc::new(Observations::default());
    let gate = Arc::new(Gate::default());
    let entered = Arc::new(AtomicBool::new(false));
    let dropped = Arc::new(AtomicUsize::new(0));
    let mut first = store(&engine, &original, &observed).unwrap();
    // The ordinary driver initializes the selected set's two shared headers.
    // No child task or task.run call is needed to warm that actual owner scope.
    first.run_concurrent(async |_| ()).await.unwrap();
    let before = requests(&observed).len();
    let padding = Arc::new(Mutex::new(None::<Padding>));
    let consumed = Arc::new(AtomicU64::new(0));
    let requested = Arc::new(AtomicU64::new(0));
    let kept = padding.clone();
    let kept_consumed = consumed.clone();
    let kept_requested = requested.clone();
    let invocation = original.clone();
    // With shared headers warm: queue, TaskSlot, JoinState, then this exact
    // concrete outer Box. No task.run or user poll precedes request four.
    observed.before_request(before + 4, move |bytes| {
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
    let error = first
        .spawn(AccessorProbeTask {
            gate: gate.clone(),
            entered: entered.clone(),
            dropped: dropped.clone(),
        })
        .err()
        .expect("original outer-Box admission refusal");
    denial(
        &error,
        MIB,
        consumed.load(Ordering::SeqCst),
        requested.load(Ordering::SeqCst),
    );
    assert_eq!(requests(&observed).len(), before + 4);
    assert_eq!(
        consumed.load(Ordering::SeqCst) + requested.load(Ordering::SeqCst),
        MIB + 1
    );
    assert!(!entered.load(Ordering::SeqCst));
    assert_eq!(gate.polls.load(Ordering::SeqCst), 0);
    assert_eq!(dropped.load(Ordering::SeqCst), 1);
    drop(error);
    drop(padding.lock().unwrap().take());
    drop(first);
    assert_eq!(original.host_memory_bytes(), 0);
    assert_eq!(original.outstanding_reservations(), 0);

    // Fresh Store, SAME original budget; no component/compiler fixture needed.
    let mut fresh = store(&engine, &original, &observed).unwrap();
    fresh.run_concurrent(async |_| ()).await.unwrap();
    let baseline = original.host_memory_bytes();
    let before = requests(&observed).len();
    let handle = fresh
        .spawn(AccessorProbeTask {
            gate: gate.clone(),
            entered: entered.clone(),
            dropped: dropped.clone(),
        })
        .unwrap();
    assert!(!entered.load(Ordering::SeqCst));
    let allocated = requests(&observed);
    assert_eq!(allocated.len(), before + 4);
    assert!(allocated[before..].iter().all(|bytes| *bytes > 0));
    let all_four = allocated[before..]
        .iter()
        .map(|bytes| *bytes as u64 + OWNER)
        .sum::<u64>();
    assert_eq!(original.host_memory_bytes(), baseline + all_four);
    let mut drive = Box::pin(fresh.run_concurrent(async |_| handle.await));
    assert!(drive
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    assert!(entered.load(Ordering::SeqCst));
    assert!(gate.polls.load(Ordering::SeqCst) > 0);
    // The published queue node may have retired. TaskSlot, JoinState and the
    // genuinely pending outer Box must all still be physically owned.
    let pending = allocated[before + 1..]
        .iter()
        .map(|bytes| *bytes as u64 + OWNER)
        .sum::<u64>();
    assert!(original.host_memory_bytes() >= baseline + pending);
    assert_eq!(dropped.load(Ordering::SeqCst), 1);
    gate.finish();
    drive.await.unwrap();
    assert_eq!(dropped.load(Ordering::SeqCst), 2);
    // Weak/task-header tails may remain paid until physical set teardown.
    drop(fresh);
    assert_eq!(observed.factory_drops.load(Ordering::SeqCst), 2);
    assert_eq!(original.host_memory_bytes(), 0);
    assert_eq!(original.outstanding_reservations(), 0);
}

#[tokio::test]
async fn actual_sync_lower_result_box_refuses_before_poll_and_fresh_budget_reuses() {
    let engine = engine();
    let component = Component::new(&engine, COMPONENT).unwrap();
    let original = budget(MIB);
    let observed = Arc::new(Observations::default());
    let mut first = store(&engine, &original, &observed).unwrap();
    let gate = Arc::new(Gate::default());
    // Existing component's typed wait returns (u32,), not ABI ValRaw storage.
    let linker = linker(&engine, &gate, false);
    let (_, function) = instance(&linker, &component, &mut first).await;
    let before = requests(&observed).len();
    let padding = Arc::new(Mutex::new(None::<Padding>));
    let consumed = Arc::new(AtomicU64::new(0));
    let requested = Arc::new(AtomicU64::new(0));
    let kept = padding.clone();
    let kept_consumed = consumed.clone();
    let kept_requested = requested.clone();
    let invocation = original.clone();
    // SOURCE-DERIVED cold prefix: queue1, stub2, ready3, original Box4,
    // result reservation5. Layout equality is an assertion, never type authority.
    observed.before_request(before + 5, move |bytes| {
        assert_eq!(bytes, std::alloc::Layout::new::<(u32,)>().size());
        assert!(bytes > 0);
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
    assert_eq!(requests(&observed).len(), before + 5);
    assert_eq!(
        requests(&observed)[before + 4],
        std::alloc::Layout::new::<(u32,)>().size()
    );
    assert_eq!(gate.polls.load(Ordering::SeqCst), 0);
    assert_eq!(
        consumed.load(Ordering::SeqCst) + requested.load(Ordering::SeqCst),
        MIB + 1
    );
    drop(error);
    drop(padding.lock().unwrap().take());
    drop(first);
    assert_eq!(observed.factory_drops.load(Ordering::SeqCst), 1);
    assert_eq!(original.host_memory_bytes(), 0);
    assert_eq!(original.outstanding_reservations(), 0);

    // Physical teardown above precedes a fresh Store under the SAME grant.
    let mut fresh = store(&engine, &original, &observed).unwrap();
    let (_, function) = instance(&linker, &component, &mut fresh).await;
    gate.finish();
    assert_eq!(function.call_async(&mut fresh, ()).await.unwrap(), (42,));
    assert!(gate.polls.load(Ordering::SeqCst) > 0);
    drop(fresh);
    assert_eq!(observed.factory_drops.load(Ordering::SeqCst), 2);
    assert_eq!(original.host_memory_bytes(), 0);
    assert_eq!(original.outstanding_reservations(), 0);
}
