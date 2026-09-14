//! Real canonical-async conformance of the shared ownership substrate. This
//! deliberately uses a test-only import; HTTP/event product adapters have their
//! own delivery tickets and are not enabled by mere interface recognition.
use super::{component, fixture::*, support};
use latent_artifacts::ArtifactRepository;
use latent_capabilities::broker::io::{
    IoBuffer, IoLimits, IoRuntime, IoSnapshot, IoStopHandle, IoStreamTerminal, IoWorkPhase,
};
use latent_core::{BudgetConsumption, PlatformErrorCode};
use latent_policy::capability::ResourceTarget;
use std::sync::Mutex;
use tokio::sync::{Notify, Semaphore};
use wasmtime::{
    component::{Component, Linker, TypedFunc},
    Config, Engine, Store, StoreLimits, StoreLimitsBuilder,
};
#[path = "async_component.rs"]
mod async_component;

struct State {
    session: CapabilitySession,
    io: Arc<IoRuntime>,
    provider_ready: Arc<Semaphore>,
    started: Arc<Notify>,
    retained: Arc<Mutex<Option<IoBuffer>>>,
    stop: Arc<Mutex<Option<IoStopHandle>>>,
    limiter: StoreLimits,
}
fn error(failure: PlatformError) -> wasmtime::Error {
    let code = failure.code;
    drop(failure);
    wasmtime::Error::msg(format!("bounded I/O: {code:?}"))
}
fn install(linker: &mut Linker<State>) {
    linker
        .root()
        .func_wrap_concurrent("read", |access, (): ()| {
            Box::pin(async move {
                let (admission, gate, started, retained, stop) = access
                    .with(|mut store| {
                        let state = store.data_mut();
                        Ok::<_, PlatformError>((
                            state.io.admit(&state.session)?,
                            Arc::clone(&state.provider_ready),
                            Arc::clone(&state.started),
                            Arc::clone(&state.retained),
                            Arc::clone(&state.stop),
                        ))
                    })
                    .map_err(|failure| error(failure).context("queue admission"))?;
                *stop.lock().unwrap() = Some(admission.stop_handle());
                let ready = admission
                    .wait()
                    .await
                    .map_err(|failure| error(failure).context("queue wait"))?;
                // The policy/publication fence runs after queueing, through temporary
                // Accessor access. No Store reference is held while the provider awaits.
                let call = access
                    .with(|mut store| {
                        let session = &store.data_mut().session;
                        let resource = ResourceTarget::Clock;
                        let handle = session.bind(component::CAP, "now-unix-millis", resource)?;
                        let call = session.dispatch(
                            handle,
                            "now-unix-millis",
                            resource,
                            &[],
                            CapabilityCallCost::new(32),
                            |call| call,
                        );
                        session.close_handle(handle)?;
                        call
                    })
                    .map_err(|failure| error(failure).context("final dispatch"))?;
                let call = ready
                    .start(call)
                    .map_err(|failure| error(failure).context("start owner"))?;
                let mut bytes = call.buffer(32, 16).map_err(error)?;
                started.notify_one();
                call.wait_for(gate.acquire())
                    .await
                    .map_err(error)?
                    .map_err(|_| wasmtime::Error::msg("test gate closed"))?
                    .forget();
                bytes.spare_mut().map_err(error)?[0] = 42;
                bytes.advance_written(1).map_err(error)?;
                let (mut writer, mut reader) = call.stream(1).map_err(error)?;
                writer.write(bytes).await.map_err(error)?;
                writer.finish(IoStreamTerminal::Eof);
                let bytes = reader
                    .read()
                    .await
                    .map_err(error)?
                    .expect("one response chunk");
                assert!(reader.read().await.map_err(error)?.is_none());
                reader.close();
                call.checkpoint().map_err(error)?;
                let result = u32::from(bytes.bytes()[0]);
                *retained.lock().unwrap() = Some(bytes);
                Ok((result,))
            })
        })
        .unwrap();
}

struct Harness {
    store: Store<State>,
    function: TypedFunc<(), (u32,)>,
    observer: CapabilitySessionObserver,
    io: Arc<IoRuntime>,
    gate: Arc<Semaphore>,
    started: Arc<Notify>,
    retained: Arc<Mutex<Option<IoBuffer>>>,
    stop: Arc<Mutex<Option<IoStopHandle>>>,
    control: Control,
}
impl Harness {
    async fn new(fixture: &Fixture, engine: &Engine, component: &Component) -> Self {
        let (mut request, control) = fixture.request("async-cell");
        let sample = ClockSample::system_now();
        request.activation.deadline_unix_millis = Some(sample.unix_millis() + 5_000);
        let deadline = latent_core::EffectiveActivationBudget::admit_at(
            &request.budget,
            &request.budget,
            &request.budget,
            request.activation.deadline_unix_millis,
            sample,
        )
        .unwrap()
        .deadline;
        let publication = fixture
            .catalog
            .execution_eligibility_selected(
                &fixture.revision.release,
                fixture.revision.publication.as_ref(),
            )
            .unwrap()
            .unwrap();
        let session = fixture
            .runtime
            .open_session(&request, &control, &publication, &deadline)
            .unwrap();
        let observer = session.observer();
        let io = Arc::new(
            IoRuntime::new(IoLimits {
                maximum_running_calls: 1,
                ..IoLimits::default()
            })
            .unwrap(),
        );
        let gate = Arc::new(Semaphore::new(0));
        let started = Arc::new(Notify::new());
        let retained = Arc::new(Mutex::new(None));
        let stop = Arc::new(Mutex::new(None));
        let mut store = Store::new(
            engine,
            State {
                session,
                io: Arc::clone(&io),
                provider_ready: Arc::clone(&gate),
                started: Arc::clone(&started),
                retained: Arc::clone(&retained),
                stop: Arc::clone(&stop),
                limiter: StoreLimitsBuilder::new()
                    .memory_size(65536)
                    .instances(4)
                    .memories(1)
                    .build(),
            },
        );
        store.limiter(|state| &mut state.limiter);
        store.set_fuel(1_000_000).unwrap();
        store.set_hostcall_fuel(65536);
        store.set_epoch_deadline(1);
        let mut linker = Linker::new(engine);
        install(&mut linker);
        let instance = linker
            .instantiate_async(&mut store, component)
            .await
            .unwrap();
        let function = instance
            .get_typed_func::<(), (u32,)>(&mut store, "run")
            .unwrap();
        Self {
            store,
            function,
            observer,
            io,
            gate,
            started,
            retained,
            stop,
            control,
        }
    }
}
fn engine() -> (Engine, Component) {
    assert_eq!(latent_wasmtime::WASMTIME_VERSION, "47.0.4");
    let mut config = Config::new();
    config
        .wasm_component_model(true)
        .wasm_component_model_async(true)
        .consume_fuel(true)
        .epoch_interruption(true);
    let engine = Engine::new(&config).unwrap();
    let component = Component::new(&engine, async_component::bytes()).unwrap();
    (engine, component)
}
fn outcome() -> GuestOutcome {
    GuestOutcome::Returned {
        output: vec![],
        output_media_type: support::MEDIA.into(),
        consumption: BudgetConsumption::default(),
    }
}

#[tokio::test]
async fn canonical_async_guest_retains_store_and_cell_cleanup_until_consumer_retires() {
    let fixture = Fixture::new().await;
    let (engine, component) = engine();
    // One compiled component, fresh activation stores and the same logical cell.
    for _ in 0..3 {
        let mut harness = Harness::new(&fixture, &engine, &component).await;
        let mut invoke = Box::pin(harness.function.call_async(&mut harness.store, ()));
        tokio::select! {
            () = harness.started.notified() => {},
            result = &mut invoke => panic!("guest returned before provider release: {result:?}"),
        }
        let stop = harness.stop.lock().unwrap().as_ref().unwrap().clone();
        assert_eq!(stop.phase(), IoWorkPhase::WaitingProvider);
        assert_eq!(harness.io.snapshot().staged_bytes, 32);
        assert_eq!(harness.io.snapshot().occupied_running_slots, 1);
        assert!(!harness.observer.is_closed());
        harness.gate.add_permits(1);
        assert_eq!(invoke.await.unwrap(), (42,));
        drop(harness.store);
        let report = harness.observer.after_store_dropped(Ok(outcome()));
        assert!(matches!(
            report.cleanup,
            ExecutionCleanup::Quarantine { .. }
        ));
        assert_eq!(stop.phase(), IoWorkPhase::Cleaning);
        assert_eq!(harness.io.snapshot().result_bytes, 32);
        assert_eq!(harness.io.snapshot().streams, 1);
        drop(harness.retained.lock().unwrap().take());
        assert_eq!(stop.phase(), IoWorkPhase::Retired);
        assert!(harness.observer.is_quiescent());
        assert_eq!(harness.io.snapshot(), IoSnapshot::default());
        // Reclamation does not automatically unquarantine a scheduler cell.
        // A subsequent invocation here uses a fresh harness/store.
    }
    fixture.idle();
}

#[tokio::test]
async fn canonical_async_cancellation_and_shutdown_stop_delivery_and_acknowledge_cleanup() {
    let fixture = Fixture::new().await;
    let (engine, component) = engine();
    for shutdown in [false, true] {
        let mut harness = Harness::new(&fixture, &engine, &component).await;
        let mut invoke = Box::pin(harness.function.call_async(&mut harness.store, ()));
        tokio::select! {
            () = harness.started.notified() => {},
            result = &mut invoke => panic!("guest returned before cancellation: {result:?}"),
        }
        assert_eq!(harness.io.snapshot().staged_bytes, 32);
        if shutdown {
            harness.io.retire();
        } else {
            harness.control.probe.0.store(true, Ordering::Release);
        }
        assert!(tokio::time::timeout(Duration::from_secs(2), invoke)
            .await
            .unwrap()
            .is_err());
        drop(harness.store);
        assert!(harness.retained.lock().unwrap().is_none());
        assert_eq!(harness.io.snapshot(), IoSnapshot::default());
        assert_eq!(
            harness
                .observer
                .after_store_dropped(Err(PlatformError {
                    code: PlatformErrorCode::Cancelled,
                    message: "stopped".into(),
                    retryable: false,
                    details: vec![]
                }))
                .cleanup,
            ExecutionCleanup::Reusable
        );
    }
}

#[tokio::test]
async fn completed_async_consumers_allow_reuse_and_unpolled_guests_start_no_io() {
    let fixture = Fixture::new().await;
    let (engine, component) = engine();
    let mut harness = Harness::new(&fixture, &engine, &component).await;
    let unpolled = Box::pin(harness.function.call_async(&mut harness.store, ()));
    assert_eq!(harness.io.snapshot(), IoSnapshot::default());
    drop(unpolled);
    // A synchronous completion of an async import uses the canonical RETURNED
    // path. The delayed tests above take STARTED and wait for the real subtask.
    harness.gate.add_permits(1);
    assert_eq!(
        harness
            .function
            .call_async(&mut harness.store, ())
            .await
            .unwrap(),
        (42,)
    );
    drop(harness.retained.lock().unwrap().take());
    assert_eq!(harness.io.snapshot(), IoSnapshot::default());
    assert!(!harness.observer.is_closed());
    drop(harness.store);
    assert_eq!(
        harness.observer.after_store_dropped(Ok(outcome())).cleanup,
        ExecutionCleanup::Reusable
    );
}
