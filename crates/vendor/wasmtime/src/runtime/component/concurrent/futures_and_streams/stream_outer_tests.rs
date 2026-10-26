//! OWNER-ONLY canonical-entry controls. This counter owner is NOT ActivationBudget.
use super::*;
use crate::component::{Component, Linker};
use crate::{AsContextMut, Config, Engine, NativeAllocation, Store};
use alloc::sync::Arc;
use alloc::vec::Vec;
use core::cell::{Cell, RefCell};
use core::sync::atomic::{AtomicBool, AtomicUsize, Ordering::SeqCst};
use std::sync::Mutex;
use std::time::Duration;

const PRIVATE_LIMIT: usize = 64 * 1024 * 1024;
const FUEL: u64 = 1_000_000_000;
const FIXTURE_ENV: &str = "LSF_TEST_STREAM_OUTERS_COMPONENT";
const REFUSAL: &str = "original-stream-entry-owner-refusal";
const FAILURE: &str = "original-stream-entry-poll-error";

#[derive(Default)]
struct Probe {
    requests: Mutex<Vec<usize>>,
    live: AtomicUsize,
    confirmations: AtomicUsize,
    refunds: AtomicUsize,
    refuse: AtomicUsize,
}
struct Allocation {
    probe: Arc<Probe>,
    bytes: usize,
}
impl NativeAllocation for Allocation {
    fn allocated(&mut self) {
        self.probe.confirmations.fetch_add(1, SeqCst);
    }
}
impl Drop for Allocation {
    fn drop(&mut self) {
        assert!(self.probe.live.fetch_sub(self.bytes, SeqCst) >= self.bytes);
        self.probe.refunds.fetch_add(1, SeqCst);
    }
}
struct Memory(Arc<Probe>);
impl crate::NativeMemory for Memory {
    fn reserve(&self, bytes: usize) -> Result<Box<dyn NativeAllocation>> {
        let ordinal = {
            let mut requests = self.0.requests.lock().unwrap();
            requests.push(bytes);
            requests.len()
        };
        if ordinal == self.0.refuse.load(SeqCst) {
            crate::bail!(REFUSAL);
        }
        self.0
            .live
            .fetch_update(SeqCst, SeqCst, |old| {
                old.checked_add(bytes)
                    .filter(|total| *total <= PRIVATE_LIMIT)
            })
            .expect("private64MiB unchanged owner ceiling");
        Ok(Box::new(Allocation {
            probe: self.0.clone(),
            bytes,
        }))
    }
}

#[derive(Clone, Copy)]
struct Cut {
    instance: Instance,
    ty: TransmitIndex,
    handle: u32,
    id: TableId<TransmitState>,
    write: bool,
    reverse: bool,
}
std::thread_local! {
    static CUT: RefCell<Option<Cut>> = const { RefCell::new(None) };
    static ARM: RefCell<Option<(Arc<Probe>, usize)>> = const { RefCell::new(None) };
    static REVERSE_ACTIVE: Cell<bool> = const { Cell::new(false) };
}
struct ObserveReverse;
impl ObserveReverse {
    fn new() -> Self {
        REVERSE_ACTIVE.with(|active| assert!(!active.replace(true)));
        Self
    }
}
impl Drop for ObserveReverse {
    fn drop(&mut self) {
        REVERSE_ACTIVE.with(|active| active.set(false));
    }
}

// Called only at the real paid canonical cut. No branch/return/value is changed.
pub(super) fn before_admission(
    instance: Instance,
    ty: TransmitIndex,
    handle: u32,
    id: TableId<TransmitState>,
    state: &mut ConcurrentState,
    write: bool,
) {
    assert_original_transmit(state, id, write);
    CUT.with(|cut| {
        *cut.borrow_mut() = Some(Cut {
            instance,
            ty,
            handle,
            id,
            write,
            reverse: false,
        })
    });
    ARM.with(|arm| {
        if let Some((probe, local)) = arm.borrow_mut().take() {
            // LOCAL queue/Task/outer order, not an upstream global ordinal.
            let before = probe.requests.lock().unwrap().len();
            probe.refuse.store(before + local, SeqCst);
        }
    });
}
// Guest write already made its legitimate Busy/GuestReady transition. The
// later host pipe has a DISTINCT cut before its consumer/queue publication.
pub(super) fn before_reverse_admission(id: TableId<TransmitState>, state: &mut ConcurrentState) {
    // Fixture-specific checks may not constrain unrelated unit-test callers.
    if !REVERSE_ACTIVE.with(Cell::get) {
        return;
    }
    let transmit = state.get_mut(id).unwrap();
    assert!(!transmit.done);
    assert!(matches!(&transmit.read, ReadState::Open));
    let &WriteState::GuestReady {
        instance,
        ty,
        handle,
        address,
        count,
        ..
    } = &transmit.write
    else {
        panic!("reverse cut requires original GuestReady writer")
    };
    assert_eq!(address, 256);
    assert_eq!(count.as_usize(), 1);
    CUT.with(|cut| {
        *cut.borrow_mut() = Some(Cut {
            instance,
            ty,
            handle,
            id,
            write: true,
            reverse: true,
        });
    });
    ARM.with(|arm| {
        if let Some((probe, local)) = arm.borrow_mut().take() {
            let before = probe.requests.lock().unwrap().len();
            probe.refuse.store(before + local, SeqCst);
        }
    });
}
fn assert_reverse_transmit(state: &mut ConcurrentState, cut: Cut, published: bool) {
    let transmit = state.get_mut(cut.id).unwrap();
    assert!(!transmit.done);
    if published {
        assert!(matches!(&transmit.read, ReadState::HostReady {
            guest_offset, cancel: false, cancel_waker: None, ..
        } if *guest_offset == ItemCount::ZERO));
    } else {
        assert!(matches!(&transmit.read, ReadState::Open));
    }
    let &WriteState::GuestReady {
        instance,
        ty,
        handle,
        address,
        count,
        ..
    } = &transmit.write
    else {
        panic!("original GuestReady must survive this host pipe path")
    };
    assert_eq!(instance.id(), cut.instance.id());
    assert!(matches!((ty, cut.ty), (TransmitIndex::Stream(a), TransmitIndex::Stream(b)) if a == b));
    assert_eq!(handle, cut.handle);
    assert_eq!(address, 256);
    assert_eq!(count.as_usize(), 1);
}
fn assert_original_transmit(state: &mut ConcurrentState, id: TableId<TransmitState>, write: bool) {
    let transmit = state.get_mut(id).unwrap();
    assert!(!transmit.done);
    if write {
        assert!(matches!(transmit.write, WriteState::Open));
        assert!(matches!(&transmit.read, ReadState::HostReady {
            guest_offset, cancel: false, cancel_waker: None, ..
        } if *guest_offset == ItemCount::ZERO));
    } else {
        assert!(matches!(transmit.read, ReadState::Open));
        assert!(matches!(&transmit.write, WriteState::HostReady {
            guest_offset, cancel: false, cancel_waker: None, ..
        } if *guest_offset == ItemCount::ZERO));
    }
}
fn assert_refused_state(store: &mut Store<()>) {
    let cut = CUT.with(|cut| cut.borrow().expect("real canonical cut observed"));
    let (_, local) = cut
        .instance
        .id()
        .get_mut(store.as_context_mut().0)
        .get_mut_by_index(cut.ty, cut.handle)
        .unwrap();
    assert_eq!(
        *local,
        if cut.reverse {
            TransmitLocalState::Busy
        } else if cut.write {
            TransmitLocalState::Write { done: false }
        } else {
            TransmitLocalState::Read { done: false }
        }
    );
    if cut.reverse {
        assert_reverse_transmit(
            store
                .as_context_mut()
                .0
                .concurrent_state_mut_without_forcing_current_thread(),
            cut,
            false,
        );
        return;
    }
    assert_original_transmit(
        store
            .as_context_mut()
            .0
            .concurrent_state_mut_without_forcing_current_thread(),
        cut.id,
        cut.write,
    );
}

#[derive(Default)]
struct Gate {
    ready: AtomicBool,
    fail: AtomicBool,
    done: AtomicBool,
    polls: AtomicUsize,
    payload: AtomicUsize,
    waker: Mutex<Option<Waker>>,
}
fn assert_settled(store: &mut Store<()>) {
    let cut = CUT.with(|cut| cut.borrow().expect("real paid canonical cut"));
    let state = store
        .as_context_mut()
        .0
        .concurrent_state_mut_without_forcing_current_thread();
    let transmit = state.get_mut(cut.id).unwrap();
    if cut.write {
        assert!(matches!(transmit.write, WriteState::Open));
        assert!(matches!(transmit.read, ReadState::Dropped));
    } else {
        assert!(matches!(transmit.read, ReadState::Open));
        assert!(matches!(transmit.write, WriteState::Dropped));
    }
}
impl Gate {
    fn poll(&self, cx: &mut Context<'_>) -> Poll<Result<()>> {
        self.polls.fetch_add(1, SeqCst);
        if !self.ready.load(SeqCst) {
            *self.waker.lock().unwrap() = Some(cx.waker().clone());
            return Poll::Pending;
        }
        self.done.store(true, SeqCst);
        if self.fail.load(SeqCst) {
            Poll::Ready(Err(crate::Error::msg(FAILURE)))
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
struct Producer(Arc<Gate>);
impl StreamProducer<()> for Producer {
    type Item = u8;
    type Buffer = Option<u8>;
    fn poll_produce<'a>(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        _store: StoreContextMut<'a, ()>,
        mut dst: Destination<'a, u8, Option<u8>>,
        _finish: bool,
    ) -> Poll<Result<StreamResult>> {
        match self.0.poll(cx) {
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
impl StreamConsumer<()> for Consumer {
    type Item = u8;
    fn poll_consume(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        store: StoreContextMut<()>,
        source: Source<'_, u8>,
        _finish: bool,
    ) -> Poll<Result<StreamResult>> {
        match self.0.poll(cx) {
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
fn fixture() -> (Engine, Component) {
    let path = std::env::var_os(FIXTURE_ENV).expect("owner-only fixed fixture path required");
    let meta = std::fs::symlink_metadata(&path).unwrap();
    assert!(meta.file_type().is_file() && !meta.file_type().is_symlink());
    assert!(meta.len() > 8 && meta.len() <= 64 * 1024);
    let bytes = std::fs::read(path).unwrap();
    assert!(bytes.starts_with(b"\0asm"));
    let engine = Engine::new(
        Config::new()
            .wasm_component_model(true)
            .wasm_component_model_async(true)
            .concurrency_support(true)
            .consume_fuel(true),
    )
    .unwrap();
    let component = Component::new(&engine, bytes).unwrap();
    (engine, component)
}
async fn setup(
    engine: &Engine,
    component: &Component,
    paid: bool,
    probe: &Arc<Probe>,
) -> (Store<()>, Instance) {
    let mut store = if paid {
        Store::try_new_with_memory(engine, (), Arc::new(Memory(probe.clone()))).unwrap()
    } else {
        Store::new(engine, ())
    };
    store.set_fuel(FUEL).unwrap();
    let instance = Linker::<()>::new(engine)
        .instantiate_async(&mut store, component)
        .await
        .unwrap();
    let fuel = store.get_fuel().unwrap();
    store.run_concurrent(async |_| ()).await.unwrap();
    assert_eq!(store.get_fuel().unwrap(), fuel);
    CUT.with(|cut| *cut.borrow_mut() = None);
    (store, instance)
}
async fn enter(
    store: &mut Store<()>,
    instance: Instance,
    gate: &Arc<Gate>,
    write: bool,
) -> Result<(u32,)> {
    if write {
        let make = instance.get_typed_func::<(), (StreamReader<u8>,)>(&mut *store, "make")?;
        let (reader,) = make.call_async(&mut *store, ()).await?;
        reader.pipe(&mut *store, Consumer(gate.clone()))?;
        instance
            .get_typed_func::<(), (u32,)>(&mut *store, "write")?
            .call_async(store, ())
            .await
    } else {
        let reader = StreamReader::new(&mut *store, Producer(gate.clone()))?;
        instance
            .get_typed_func::<(StreamReader<u8>,), (u32,)>(&mut *store, "read")?
            .call_async(store, (reader,))
            .await
    }
}
async fn drive(store: &mut Store<()>, gate: &Arc<Gate>) -> Result<()> {
    // Deliberately pending main future drives the existing scheduler. It does
    // not allocate a new stream/task or fabricate completion.
    tokio::time::timeout(
        Duration::from_secs(120),
        store.run_concurrent(async |_| {
            while !gate.done.load(SeqCst) {
                tokio::task::yield_now().await;
            }
        }),
    )
    .await
    .expect("private120s original ceiling")
}
async fn waiting_writer(store: &mut Store<()>, instance: Instance) -> StreamReader<u8> {
    let make = instance
        .get_typed_func::<(), (StreamReader<u8>,)>(&mut *store, "make")
        .unwrap();
    let (reader,) = make.call_async(&mut *store, ()).await.unwrap();
    let write = instance
        .get_typed_func::<(), (u32,)>(&mut *store, "write")
        .unwrap();
    assert_eq!(write.call_async(store, ()).await.unwrap(), (u32::MAX,));
    reader
}
async fn reverse_refusal_cases(engine: &Engine, component: &Component) {
    for local in 1..=3 {
        let probe = Arc::new(Probe::default());
        let (mut store, instance) = setup(engine, component, true, &probe).await;
        let reader = waiting_writer(&mut store, instance).await;
        let gate = Arc::new(Gate::default());
        ARM.with(|arm| *arm.borrow_mut() = Some((probe.clone(), local)));
        let error = {
            let _observe = ObserveReverse::new();
            reader.pipe(&mut store, Consumer(gate.clone())).unwrap_err()
        };
        assert!(format!("{error:#}").contains(REFUSAL));
        assert_eq!(gate.polls.load(SeqCst), 0);
        assert_refused_state(&mut store);
        let global = probe.refuse.load(SeqCst);
        assert_eq!(probe.requests.lock().unwrap().len(), global);
        println!(
            "STREAM-REVERSE-CUT local={} global={} preexisting-busy=true guest-ready=true consumer-polls=0",
            local, global
        );
        drop(error);
        drop(store);
        gate.release();
        assert_eq!(probe.live.load(SeqCst), 0);
        probe.refuse.store(0, SeqCst);
        let (mut fresh, instance) = setup(engine, component, true, &probe).await;
        let answer = instance
            .get_typed_func::<(), (u32,)>(&mut fresh, "answer")
            .unwrap();
        assert_eq!(answer.call_async(&mut fresh, ()).await.unwrap(), (42,));
        drop(fresh);
        assert_eq!(probe.live.load(SeqCst), 0);
    }
}
async fn reverse_positive_cases(engine: &Engine, component: &Component) {
    for paid in [false, true] {
        for mode in 0..3 {
            let probe = Arc::new(Probe::default());
            let (mut store, instance) = setup(engine, component, paid, &probe).await;
            let reader = waiting_writer(&mut store, instance).await;
            let gate = Arc::new(Gate::default());
            gate.ready.store(mode != 1, SeqCst);
            gate.fail.store(mode == 2, SeqCst);
            {
                let _observe = ObserveReverse::new();
                reader.pipe(&mut store, Consumer(gate.clone())).unwrap();
            }
            assert_eq!(
                gate.polls.load(SeqCst),
                0,
                "host pipe queues without initial inner poll"
            );
            if paid {
                let cut = CUT.with(|cut| cut.borrow().expect("actual reverse cut"));
                assert!(cut.reverse);
                assert_reverse_transmit(
                    store
                        .as_context_mut()
                        .0
                        .concurrent_state_mut_without_forcing_current_thread(),
                    cut,
                    true,
                );
            }
            let mut running = Box::pin(drive(&mut store, &gate));
            if mode == 1 {
                assert!(
                    running
                        .as_mut()
                        .poll(&mut Context::from_waker(Waker::noop()))
                        .is_pending()
                );
                assert!(gate.polls.load(SeqCst) > 0);
                let before_wake = probe.requests.lock().unwrap().len();
                gate.release();
                assert_eq!(probe.requests.lock().unwrap().len(), before_wake);
            }
            let result = running.await;
            if mode == 2 {
                assert!(format!("{:#}", result.unwrap_err()).contains(FAILURE));
                // Original await-error exits before settle. Keep that genuine
                // state; physical Store cleanup is checked below, no rollback.
                if paid {
                    let cut = CUT.with(|cut| cut.borrow().unwrap());
                    assert_reverse_transmit(
                        store
                            .as_context_mut()
                            .0
                            .concurrent_state_mut_without_forcing_current_thread(),
                        cut,
                        true,
                    );
                }
            } else {
                result.unwrap();
                assert_eq!(gate.payload.load(SeqCst), 42);
                if paid {
                    assert_settled(&mut store);
                }
            }
            drop(store);
            gate.release();
            assert_eq!(probe.live.load(SeqCst), 0);
            println!(
                "STREAM-REVERSE-CLEANUP paid={} mode={} payload={} final=0",
                paid,
                mode,
                if mode == 2 { "original-error" } else { "42" }
            );
        }
    }
}
async fn refusal_cases(write: bool) {
    let (engine, component) = fixture();
    for local in 1..=3 {
        let probe = Arc::new(Probe::default());
        let (mut store, instance) = setup(&engine, &component, true, &probe).await;
        let gate = Arc::new(Gate::default());
        ARM.with(|arm| *arm.borrow_mut() = Some((probe.clone(), local)));
        let error = enter(&mut store, instance, &gate, write).await.unwrap_err();
        assert!(format!("{error:#}").contains(REFUSAL));
        assert_eq!(gate.polls.load(SeqCst), 0);
        assert_refused_state(&mut store);
        let global = probe.refuse.load(SeqCst);
        assert_eq!(probe.requests.lock().unwrap().len(), global);
        println!(
            "STREAM-CUT direction={} local={} global={} pre-busy=true polls=0",
            if write { "write" } else { "read" },
            local,
            global
        );
        drop(error);
        drop(store);
        gate.release();
        assert_eq!(probe.live.load(SeqCst), 0);
        probe.refuse.store(0, SeqCst);
        let (mut fresh, instance) = setup(&engine, &component, true, &probe).await;
        let answer = instance
            .get_typed_func::<(), (u32,)>(&mut fresh, "answer")
            .unwrap();
        assert_eq!(answer.call_async(&mut fresh, ()).await.unwrap(), (42,));
        drop(fresh);
        assert_eq!(probe.live.load(SeqCst), 0);
    }
    if write {
        reverse_refusal_cases(&engine, &component).await;
    }
}
async fn positive_cases(write: bool) {
    let (engine, component) = fixture();
    for paid in [false, true] {
        // ready, pending->ready, original error. No trap reentry is attempted.
        for mode in 0..3 {
            let probe = Arc::new(Probe::default());
            let (mut store, instance) = setup(&engine, &component, paid, &probe).await;
            let gate = Arc::new(Gate::default());
            gate.ready.store(mode != 1, SeqCst);
            gate.fail.store(mode == 2, SeqCst);
            let result = enter(&mut store, instance, &gate, write).await;
            assert!(gate.polls.load(SeqCst) > 0);
            if mode == 2 {
                assert!(format!("{:#}", result.unwrap_err()).contains(FAILURE));
            } else {
                assert_eq!(result.unwrap(), (if mode == 1 { u32::MAX } else { 17 },));
                if mode == 1 {
                    let before = probe.requests.lock().unwrap().len();
                    gate.release();
                    assert_eq!(
                        probe.requests.lock().unwrap().len(),
                        before,
                        "the real wake itself makes no new admission"
                    );
                    // A separate normal driver may have its own legitimate
                    // admissions (including incoming v16), distinct from wake.
                    drive(&mut store, &gate).await.unwrap();
                }
                if write {
                    assert_eq!(gate.payload.load(SeqCst), 42);
                } else {
                    let value = instance
                        .get_typed_func::<(), (u32,)>(&mut store, "read-value")
                        .unwrap();
                    assert_eq!(value.call_async(&mut store, ()).await.unwrap(), (42,));
                }
                if paid {
                    assert_settled(&mut store);
                }
            }
            drop(store);
            gate.release();
            assert_eq!(probe.live.load(SeqCst), 0);
            println!(
                "STREAM-PAYLOAD direction={} paid={} mode={} payload={}",
                if write { "write" } else { "read" },
                paid,
                mode,
                if mode == 2 { "original-error" } else { "42" }
            );
        }
    }
    if write {
        reverse_positive_cases(&engine, &component).await;
    }
}

#[tokio::test]
#[ignore = "requires owner-authenticated RunnerTemp canonical stream component"]
async fn actual_stream_guest_write_refusals_precede_busy_and_transmit_mutation() {
    tokio::time::timeout(Duration::from_secs(120), refusal_cases(true))
        .await
        .unwrap();
}
#[tokio::test]
#[ignore = "requires owner-authenticated RunnerTemp canonical stream component"]
async fn actual_stream_guest_read_refusals_precede_busy_and_transmit_mutation() {
    tokio::time::timeout(Duration::from_secs(120), refusal_cases(false))
        .await
        .unwrap();
}
#[tokio::test]
#[ignore = "requires owner-authenticated RunnerTemp canonical stream component"]
async fn actual_stream_guest_write_ready_pending_error_and_none_order() {
    tokio::time::timeout(Duration::from_secs(120), positive_cases(true))
        .await
        .unwrap();
}
#[tokio::test]
#[ignore = "requires owner-authenticated RunnerTemp canonical stream component"]
async fn actual_stream_guest_read_ready_pending_error_and_none_order() {
    tokio::time::timeout(Duration::from_secs(120), positive_cases(false))
        .await
        .unwrap();
}

use alloc::string::ToString;

// Private implementation observations only; these are not ActivationBudget or
// source-derived claims of a newly executed native stream programme.
#[derive(Default)]
struct ConsumerCellProbe {
    requests: Mutex<Vec<usize>>,
    live: AtomicUsize,
    confirmations: AtomicUsize,
    value_drops: AtomicUsize,
    refunds: Mutex<Vec<usize>>,
    refuse: AtomicUsize,
    panic_confirmation: AtomicUsize,
    check_value_drop: AtomicBool,
}

struct ConsumerCellAllocation {
    probe: Arc<ConsumerCellProbe>,
    bytes: usize,
    ordinal: usize,
    confirmed: bool,
}

impl NativeAllocation for ConsumerCellAllocation {
    fn allocated(&mut self) {
        self.confirmed = true;
        self.probe.confirmations.fetch_add(1, SeqCst);
        assert_ne!(
            self.probe.panic_confirmation.load(SeqCst),
            self.ordinal,
            "consumer-cell-confirmation-control"
        );
    }
}

impl Drop for ConsumerCellAllocation {
    fn drop(&mut self) {
        if self.confirmed && self.probe.check_value_drop.load(SeqCst) {
            assert_eq!(self.probe.value_drops.load(SeqCst), 1);
        }
        assert!(self.probe.live.fetch_sub(self.bytes, SeqCst) >= self.bytes);
        self.probe.refunds.lock().unwrap().push(self.ordinal);
    }
}

struct ConsumerCellMemory(Arc<ConsumerCellProbe>);

impl crate::NativeMemory for ConsumerCellMemory {
    fn reserve(&self, bytes: usize) -> Result<Box<dyn NativeAllocation>> {
        let ordinal = {
            let mut requests = self.0.requests.lock().unwrap();
            requests.push(bytes);
            requests.len()
        };
        if self.0.refuse.load(SeqCst) == ordinal {
            crate::bail!("consumer-cell-refusal-control");
        }
        self.0.live.fetch_add(bytes, SeqCst);
        Ok(Box::new(ConsumerCellAllocation {
            probe: self.0.clone(),
            bytes,
            ordinal,
            confirmed: false,
        }))
    }
}

#[repr(align(256))]
struct ConsumerCellValue {
    probe: Arc<ConsumerCellProbe>,
    panic_drop: bool,
    _pinned: core::marker::PhantomPinned,
}

impl Drop for ConsumerCellValue {
    fn drop(&mut self) {
        assert_eq!(self.probe.value_drops.fetch_add(1, SeqCst), 0);
        assert!(!self.panic_drop, "consumer-cell-destructor-control");
    }
}

fn consumer_cell_memory(probe: &Arc<ConsumerCellProbe>) -> crate::runtime::native_memory::Memory {
    Some(Arc::new(ConsumerCellMemory(probe.clone())))
}

fn consumer_cell_value(probe: &Arc<ConsumerCellProbe>, panic_drop: bool) -> ConsumerCellValue {
    ConsumerCellValue {
        probe: probe.clone(),
        panic_drop,
        _pinned: core::marker::PhantomPinned,
    }
}

#[test]
fn consumer_cell_two_admissions_refuse_before_either_allocation_and_abandon_unused() {
    for refused in [1, 2] {
        let probe = Arc::new(ConsumerCellProbe::default());
        probe.refuse.store(refused, SeqCst);
        let result =
            AccountedConsumerCell::<ConsumerCellValue>::prepare(&consumer_cell_memory(&probe));
        assert_eq!(
            result.err().unwrap().to_string(),
            "consumer-cell-refusal-control"
        );
        assert_eq!(probe.requests.lock().unwrap().len(), refused);
        assert_eq!(probe.confirmations.load(SeqCst), 0);
        assert_eq!(probe.value_drops.load(SeqCst), 0);
        assert_eq!(probe.live.load(SeqCst), 0);
        assert_eq!(probe.refunds.lock().unwrap().len(), refused - 1);
    }
    let probe = Arc::new(ConsumerCellProbe::default());
    let prepared =
        AccountedConsumerCell::<ConsumerCellValue>::prepare(&consumer_cell_memory(&probe)).unwrap();
    assert_eq!(
        *probe.requests.lock().unwrap(),
        [
            core::alloc::Layout::new::<ConsumerCellValue>().size(),
            AccountedConsumerCell::<ConsumerCellValue>::layout()
                .unwrap()
                .size(),
        ]
    );
    assert_eq!(probe.confirmations.load(SeqCst), 0);
    drop(prepared);
    assert_eq!(probe.live.load(SeqCst), 0);
    assert_eq!(probe.value_drops.load(SeqCst), 0);
}

#[test]
fn consumer_cell_pinned_value_and_shared_owner_live_through_clones_and_taken_guard() {
    let probe = Arc::new(ConsumerCellProbe::default());
    probe.check_value_drop.store(true, SeqCst);
    let prepared =
        AccountedConsumerCell::<ConsumerCellValue>::prepare(&consumer_cell_memory(&probe)).unwrap();
    let cell = AccountedConsumerCell::create(prepared, consumer_cell_value(&probe, false));
    let live = probe.live.load(SeqCst);
    assert_eq!(probe.confirmations.load(SeqCst), 2);
    let second = cell.clone();
    let mut taken = second.take().unwrap();
    let address = taken.as_mut().as_ref().get_ref() as *const ConsumerCellValue as usize;
    assert_eq!(address % core::mem::align_of::<ConsumerCellValue>(), 0);
    drop(cell);
    assert_eq!(probe.live.load(SeqCst), live);
    assert_eq!(probe.value_drops.load(SeqCst), 0);
    drop(taken); // Original LockedStateGuard restores the SAME pinned consumer.
    assert_eq!(
        second.take().unwrap().as_ref().get_ref() as *const _ as usize,
        address
    );
    let last = second.clone();
    drop(second);
    assert_eq!(probe.live.load(SeqCst), live);
    drop(last);
    assert_eq!(probe.value_drops.load(SeqCst), 1);
    assert_eq!(probe.live.load(SeqCst), 0);
    assert_eq!(*probe.refunds.lock().unwrap(), [1, 2]);
}

#[test]
fn consumer_cell_zst_and_none_preserve_actual_backing_routes() {
    let probe = Arc::new(ConsumerCellProbe::default());
    let prepared = AccountedConsumerCell::<()>::prepare(&consumer_cell_memory(&probe)).unwrap();
    assert_eq!(
        *probe.requests.lock().unwrap(),
        [AccountedConsumerCell::<()>::layout().unwrap().size(),]
    );
    let cell = AccountedConsumerCell::create(prepared, ());
    assert_eq!(probe.confirmations.load(SeqCst), 1);
    drop(cell);
    assert_eq!(probe.live.load(SeqCst), 0);

    let probe = Arc::new(ConsumerCellProbe::default());
    type Legacy = Arc<LockedState<Pin<Box<ConsumerCellValue>>>>;
    let prepared = <Legacy as ConsumerStorage<ConsumerCellValue>>::prepare(&None).unwrap();
    let cell: Legacy = <Legacy as ConsumerStorage<ConsumerCellValue>>::create(
        prepared,
        consumer_cell_value(&probe, false),
    );
    let second = cell.clone();
    drop(cell);
    assert_eq!(probe.value_drops.load(SeqCst), 0);
    drop(second);
    assert_eq!(probe.value_drops.load(SeqCst), 1);
    assert!(probe.requests.lock().unwrap().is_empty());
    assert_eq!(probe.confirmations.load(SeqCst), 0);
}

#[test]
fn consumer_cell_each_confirmation_unwind_has_physical_cleanup_installed() {
    for confirmation in [1, 2] {
        let probe = Arc::new(ConsumerCellProbe::default());
        probe.check_value_drop.store(true, SeqCst);
        probe.panic_confirmation.store(confirmation, SeqCst);
        let prepared =
            AccountedConsumerCell::<ConsumerCellValue>::prepare(&consumer_cell_memory(&probe))
                .unwrap();
        assert!(
            std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                AccountedConsumerCell::create(prepared, consumer_cell_value(&probe, false))
            }))
            .is_err()
        );
        assert_eq!(probe.value_drops.load(SeqCst), 1);
        assert_eq!(probe.live.load(SeqCst), 0);
        assert_eq!(probe.refunds.lock().unwrap().len(), 2);
    }
}

#[test]
fn consumer_cell_destructor_unwind_retains_both_original_uncertain_charges() {
    let probe = Arc::new(ConsumerCellProbe::default());
    let prepared =
        AccountedConsumerCell::<ConsumerCellValue>::prepare(&consumer_cell_memory(&probe)).unwrap();
    let cell = AccountedConsumerCell::create(prepared, consumer_cell_value(&probe, true));
    let live = probe.live.load(SeqCst);
    assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(cell))).is_err());
    assert_eq!(probe.value_drops.load(SeqCst), 1);
    assert_eq!(probe.live.load(SeqCst), live);
    assert!(probe.refunds.lock().unwrap().is_empty());
}

// Producer implementation controls are private counters, not public grants.
#[repr(align(256))]
struct ProducerCellValue {
    trace: Arc<Mutex<Vec<&'static str>>>,
    panic_drop: bool,
    not_sync: Cell<u8>,
    _pinned: core::marker::PhantomPinned,
}
impl Drop for ProducerCellValue {
    fn drop(&mut self) {
        self.trace.lock().unwrap().push("P");
        assert!(!self.panic_drop, "producer-cell-P-drop");
    }
}
struct ProducerCellBuffer {
    trace: Option<Arc<Mutex<Vec<&'static str>>>>,
    panic_drop: bool,
}
impl Default for ProducerCellBuffer {
    fn default() -> Self {
        Self {
            trace: None,
            panic_drop: false,
        }
    }
}
impl Drop for ProducerCellBuffer {
    fn drop(&mut self) {
        if let Some(trace) = &self.trace {
            trace.lock().unwrap().push("B");
        }
        assert!(!self.panic_drop, "producer-cell-B-drop");
    }
}
fn producer_cell_value(
    trace: &Arc<Mutex<Vec<&'static str>>>,
    panic_drop: bool,
) -> ProducerCellValue {
    ProducerCellValue {
        trace: trace.clone(),
        panic_drop,
        not_sync: Cell::new(0),
        _pinned: core::marker::PhantomPinned,
    }
}
// Exercise the physical owner with its exact P/B layouts. This is deliberately
// NOT a marker implementation claiming arbitrary P has FutureReader custody.
fn physical_producer_prepared<P, B>(probe: &Arc<ConsumerCellProbe>) -> PreparedProducerCell<P, B> {
    let memory = consumer_cell_memory(probe);
    PreparedProducerCell {
        pinned: crate::runtime::native_memory::reserve(
            &memory,
            core::alloc::Layout::new::<P>().size(),
        )
        .unwrap(),
        shared: crate::runtime::native_memory::reserve(
            &memory,
            AccountedProducerCell::<P, B>::layout().unwrap().size(),
        )
        .unwrap()
        .unwrap(),
        _producer: PhantomData,
    }
}

#[test]
fn producer_cell_stream_admission_is_shared_only_and_unused_refunds() {
    let probe = Arc::new(ConsumerCellProbe::default());
    let memory = consumer_cell_memory(&probe);
    probe.refuse.store(1, SeqCst);
    assert!(prepare_producer_cell::<(), Producer, UnpaidStreamProducerBody>(&memory).is_err());
    assert_eq!(probe.confirmations.load(SeqCst), 0);
    assert_eq!(probe.live.load(SeqCst), 0);
    probe.refuse.store(0, SeqCst);
    let prepared =
        prepare_producer_cell::<(), Producer, UnpaidStreamProducerBody>(&memory).unwrap();
    assert!(
        prepared.pinned.is_none(),
        "general owning conversion must never strand a body charge"
    );
    assert_eq!(
        *probe.requests.lock().unwrap(),
        [AccountedProducerCell::<Producer, Option<u8>>::layout()
            .unwrap()
            .size(); 2]
    );
    drop(prepared);
    assert_eq!(probe.live.load(SeqCst), 0);
    assert_eq!(probe.confirmations.load(SeqCst), 0);
}

#[test]
fn producer_cell_pin_clone_send_guard_restore_and_p_then_b_retirement() {
    fn send<T: Send>(_: &T) {}
    let probe = Arc::new(ConsumerCellProbe::default());
    let trace = Arc::new(Mutex::new(Vec::new()));
    let prepared = physical_producer_prepared::<ProducerCellValue, ProducerCellBuffer>(&probe);
    let cell = AccountedProducerCell::create(prepared, producer_cell_value(&trace, false));
    let second = cell.clone();
    let live = probe.live.load(SeqCst);
    assert_eq!(probe.confirmations.load(SeqCst), 2);
    let address = {
        let mut guard = cell.take().unwrap();
        send(&guard); // P contains Cell and !Unpin; no P:Sync requirement.
        guard.0.as_ref().get_ref().not_sync.set(42);
        guard.1.trace = Some(trace.clone());
        let address = guard.0.as_ref().get_ref() as *const ProducerCellValue as usize;
        assert_eq!(address % core::mem::align_of::<ProducerCellValue>(), 0);
        address
    };
    assert!(
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let _guard = second.take().unwrap();
            panic!("original taken-guard unwind");
        }))
        .is_err()
    );
    assert_eq!(
        second.take().unwrap().0.as_ref().get_ref() as *const _ as usize,
        address
    );
    drop(cell);
    assert_eq!(probe.live.load(SeqCst), live);
    assert!(trace.lock().unwrap().is_empty());
    drop(second);
    assert_eq!(*trace.lock().unwrap(), ["P", "B"]);
    assert_eq!(*probe.refunds.lock().unwrap(), [1, 2]);
    assert_eq!(probe.live.load(SeqCst), 0);
}

#[test]
fn producer_cell_zst_and_original_none_tuple_remain_distinct() {
    let probe = Arc::new(ConsumerCellProbe::default());
    let prepared = physical_producer_prepared::<(), ()>(&probe);
    assert!(prepared.pinned.is_none());
    let cell = AccountedProducerCell::create(prepared, ());
    assert_eq!(
        *probe.requests.lock().unwrap(),
        [AccountedProducerCell::<(), ()>::layout().unwrap().size()]
    );
    assert_eq!(probe.confirmations.load(SeqCst), 1);
    drop(cell);
    assert_eq!(probe.live.load(SeqCst), 0);
    let trace = Arc::new(Mutex::new(Vec::new()));
    // Literal original None allocation/exact tuple type and guard.
    let cell: Arc<LockedState<(Pin<Box<ProducerCellValue>>, ProducerCellBuffer)>> =
        Arc::new(LockedState::new((
            Box::pin(producer_cell_value(&trace, false)),
            ProducerCellBuffer::default(),
        )));
    let mut guard = LockedState::take(&cell).unwrap();
    guard.1.trace = Some(trace.clone());
    drop(guard);
    drop(cell);
    assert_eq!(*trace.lock().unwrap(), ["P", "B"]);
    assert_eq!(probe.requests.lock().unwrap().len(), 1);
}

#[test]
fn producer_cell_confirmation_and_buffer_default_unwind_install_cleanup_first() {
    for confirmation in [1, 2] {
        let probe = Arc::new(ConsumerCellProbe::default());
        probe.panic_confirmation.store(confirmation, SeqCst);
        let trace = Arc::new(Mutex::new(Vec::new()));
        let prepared = physical_producer_prepared::<ProducerCellValue, ProducerCellBuffer>(&probe);
        assert!(
            std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                AccountedProducerCell::create(prepared, producer_cell_value(&trace, false))
            }))
            .is_err()
        );
        assert_eq!(*trace.lock().unwrap(), ["P"]);
        assert_eq!(probe.live.load(SeqCst), 0);
        assert_eq!(probe.refunds.lock().unwrap().len(), 2);
    }
    struct BufferDefaultPanic;
    impl Default for BufferDefaultPanic {
        fn default() -> Self {
            panic!("producer-cell-buffer-default");
        }
    }
    let probe = Arc::new(ConsumerCellProbe::default());
    let trace = Arc::new(Mutex::new(Vec::new()));
    let prepared = physical_producer_prepared::<ProducerCellValue, BufferDefaultPanic>(&probe);
    assert!(
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            AccountedProducerCell::create(prepared, producer_cell_value(&trace, false))
        }))
        .is_err()
    );
    assert_eq!(*trace.lock().unwrap(), ["P"]);
    assert_eq!(probe.live.load(SeqCst), 0);
}

#[test]
fn producer_cell_destructor_unwind_retains_same_original_guards() {
    for panic_p in [true, false] {
        let probe = Arc::new(ConsumerCellProbe::default());
        let trace = Arc::new(Mutex::new(Vec::new()));
        let prepared = physical_producer_prepared::<ProducerCellValue, ProducerCellBuffer>(&probe);
        let cell = AccountedProducerCell::create(prepared, producer_cell_value(&trace, panic_p));
        cell.with(|pair| {
            pair.1.trace = Some(trace.clone());
            pair.1.panic_drop = !panic_p;
        })
        .unwrap();
        let live = probe.live.load(SeqCst);
        assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(cell))).is_err());
        assert_eq!(*trace.lock().unwrap(), ["P", "B"]);
        assert_eq!(probe.live.load(SeqCst), live);
        assert!(probe.refunds.lock().unwrap().is_empty());
    }
}

#[tokio::test]
async fn producer_cell_real_future_adapter_default_err_restores_original_custody() {
    let engine = Engine::new(
        Config::new()
            .wasm_component_model(true)
            .wasm_component_model_async(true)
            .concurrency_support(true),
    )
    .unwrap();
    let probe = Arc::new(Probe::default());
    let mut store =
        Store::try_new_with_memory(&engine, (), Arc::new(Memory(probe.clone()))).unwrap();
    store.run_concurrent(async |_| ()).await.unwrap();
    let before = probe.requests.lock().unwrap().len();
    let initial = probe.live.load(SeqCst);
    let mut reader = FutureReader::new(&mut store, async { crate::error::Ok(42u8) }).unwrap();
    assert_eq!(probe.requests.lock().unwrap().len(), before + 2);
    let live = probe.live.load(SeqCst);
    assert!(live > initial);
    for _ in 0..32 {
        let state = store
            .as_context_mut()
            .0
            .concurrent_state_mut_already_forced_current_thread();
        let id = state.get_mut(reader.id).unwrap().state;
        let WriteState::HostReady { try_into, .. } = &state.get_mut(id).unwrap().write else {
            panic!("real FutureReader producer");
        };
        assert!(try_into(TypeId::of::<()>()).is_none());
        assert_eq!(probe.live.load(SeqCst), live);
        assert_eq!(probe.requests.lock().unwrap().len(), before + 2);
    }
    reader.close(&mut store).unwrap();
    assert_eq!(probe.live.load(SeqCst), initial);
    drop(store);
    assert_eq!(probe.live.load(SeqCst), 0);
}
