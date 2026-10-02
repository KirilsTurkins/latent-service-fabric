use std::task::{Context, Wake, Waker};
use std::time::Duration;

use latent_core::native_capacity::{
    NativeAdmissionClass, NativeCapacityLimits, NativeCapacityOwner, NativeReservation,
    NativeReservationRequest,
};
use latent_core::test_support::coordination::PauseTicket;

use super::*;
use crate::embedded::ReadView;
use crate::store_identity::StoreIdentity;

const VALIDATOR_BYTES: u64 = 4096;

fn identity() -> StoreIdentity {
    StoreIdentity::new("resident-memory-test".into()).unwrap()
}

fn validate_identity(view: &ReadView) -> Result<(), StoreError> {
    super::super::physical::validate_records(view, &mut StoreIdentity::validate_row)
}

fn memory(
    config: &ProtectedStoreConfig,
    clock: &TestClock,
) -> (
    NativeCapacityOwner,
    Arc<NativeReservation>,
    ProtectedStoreStartupMemory,
) {
    let work_bytes = config.startup_memory_bytes(VALIDATOR_BYTES).unwrap();
    let native =
        NativeCapacityOwner::with_clock(NativeCapacityLimits::default(), Arc::new(clock.clone()))
            .unwrap();
    let original = Arc::new(
        native
            .reserve(
                NativeAdmissionClass::Recovery,
                NativeReservationRequest {
                    work_bytes,
                    ..NativeReservationRequest::default()
                },
                clock.monotonic_now() + Duration::from_secs(10),
            )
            .unwrap(),
    );
    let memory = ProtectedStoreStartupMemory::new(&native, Arc::clone(&original)).unwrap();
    (native, original, memory)
}

fn paused_validator(
    worker: Rendezvous,
    notice: mpsc::Sender<(std::thread::ThreadId, PauseTicket)>,
) -> impl FnOnce(&ReadView) -> Result<(), StoreError> + Send + 'static {
    move |view| {
        validate_identity(view)?;
        let (registration, mut physical) = worker.track(view.identity()).unwrap();
        physical.commit(Stage::Entered).unwrap();
        let mut parked = Box::pin(physical.pause());
        PollProbe::default().pending(parked.as_mut());
        notice
            .send((
                std::thread::current().id(),
                worker.blocked(registration, Stage::Entered).unwrap(),
            ))
            .unwrap();
        block_on(parked);
        validate_identity(view)
    }
}

fn drain_startup(startup: &ProtectedStoreStartup, clock: &TestClock) {
    let shutdown = wait(
        startup
            .drain_async(clock.monotonic_now() + WATCHDOG, std::future::pending())
            .unwrap(),
    );
    assert!(!shutdown.clean);
    assert!(shutdown.snapshot.physically_retired());
}

fn reopen(config: ProtectedStoreConfig) -> ProtectedStoreOwner {
    wait(
        ProtectedStoreOwner::start_validated_view(config, VALIDATOR_BYTES, validate_identity)
            .unwrap(),
    )
    .unwrap()
}

fn inspect_identity(store: &ProtectedStoreOwner) -> Option<StoreIdentity> {
    wait(
        store
            .with_store(crate::store_io::StoreIoKind::Read, 4096, |engine| {
                StoreIdentity::inspect(&engine.snapshot()?)
            })
            .unwrap(),
    )
    .unwrap()
    .unwrap()
}

#[test]
fn prepaid_startup_binding_and_resident_owner_survive_until_real_engine_root_retirement() {
    let (_root, config) = fixture();
    let clock = TestClock::new(1000, Instant::now(), 1);
    let (native, original, memory) = memory(&config, &clock);
    let witness = Arc::downgrade(&original);
    let store = wait(
        ProtectedStoreOwner::start_bound_retained_validated_view_with_clock(
            config.clone(),
            identity(),
            memory,
            VALIDATOR_BYTES,
            validate_identity,
            Arc::new(clock),
        )
        .unwrap(),
    )
    .unwrap();
    assert!(store.uses_native_capacity(&native));
    assert!(store.native_capacity().unwrap().is_same_owner(&native));
    store.bind_native_capacity(&native).unwrap();
    let foreign = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
    assert_eq!(
        store.bind_native_capacity(&foreign),
        Err(ProtectedStoreError::InvalidConfiguration)
    );
    drop(original);
    assert!(witness.upgrade().is_some());
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    // The first real storage callback already sees the correct sealed owner.
    assert_eq!(inspect_identity(&store), Some(identity()));
    drop(
        wait(store.take_initialization_witness().unwrap())
            .unwrap()
            .unwrap()
            .unwrap(),
    );
    assert!(finish(&store).clean);
    assert!(witness.upgrade().is_none());
    assert!(native.snapshot().unwrap().physically_retired());
    let reopened = reopen(config);
    assert_eq!(inspect_identity(&reopened), Some(identity()));
    assert!(finish(&reopened).clean);
}

#[test]
fn detached_drain_cannot_refund_resident_memory_during_actual_native_store_destructor() {
    let (_root, config) = fixture();
    let clock = TestClock::new(1000, Instant::now(), 1);
    let (native, original, memory) = memory(&config, &clock);
    let witness = Arc::downgrade(&original);
    let store = wait(
        ProtectedStoreOwner::start_bound_retained_validated_view_with_clock(
            config.clone(),
            identity(),
            memory,
            VALIDATOR_BYTES,
            validate_identity,
            Arc::new(clock.clone()),
        )
        .unwrap(),
    )
    .unwrap();
    let pause = Rendezvous::new(1);
    let worker = pause.clone();
    let (notice, receiver) = mpsc::channel();
    wait(
        store
            .ready
            .submit(crate::store_io::StoreIoKind::Write, 4096, move |physical| {
                physical.install_drop_probe(move || {
                    let (registration, mut native) = worker.track(()).unwrap();
                    native.commit(Stage::Entered).unwrap();
                    let mut parked = Box::pin(native.pause());
                    PollProbe::default().pending(parked.as_mut());
                    notice
                        .send(worker.blocked(registration, Stage::Entered).unwrap())
                        .unwrap();
                    block_on(parked);
                });
            })
            .unwrap(),
    )
    .unwrap();
    drop(original);
    let mut drain = Box::pin(
        store
            .drain_async(clock.monotonic_now() + WATCHDOG, std::future::pending())
            .unwrap(),
    );
    PollProbe::default().pending(drain.as_mut());
    let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
    drop(drain);
    assert!(witness.upgrade().is_some());
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    assert!(!store.snapshot().unwrap().physically_retired());
    assert_eq!(
        failed_start(config.clone()),
        ProtectedStoreError::Store(StoreError::Unavailable)
    );
    // Native destructor completion, never dropped-waiter/deadline inference,
    // is the positive release of the original global resident owner.
    pause.release(ticket).unwrap();
    assert!(finish(&store).clean);
    assert!(witness.upgrade().is_none());
    assert!(native.snapshot().unwrap().physically_retired());
    let reopened = reopen(config);
    assert_eq!(inspect_identity(&reopened), Some(identity()));
    assert!(finish(&reopened).clean);
}

#[test]
fn detached_initializer_keeps_global_memory_and_real_root_lock_until_worker_cleanup() {
    let (_root, config) = fixture();
    let clock = TestClock::new(1000, Instant::now(), 1);
    let (native, original, memory) = memory(&config, &clock);
    let witness = Arc::downgrade(&original);
    let pause = Rendezvous::new(1);
    let (notice, receiver) = mpsc::channel();
    let mut startup = Box::pin(
        ProtectedStoreOwner::start_bound_retained_validated_view_with_clock(
            config.clone(),
            identity(),
            memory,
            VALIDATOR_BYTES,
            paused_validator(pause.clone(), notice),
            Arc::new(clock.clone()),
        )
        .unwrap(),
    );
    let (worker, ticket) = receiver.recv_timeout(WATCHDOG).unwrap();
    assert_ne!(worker, std::thread::current().id());
    PollProbe::default().pending(startup.as_mut());
    drop(startup);
    drop(original);
    assert!(witness.upgrade().is_some());
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    assert_eq!(
        failed_start(config.clone()),
        ProtectedStoreError::Store(StoreError::Unavailable)
    );
    let drain = native
        .drain_async(clock.monotonic_now() + WATCHDOG, std::future::pending())
        .unwrap();
    pause.release(ticket).unwrap();
    let shutdown = wait(drain);
    assert!(shutdown.clean);
    assert!(shutdown.snapshot.physically_retired());
    assert!(witness.upgrade().is_none());
    let reopened = reopen(config);
    assert!(finish(&reopened).clean);
}

#[test]
fn original_startup_deadline_expiring_under_real_validator_cannot_publish_identity_or_ready() {
    let (_root, config) = fixture();
    let clock = TestClock::new(1000, Instant::now(), 1);
    let (native, original, memory) = memory(&config, &clock);
    let witness = Arc::downgrade(&original);
    let pause = Rendezvous::new(1);
    let (notice, receiver) = mpsc::channel();
    let mut startup = Box::pin(
        ProtectedStoreOwner::start_bound_retained_validated_view_with_clock(
            config.clone(),
            identity(),
            memory,
            VALIDATOR_BYTES,
            paused_validator(pause.clone(), notice),
            Arc::new(clock.clone()),
        )
        .unwrap(),
    );
    let (_, ticket) = receiver.recv_timeout(WATCHDOG).unwrap();
    clock.advance(Duration::from_secs(10));
    drop(original);
    assert!(witness.upgrade().is_some());
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    pause.release(ticket).unwrap();
    assert_eq!(
        wait(startup.as_mut()).err(),
        Some(ProtectedStoreError::Io(StoreIoError::AdmissionClosed))
    );
    drain_startup(&startup, &clock);
    assert!(witness.upgrade().is_none());
    assert!(native.snapshot().unwrap().physically_retired());
    assert!(!native.snapshot().unwrap().quarantined);
    let reopened = reopen(config);
    assert_eq!(inspect_identity(&reopened), None);
    assert!(finish(&reopened).clean);
}

struct Completed(mpsc::SyncSender<()>);

impl Wake for Completed {
    fn wake(self: Arc<Self>) {
        let _ = self.0.try_send(());
    }

    fn wake_by_ref(self: &Arc<Self>) {
        let _ = self.0.try_send(());
    }
}

#[test]
fn expired_ready_delivery_quarantines_and_retains_native_store_until_positive_drain() {
    let (_root, config) = fixture();
    let clock = TestClock::new(1000, Instant::now(), 1);
    let (native, original, memory) = memory(&config, &clock);
    let witness = Arc::downgrade(&original);
    let pause = Rendezvous::new(1);
    let (notice, receiver) = mpsc::channel();
    let mut startup = Box::pin(
        ProtectedStoreOwner::start_bound_retained_validated_view_with_clock(
            config.clone(),
            identity(),
            memory,
            VALIDATOR_BYTES,
            paused_validator(pause.clone(), notice),
            Arc::new(clock.clone()),
        )
        .unwrap(),
    );
    let (_, ticket) = receiver.recv_timeout(WATCHDOG).unwrap();
    let (completed, completion) = mpsc::sync_channel(1);
    let waker = Waker::from(Arc::new(Completed(completed)));
    assert!(startup
        .as_mut()
        .poll(&mut Context::from_waker(&waker))
        .is_pending());
    pause.release(ticket).unwrap();
    // This wake follows the real successful native initializer/response.
    completion.recv_timeout(WATCHDOG).unwrap();
    clock.advance(Duration::from_secs(10));
    drop(original);
    assert_eq!(
        PollProbe::default().ready(startup.as_mut()).err(),
        Some(ProtectedStoreError::Io(StoreIoError::AdmissionClosed))
    );
    assert!(startup.snapshot().unwrap().quarantined);
    drain_startup(&startup, &clock);
    assert!(witness.upgrade().is_none());
    assert!(native.snapshot().unwrap().physically_retired());
    let reopened = reopen(config);
    // Late Ready denial cannot erase the initializer's already committed row
    // or manufacture a new missing-checkpoint initialization witness.
    assert_eq!(inspect_identity(&reopened), Some(identity()));
    assert!(wait(reopened.take_initialization_witness().unwrap())
        .unwrap()
        .unwrap()
        .is_none());
    assert!(finish(&reopened).clean);
}
