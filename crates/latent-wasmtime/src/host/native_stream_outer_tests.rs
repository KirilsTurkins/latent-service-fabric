//! Public stream controls using the ORIGINAL ActivationBudget adapter.
//! Grant: 1MiB / 1B fuel / 5s wall. Not the private64MiB/120s ceiling.
use super::native_store_tests::{
    allocation_rows, core_answer, requests, store, Observations, CORE, MIB, OWNER,
};
use super::native_table_tests::{budget, denial};
use std::future::Future;
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering::SeqCst};
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll, Waker};
use std::time::Duration;
use wasmtime::component::{
    Destination, Source, StreamConsumer, StreamProducer, StreamReader, StreamResult,
};
use wasmtime::{Config, Engine, Module, Store, StoreContextMut};

const FUEL: u64 = 1_000_000_000;
const FAILURE: &str = "original-public-stream-poll-error";

#[derive(Default)]
struct Gate {
    ready: AtomicBool,
    fail: AtomicBool,
    done: AtomicBool,
    polls: AtomicUsize,
    payload: AtomicUsize,
    drops: AtomicUsize,
    waker: Mutex<Option<Waker>>,
    trace: Arc<Mutex<Vec<&'static str>>>,
}
impl Gate {
    fn poll(&self, cx: &mut Context<'_>, who: &'static str) -> Poll<wasmtime::Result<()>> {
        self.trace.lock().unwrap().push(who);
        self.polls.fetch_add(1, SeqCst);
        if !self.ready.load(SeqCst) {
            *self.waker.lock().unwrap() = Some(cx.waker().clone());
            return Poll::Pending;
        }
        self.done.store(true, SeqCst);
        if self.fail.load(SeqCst) {
            Poll::Ready(Err(wasmtime::Error::msg(FAILURE)))
        } else {
            Poll::Ready(Ok(()))
        }
    }
    fn release(&self) {
        self.ready.store(true, SeqCst);
        if let Some(waker) = self.waker.lock().unwrap().take() {
            waker.wake();
        }
    }
}
fn gates() -> (Arc<Gate>, Arc<Gate>) {
    let trace = Arc::new(Mutex::new(Vec::new()));
    let producer = Arc::new(Gate {
        trace: trace.clone(),
        ..Gate::default()
    });
    let consumer = Arc::new(Gate {
        trace,
        ..Gate::default()
    });
    consumer.ready.store(true, SeqCst);
    (producer, consumer)
}
struct Producer(Arc<Gate>);
impl Drop for Producer {
    fn drop(&mut self) {
        self.0.drops.fetch_add(1, SeqCst);
    }
}
impl<D: 'static> StreamProducer<D> for Producer {
    type Item = u8;
    type Buffer = Option<u8>;
    fn poll_produce<'a>(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        _store: StoreContextMut<'a, D>,
        mut dst: Destination<'a, u8, Option<u8>>,
        _finish: bool,
    ) -> Poll<wasmtime::Result<StreamResult>> {
        match self.0.poll(cx, "produce") {
            Poll::Pending => Poll::Pending,
            Poll::Ready(Err(error)) => Poll::Ready(Err(error)),
            Poll::Ready(Ok(())) => {
                dst.set_buffer(Some(42));
                Poll::Ready(Ok(StreamResult::Dropped))
            }
        }
    }
}
struct Consumer(Arc<Gate>);
impl Drop for Consumer {
    fn drop(&mut self) {
        self.0.drops.fetch_add(1, SeqCst);
    }
}
impl<D: 'static> StreamConsumer<D> for Consumer {
    type Item = u8;
    fn poll_consume(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        store: StoreContextMut<D>,
        source: Source<'_, u8>,
        _finish: bool,
    ) -> Poll<wasmtime::Result<StreamResult>> {
        match self.0.poll(cx, "consume") {
            Poll::Pending => Poll::Pending,
            Poll::Ready(Err(error)) => Poll::Ready(Err(error)),
            Poll::Ready(Ok(())) => {
                let mut source = source.as_direct(store);
                assert_eq!(source.remaining(), &[42]);
                source.mark_read(1);
                self.0.payload.store(42, SeqCst);
                Poll::Ready(Ok(StreamResult::Dropped))
            }
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
async fn warm<D: Send + 'static>(store: &mut Store<D>) {
    store.set_fuel(FUEL).unwrap();
    let fuel = store.get_fuel().unwrap();
    store.run_concurrent(async |_| ()).await.unwrap();
    assert_eq!(store.get_fuel().unwrap(), fuel);
}
async fn drive<D: Send + 'static>(
    store: &mut Store<D>,
    producer: &Arc<Gate>,
    consumer: &Arc<Gate>,
) -> wasmtime::Result<()> {
    tokio::time::timeout(
        Duration::from_secs(5),
        store.run_concurrent(async |_| {
            while !consumer.done.load(SeqCst)
                && !(producer.fail.load(SeqCst) && producer.done.load(SeqCst))
            {
                tokio::task::yield_now().await;
            }
        }),
    )
    .await
    .expect("original public5s wall; never private120s")
}
struct Padding {
    _bytes: Vec<u8>,
    _owner: Box<dyn wasmtime::NativeAllocation>,
}

#[tokio::test]
async fn actual_stream_host_ready_refusals_precede_consumer_factory_and_polls() {
    let engine = engine();
    // Existing fixed native-store fixture; no WAT/compiler-tool invocation.
    let core = Module::new(&engine, CORE).unwrap();
    for local in 1..=5 {
        let original = budget(MIB);
        let observed = Arc::new(Observations::default());
        let mut first = store(&engine, &original, &observed).unwrap();
        warm(&mut first).await;
        let (producer, consumer) = gates();
        let reader = StreamReader::new(&mut first, Producer(producer.clone())).unwrap();
        let before = requests(&observed).len();
        let padding = Arc::new(Mutex::new(None::<Padding>));
        let consumed = Arc::new(AtomicU64::new(0));
        let requested = Arc::new(AtomicU64::new(0));
        let kept = padding.clone();
        let kept_consumed = consumed.clone();
        let kept_requested = requested.clone();
        let invocation = original.clone();
        // Source-owned LOCAL queue -> Task -> outer -> pinned C -> shared C cell.
        // Warmed shared headers and the original real-budget padding stay unchanged.
        observed.before_request(before + local, move |bytes| {
            let request = bytes as u64 + OWNER;
            let payload = MIB - invocation.host_memory_bytes() - request + 1 - OWNER;
            let mut owner = crate::native_tables::reserve(&invocation, payload as usize)
                .unwrap()
                .unwrap();
            let bytes = vec![0u8; payload as usize];
            assert_eq!(bytes.capacity(), payload as usize);
            owner.allocated();
            *kept.lock().unwrap() = Some(Padding {
                _bytes: bytes,
                _owner: owner,
            });
            kept_consumed.store(invocation.host_memory_bytes(), SeqCst);
            kept_requested.store(request, SeqCst);
        });
        let error = reader
            .pipe(&mut first, Consumer(consumer.clone()))
            .unwrap_err();
        denial(&error, MIB, consumed.load(SeqCst), requested.load(SeqCst));
        assert_eq!(consumed.load(SeqCst) + requested.load(SeqCst), MIB + 1);
        let entries = requests(&observed);
        assert_eq!(entries.len(), before + local);
        if local >= 4 {
            assert_eq!(
                entries[before + 3],
                std::alloc::Layout::new::<Consumer>().size()
            );
        }
        assert_eq!(producer.polls.load(SeqCst), 0);
        assert_eq!(consumer.polls.load(SeqCst), 0);
        println!(
            "STREAM-PUBLIC-REFUSAL local={} global={} original-grant=1048576 polls=0",
            local,
            before + local
        );
        drop(error);
        drop(padding.lock().unwrap().take());
        drop(first);
        producer.release();
        consumer.release();
        assert_eq!(original.host_memory_bytes(), 0);
        assert_eq!(original.outstanding_reservations(), 0);
        let mut fresh = store(&engine, &original, &observed).unwrap();
        fresh.set_fuel(FUEL).unwrap();
        let instance = wasmtime::Instance::new(&mut fresh, &core, &[]).unwrap();
        assert_eq!(core_answer(instance, &mut fresh), 42);
        drop(fresh);
        assert_eq!(original.host_memory_bytes(), 0);
        assert_eq!(original.outstanding_reservations(), 0);
    }
}

#[tokio::test]
async fn actual_stream_host_ready_pending_ready_and_error_preserve_cleanup() {
    let engine = engine();
    // ready / pending-complete / producer-error / consumer-error / pending-drop.
    for mode in 0..5 {
        let original = budget(MIB);
        let observed = Arc::new(Observations::default());
        let other = Arc::new(Observations::default());
        let mut foreign = store(&engine, &original, &other).unwrap();
        warm(&mut foreign).await;
        let foreign_bytes = original.host_memory_bytes();
        let foreign_requests = requests(&other);
        let mut first = store(&engine, &original, &observed).unwrap();
        warm(&mut first).await;
        let (producer, consumer) = gates();
        producer.ready.store(mode != 1 && mode != 4, SeqCst);
        producer.fail.store(mode == 2, SeqCst);
        consumer.fail.store(mode == 3, SeqCst);
        let reader = StreamReader::new(&mut first, Producer(producer.clone())).unwrap();
        let before = requests(&observed).len();
        reader.pipe(&mut first, Consumer(consumer.clone())).unwrap();
        let entries = requests(&observed);
        assert_eq!(entries.len(), before + 5);
        assert_eq!(
            entries[before + 3],
            std::alloc::Layout::new::<Consumer>().size()
        );
        let task_outer_and_consumer = entries[before + 1..before + 5]
            .iter()
            .map(|bytes| *bytes as u64 + OWNER)
            .sum::<u64>();
        let mut running = Box::pin(drive(&mut first, &producer, &consumer));
        if mode == 1 || mode == 4 {
            assert!(running
                .as_mut()
                .poll(&mut Context::from_waker(Waker::noop()))
                .is_pending());
            assert!(producer.polls.load(SeqCst) > 0);
            assert_eq!(consumer.polls.load(SeqCst), 0);
            assert!(original.host_memory_bytes() >= foreign_bytes + task_outer_and_consumer);
        }
        if mode == 4 {
            drop(running);
            drop(first);
            assert!(
                original.host_memory_bytes() > foreign_bytes,
                "genuine escaped waker must keep its Task/ready owners paid"
            );
            let before_wake = requests(&observed).len();
            producer.release();
            consumer.release();
            assert_eq!(requests(&observed).len(), before_wake);
            assert_eq!(original.host_memory_bytes(), foreign_bytes);
        } else {
            if mode == 1 {
                producer.release();
            }
            let result = running.await;
            if mode == 2 || mode == 3 {
                assert!(format!("{:#}", result.unwrap_err()).contains(FAILURE));
            } else {
                result.unwrap();
                assert_eq!(consumer.payload.load(SeqCst), 42);
            }
            // Consumer is still held by TransmitState::HostToHost until the
            // ORIGINAL map cleanup deletes that transmit, including errors.
            // Check before Store destruction, not merely eventual teardown.
            assert_eq!(producer.drops.load(SeqCst), 1);
            assert_eq!(consumer.drops.load(SeqCst), 1);
            drop(first);
            producer.release();
            consumer.release();
            assert_eq!(original.host_memory_bytes(), foreign_bytes);
        }
        assert_eq!(requests(&other), foreign_requests);
        drop(foreign);
        assert_eq!(original.host_memory_bytes(), 0);
        assert_eq!(original.outstanding_reservations(), 0);
        println!(
            "STREAM-PUBLIC-CLEANUP mode={} payload={} foreign-unchanged=true final=0 wall=5",
            mode,
            if mode < 2 { "42" } else { "not-claimed" }
        );
    }
    // None uses its literal old loop. Observe its same producer-before-consumer
    // order independently, without inventing native accounting on None.
    let mut none = Store::new(&engine, ());
    warm(&mut none).await;
    let (producer, consumer) = gates();
    producer.ready.store(true, SeqCst);
    StreamReader::new(&mut none, Producer(producer.clone()))
        .unwrap()
        .pipe(&mut none, Consumer(consumer.clone()))
        .unwrap();
    drive(&mut none, &producer, &consumer).await.unwrap();
    assert_eq!(consumer.payload.load(SeqCst), 42);
    assert_eq!(*producer.trace.lock().unwrap(), ["produce", "consume"]);
    drop(none);
}

// Actual public producer creation/conversion on the ORIGINAL 1MiB/1B/5s
// ActivationBudget adapter, separate from the implementation counter controls.
#[repr(align(256))]
struct FutureValue {
    gate: Arc<Gate>,
    _pinned: std::marker::PhantomPinned,
}
impl Drop for FutureValue {
    fn drop(&mut self) {
        self.gate.drops.fetch_add(1, SeqCst);
    }
}
impl<D: 'static> wasmtime::component::FutureProducer<D> for FutureValue {
    type Item = u8;
    fn poll_produce(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        _store: StoreContextMut<D>,
        _finish: bool,
    ) -> Poll<wasmtime::Result<Option<u8>>> {
        self.gate
            .poll(cx, "produce")
            .map(|result| result.map(|()| Some(42)))
    }
}
fn future_value(gate: &Arc<Gate>) -> FutureValue {
    FutureValue {
        gate: gate.clone(),
        _pinned: std::marker::PhantomPinned,
    }
}
struct FutureSink(Arc<Gate>);
impl<D: 'static> wasmtime::component::FutureConsumer<D> for FutureSink {
    type Item = u8;
    fn poll_consume(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        store: StoreContextMut<D>,
        source: Source<'_, u8>,
        _finish: bool,
    ) -> Poll<wasmtime::Result<()>> {
        match self.0.poll(cx, "consume") {
            Poll::Pending => Poll::Pending,
            Poll::Ready(Err(error)) => Poll::Ready(Err(error)),
            Poll::Ready(Ok(())) => {
                let mut source = source.as_direct(store);
                assert_eq!(source.remaining(), &[42]);
                source.mark_read(1);
                self.0.payload.store(42, SeqCst);
                Poll::Ready(Ok(()))
            }
        }
    }
}

#[tokio::test]
async fn actual_producer_creation_refusals_precede_poll_and_preserve_foreign_store() {
    let engine = engine();
    let core = Module::new(&engine, CORE).unwrap();
    // Stream shared cell; Future exact local adapter Box then shared cell.
    for (future, local) in [(false, 1), (true, 1), (true, 2)] {
        let original = budget(MIB);
        let observed = Arc::new(Observations::default());
        let other = Arc::new(Observations::default());
        let mut foreign = store(&engine, &original, &other).unwrap();
        warm(&mut foreign).await;
        let foreign_bytes = original.host_memory_bytes();
        let foreign_requests = requests(&other);
        let mut first = store(&engine, &original, &observed).unwrap();
        warm(&mut first).await;
        let (producer, _) = gates();
        let before = requests(&observed).len();
        let padding = Arc::new(Mutex::new(None::<Padding>));
        let consumed = Arc::new(AtomicU64::new(0));
        let requested = Arc::new(AtomicU64::new(0));
        let kept = padding.clone();
        let kept_consumed = consumed.clone();
        let kept_requested = requested.clone();
        let invocation = original.clone();
        observed.before_request(before + local, move |bytes| {
            let request = bytes as u64 + OWNER;
            let payload = MIB - invocation.host_memory_bytes() - request + 1 - OWNER;
            let mut owner = crate::native_tables::reserve(&invocation, payload as usize)
                .unwrap()
                .unwrap();
            let bytes = vec![0u8; payload as usize];
            assert_eq!(bytes.capacity(), payload as usize);
            owner.allocated();
            *kept.lock().unwrap() = Some(Padding {
                _bytes: bytes,
                _owner: owner,
            });
            kept_consumed.store(invocation.host_memory_bytes(), SeqCst);
            kept_requested.store(request, SeqCst);
        });
        let error = if future {
            wasmtime::component::FutureReader::new(&mut first, future_value(&producer))
                .err()
                .unwrap()
        } else {
            StreamReader::new(&mut first, Producer(producer.clone()))
                .err()
                .unwrap()
        };
        denial(&error, MIB, consumed.load(SeqCst), requested.load(SeqCst));
        assert_eq!(consumed.load(SeqCst) + requested.load(SeqCst), MIB + 1);
        assert_eq!(requests(&observed).len(), before + local);
        assert_eq!(producer.polls.load(SeqCst), 0);
        assert_eq!(producer.drops.load(SeqCst), 1);
        drop(error);
        drop(padding.lock().unwrap().take());
        drop(first);
        assert_eq!(original.host_memory_bytes(), foreign_bytes);
        assert_eq!(requests(&other), foreign_requests);
        let mut fresh = store(&engine, &original, &observed).unwrap();
        fresh.set_fuel(FUEL).unwrap();
        let instance = wasmtime::Instance::new(&mut fresh, &core, &[]).unwrap();
        assert_eq!(core_answer(instance, &mut fresh), 42);
        drop(fresh);
        assert_eq!(original.host_memory_bytes(), foreign_bytes);
        drop(foreign);
        assert_eq!(original.host_memory_bytes(), 0);
        assert_eq!(original.outstanding_reservations(), 0);
        println!("PRODUCER-PUBLIC-REFUSAL future={future} local={local} global={} polls=0 fresh=42 foreign-unchanged=true final=0 wall=5", before + local);
    }
}

struct EscapingProducer(Arc<Gate>);
impl Drop for EscapingProducer {
    fn drop(&mut self) {
        self.0.drops.fetch_add(1, SeqCst);
    }
}
impl<D: 'static> StreamProducer<D> for EscapingProducer {
    type Item = u8;
    type Buffer = Option<u8>;
    fn poll_produce<'a>(
        self: Pin<&mut Self>,
        _cx: &mut Context<'_>,
        _store: StoreContextMut<'a, D>,
        _dst: Destination<'a, u8, Option<u8>>,
        _finish: bool,
    ) -> Poll<wasmtime::Result<StreamResult>> {
        self.0.polls.fetch_add(1, SeqCst);
        Poll::Pending
    }
    fn try_into(
        me: Pin<Box<Self>>,
        ty: std::any::TypeId,
    ) -> Result<Box<dyn std::any::Any>, Pin<Box<Self>>> {
        if ty == std::any::TypeId::of::<Pin<Box<Self>>>() {
            Ok(Box::new(me))
        } else {
            Err(me)
        }
    }
}

// Native ConcurrentState::new_transmit inserts exactly State/write/read.
// Each now owns its full typed Box; NativeVec's cold entry capacities are
// EXACTLY 1/2/3, not Vec's unaccounted geometric growth. Exercise and retire
// that cold path explicitly before testing allocation-free handle conversion.
const TRANSMIT_VALUES: usize = 3;
pub(super) fn warm_transmit_storage(
    first: &mut Store<super::native_store_tests::Data>,
    original: &latent_core::ActivationBudget,
    observed: &Observations,
) {
    let before = requests(observed).len();
    let baseline = original.host_memory_bytes();
    let (producer, _) = gates();
    let mut reader = StreamReader::new(&mut *first, Producer(producer.clone())).unwrap();
    let rows = allocation_rows(observed);
    let created = &rows[before..];
    // Shared producer cell + two factories, then Box/entry backing per value.
    assert_eq!(created.len(), 3 + 2 * TRANSMIT_VALUES);
    assert!(created.iter().enumerate().all(|(index, row)| {
        row.admitted && row.confirmed && (row.released == (index == 4 || index == 6))
    }));
    // Exact old/new overlap ends after moving entries: capacities1 and2 retire,
    // capacity3 is kept for free-list reuse. Both handle Boxes have same T.
    assert_eq!(created[6].bytes, 2 * created[4].bytes);
    assert_eq!(created[8].bytes, TRANSMIT_VALUES * created[4].bytes);
    assert_eq!(created[5].bytes, created[7].bytes);
    reader.close(&mut *first).unwrap();
    assert_eq!(producer.polls.load(SeqCst), 0);
    assert_eq!(producer.drops.load(SeqCst), 1);
    let retired = allocation_rows(observed);
    for (index, row) in retired[before..].iter().enumerate() {
        assert!(row.admitted && row.confirmed);
        assert_eq!(
            row.released,
            index != 8,
            "only exact entry backing survives close"
        );
    }
    assert_eq!(
        original.host_memory_bytes(),
        baseline + created[8].bytes as u64 + OWNER
    );
}

#[tokio::test]
async fn actual_producer_stream_conversion_reuses_budget_and_preserves_owning_escape() {
    let engine = engine();
    let original = budget(MIB);
    let observed = Arc::new(Observations::default());
    let other = Arc::new(Observations::default());
    let mut foreign = store(&engine, &original, &other).unwrap();
    warm(&mut foreign).await;
    let foreign_bytes = original.host_memory_bytes();
    let foreign_requests = requests(&other);
    let mut first = store(&engine, &original, &observed).unwrap();
    warm(&mut first).await;
    warm_transmit_storage(&mut first, &original, &observed);
    let baseline = original.host_memory_bytes();
    // Repeat create -> ordinary Err -> close on the SAME reusable budget.
    for _ in 0..16 {
        let (producer, _) = gates();
        let before = requests(&observed).len();
        let mut reader = StreamReader::new(&mut first, EscapingProducer(producer.clone())).unwrap();
        assert_eq!(requests(&observed).len(), before + 3 + TRANSMIT_VALUES);
        let live = original.host_memory_bytes();
        for _ in 0..4 {
            reader = reader.try_into::<()>(&mut first).err().unwrap();
            assert_eq!(original.host_memory_bytes(), live);
            assert_eq!(requests(&observed).len(), before + 3 + TRANSMIT_VALUES);
        }
        reader.close(&mut first).unwrap();
        assert_eq!(producer.drops.load(SeqCst), 1);
        assert_eq!(producer.polls.load(SeqCst), 0);
        assert_eq!(original.host_memory_bytes(), baseline);
    }
    let (producer, _) = gates();
    let reader = StreamReader::new(&mut first, EscapingProducer(producer.clone())).unwrap();
    let escaped: Pin<Box<EscapingProducer>> = reader.try_into(&mut first).unwrap();
    assert_eq!(producer.drops.load(SeqCst), 0);
    assert_eq!(
        original.host_memory_bytes(),
        baseline,
        "shared cell retired; escaped P Box explicitly UNPAID"
    );
    drop(first);
    assert_eq!(original.host_memory_bytes(), foreign_bytes);
    assert_eq!(requests(&other), foreign_requests);
    drop(escaped); // Genuine original Box survives Store, without a fake refund.
    assert_eq!(producer.drops.load(SeqCst), 1);
    drop(foreign);
    assert_eq!(original.host_memory_bytes(), 0);
    assert_eq!(original.outstanding_reservations(), 0);
    println!("PRODUCER-PUBLIC-CONVERSION ordinary-Err-reusable=true owning-Ok-preserved=true PBox=unpaid final=0 wall=5");
}

#[tokio::test]
async fn actual_producer_future_any_roundtrip_and_pending_completion_preserve_custody() {
    let engine = engine();
    for selected in [true, false] {
        let original = budget(MIB);
        let observed = Arc::new(Observations::default());
        // The None branch uses the SAME public FutureReader local adapter type.
        let mut first = if selected {
            store(&engine, &original, &observed).unwrap()
        } else {
            // The concrete local Producer<FutureValue> is unchanged on None.
            // Use the original no-factory Store rather than a dummy binding.
            let mut none = Store::new(&engine, ());
            warm(&mut none).await;
            let (producer, consumer) = gates();
            let reader =
                wasmtime::component::FutureReader::new(&mut none, future_value(&producer)).unwrap();
            reader
                .pipe(&mut none, FutureSink(consumer.clone()))
                .unwrap();
            let mut running = Box::pin(drive(&mut none, &producer, &consumer));
            assert!(running
                .as_mut()
                .poll(&mut Context::from_waker(Waker::noop()))
                .is_pending());
            producer.release();
            running.await.unwrap();
            assert_eq!(consumer.payload.load(SeqCst), 42);
            let trace = producer.trace.lock().unwrap();
            assert_eq!(trace.first(), Some(&"produce"));
            assert_eq!(trace.last(), Some(&"consume"));
            assert!(trace[..trace.len() - 1]
                .iter()
                .all(|item| *item == "produce"));
            drop(trace);
            drop(none);
            continue;
        };
        warm(&mut first).await;
        warm_transmit_storage(&mut first, &original, &observed);
        let baseline = original.host_memory_bytes();
        let (producer, _consumer) = gates();
        let before = requests(&observed).len();
        let reader =
            wasmtime::component::FutureReader::new(&mut first, future_value(&producer)).unwrap();
        assert_eq!(requests(&observed).len(), before + 4 + TRANSMIT_VALUES);
        let live = original.host_memory_bytes();
        let any = reader.try_into_future_any(&mut first).unwrap();
        let mut reader = wasmtime::component::FutureReader::<u8>::try_from_future_any(any).unwrap();
        assert_eq!(original.host_memory_bytes(), live);
        assert_eq!(requests(&observed).len(), before + 4 + TRANSMIT_VALUES);
        reader.close(&mut first).unwrap();
        assert_eq!(producer.drops.load(SeqCst), 1);
        assert_eq!(original.host_memory_bytes(), baseline);
        let (producer, consumer) = gates();
        let reader =
            wasmtime::component::FutureReader::new(&mut first, future_value(&producer)).unwrap();
        reader
            .pipe(&mut first, FutureSink(consumer.clone()))
            .unwrap();
        let mut running = Box::pin(drive(&mut first, &producer, &consumer));
        assert!(running
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop()))
            .is_pending());
        assert_eq!(producer.drops.load(SeqCst), 0);
        producer.release();
        running.await.unwrap();
        assert_eq!(consumer.payload.load(SeqCst), 42);
        assert_eq!(producer.drops.load(SeqCst), 1);
        drop(first);
        producer.release();
        consumer.release();
        assert_eq!(original.host_memory_bytes(), 0);
        assert_eq!(original.outstanding_reservations(), 0);
        println!("PRODUCER-PUBLIC-FUTURE adapter-custody=true Any-handle-only=true pending-payload=42 final=0 wall=5");
    }
}

#[tokio::test]
async fn actual_producer_factory_refusals_precede_transmit_factory_and_polls() {
    let engine = engine();
    let core = Module::new(&engine, CORE).unwrap();
    // Source-defined new cuts only: Stream factories2/3; Future factories3/4.
    for (future, local) in [(false, 2), (false, 3), (true, 3), (true, 4)] {
        let original = budget(MIB);
        let observed = Arc::new(Observations::default());
        let other = Arc::new(Observations::default());
        let mut foreign = store(&engine, &original, &other).unwrap();
        warm(&mut foreign).await;
        let foreign_bytes = original.host_memory_bytes();
        let foreign_requests = requests(&other);
        let mut first = store(&engine, &original, &observed).unwrap();
        warm(&mut first).await;
        let (producer, _) = gates();
        let before = requests(&observed).len();
        let padding = Arc::new(Mutex::new(None::<Padding>));
        let consumed = Arc::new(AtomicU64::new(0));
        let requested = Arc::new(AtomicU64::new(0));
        let kept = padding.clone();
        let kept_consumed = consumed.clone();
        let kept_requested = requested.clone();
        let invocation = original.clone();
        observed.before_request(before + local, move |bytes| {
            let request = bytes as u64 + OWNER;
            let payload = MIB - invocation.host_memory_bytes() - request + 1 - OWNER;
            let mut owner = crate::native_tables::reserve(&invocation, payload as usize)
                .unwrap()
                .unwrap();
            let bytes = vec![0u8; payload as usize];
            assert_eq!(bytes.capacity(), payload as usize);
            owner.allocated();
            *kept.lock().unwrap() = Some(Padding {
                _bytes: bytes,
                _owner: owner,
            });
            kept_consumed.store(invocation.host_memory_bytes(), SeqCst);
            kept_requested.store(request, SeqCst);
        });
        let error = if future {
            wasmtime::component::FutureReader::new(&mut first, future_value(&producer))
                .err()
                .unwrap()
        } else {
            StreamReader::new(&mut first, Producer(producer.clone()))
                .err()
                .unwrap()
        };
        denial(&error, MIB, consumed.load(SeqCst), requested.load(SeqCst));
        assert_eq!(consumed.load(SeqCst) + requested.load(SeqCst), MIB + 1);
        assert_eq!(requests(&observed).len(), before + local);
        assert_eq!(producer.polls.load(SeqCst), 0);
        assert_eq!(producer.drops.load(SeqCst), 1);
        drop(error);
        drop(padding.lock().unwrap().take());
        drop(first);
        assert_eq!(original.host_memory_bytes(), foreign_bytes);
        assert_eq!(requests(&other), foreign_requests);
        let mut fresh = store(&engine, &original, &observed).unwrap();
        fresh.set_fuel(FUEL).unwrap();
        let instance = wasmtime::Instance::new(&mut fresh, &core, &[]).unwrap();
        assert_eq!(core_answer(instance, &mut fresh), 42);
        drop(fresh);
        assert_eq!(original.host_memory_bytes(), foreign_bytes);
        drop(foreign);
        assert_eq!(original.host_memory_bytes(), 0);
        assert_eq!(original.outstanding_reservations(), 0);
        println!("PRODUCER-FACTORY-REFUSAL future={future} local={local} global={} polls=0 fresh=42 foreign-unchanged=true final=0 wall=5", before + local);
    }
}

#[tokio::test]
async fn actual_producer_factory_conversion_and_pending_lifetime_preserve_budget() {
    let engine = engine();
    let original = budget(MIB);
    let observed = Arc::new(Observations::default());
    let other = Arc::new(Observations::default());
    let mut foreign = store(&engine, &original, &other).unwrap();
    warm(&mut foreign).await;
    let foreign_bytes = original.host_memory_bytes();
    let foreign_requests = requests(&other);
    let mut first = store(&engine, &original, &observed).unwrap();
    warm(&mut first).await;
    warm_transmit_storage(&mut first, &original, &observed);
    let baseline = original.host_memory_bytes();
    for _ in 0..16 {
        let (producer, _) = gates();
        let before = requests(&observed).len();
        let mut reader = StreamReader::new(&mut first, EscapingProducer(producer.clone())).unwrap();
        assert_eq!(
            requests(&observed).len(),
            before + 3 + TRANSMIT_VALUES,
            "shared, two factories, three typed resource Boxes; existing entry backing"
        );
        let live = original.host_memory_bytes();
        for _ in 0..4 {
            reader = reader.try_into::<()>(&mut first).err().unwrap();
            assert_eq!(original.host_memory_bytes(), live);
            assert_eq!(requests(&observed).len(), before + 3 + TRANSMIT_VALUES);
        }
        reader.close(&mut first).unwrap();
        assert_eq!(producer.polls.load(SeqCst), 0);
        assert_eq!(producer.drops.load(SeqCst), 1);
        assert_eq!(original.host_memory_bytes(), baseline);
    }
    let (producer, _) = gates();
    let reader = StreamReader::new(&mut first, EscapingProducer(producer.clone())).unwrap();
    let escaped: Pin<Box<EscapingProducer>> = reader.try_into(&mut first).unwrap();
    assert_eq!(producer.drops.load(SeqCst), 0);
    assert_eq!(
        original.host_memory_bytes(),
        baseline,
        "both factories and cell retired; escaped P Box remains UNPAID"
    );
    drop(escaped);
    assert_eq!(producer.drops.load(SeqCst), 1);
    drop(first);
    assert_eq!(original.host_memory_bytes(), foreign_bytes);

    // Actual producer factory moves into the existing completion, across Pending.
    // Test ready, genuinely pending and original user error, without a component.
    for mode in 0..3 {
        let mut first = store(&engine, &original, &observed).unwrap();
        warm(&mut first).await;
        warm_transmit_storage(&mut first, &original, &observed);
        let baseline = original.host_memory_bytes();
        let (producer, consumer) = gates();
        producer.ready.store(mode != 1, SeqCst);
        producer.fail.store(mode == 2, SeqCst);
        let before = requests(&observed).len();
        let reader =
            wasmtime::component::FutureReader::new(&mut first, future_value(&producer)).unwrap();
        assert_eq!(
            requests(&observed).len(),
            before + 4 + TRANSMIT_VALUES,
            "local adapter, shared, two factories, three typed resource Boxes"
        );
        reader
            .pipe(&mut first, FutureSink(consumer.clone()))
            .unwrap();
        let mut running = Box::pin(drive(&mut first, &producer, &consumer));
        if mode == 1 {
            assert!(running
                .as_mut()
                .poll(&mut Context::from_waker(Waker::noop()))
                .is_pending());
            assert!(producer.polls.load(SeqCst) > 0);
            assert_eq!(consumer.polls.load(SeqCst), 0);
            assert!(original.host_memory_bytes() > baseline);
            producer.release();
        }
        let result = running.await;
        if mode == 2 {
            assert!(format!("{:#}", result.unwrap_err()).contains(FAILURE));
        } else {
            result.unwrap();
            assert_eq!(consumer.payload.load(SeqCst), 42);
        }
        // The original error path may retain transmit/work state until Store
        // teardown; a failed user poll is not a synthetic successful settle.
        drop(first);
        producer.release();
        consumer.release();
        assert_eq!(producer.drops.load(SeqCst), 1);
        assert_eq!(original.host_memory_bytes(), foreign_bytes);
    }
    assert_eq!(requests(&other), foreign_requests);
    drop(foreign);
    assert_eq!(original.host_memory_bytes(), 0);
    assert_eq!(original.outstanding_reservations(), 0);

    // Literal None path remains a separate source/Box/capture route.
    let mut none = Store::new(&engine, ());
    warm(&mut none).await;
    let (producer, consumer) = gates();
    producer.ready.store(true, SeqCst);
    StreamReader::new(&mut none, Producer(producer.clone()))
        .unwrap()
        .pipe(&mut none, Consumer(consumer.clone()))
        .unwrap();
    drive(&mut none, &producer, &consumer).await.unwrap();
    assert_eq!(*producer.trace.lock().unwrap(), ["produce", "consume"]);
    assert_eq!(consumer.payload.load(SeqCst), 42);
    drop(none);
    println!("PRODUCER-FACTORY-LIFETIME Err-reusable=true Ok-escape-P-unpaid=true pending=42 error=original None-order=true foreign-unchanged=true final=0 wall=5");
}
