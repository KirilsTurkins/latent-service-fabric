//! Public stream controls using the ORIGINAL ActivationBudget adapter.
//! Grant: 1MiB / 1B fuel / 5s wall. Not the private64MiB/120s ceiling.
use super::native_store_tests::{core_answer, requests, store, Observations, CORE, MIB, OWNER};
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
