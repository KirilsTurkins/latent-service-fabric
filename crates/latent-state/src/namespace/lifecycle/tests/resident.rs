//! Actual namespace stamps retain the prepaid native owner until destruction.
use super::*;
use latent_core::{
    native_capacity::{
        NativeAdmissionClass, NativeBufferClass, NativeCapacityLimits, NativeCapacityOwner,
        NativeReservation, NativeReservationRequest,
    },
    ActivationClock, ClockSample,
};
use std::{
    sync::{atomic::AtomicU64, mpsc, Condvar},
    time::{Duration, Instant},
};

fn limits() -> NamespaceLifecycleLimits {
    NamespaceLifecycleLimits {
        namespaces: 2,
        owners: 2,
    }
}

fn reservation(
    native: &NativeCapacityOwner,
    class: NativeAdmissionClass,
    bytes: u64,
) -> Arc<NativeReservation> {
    Arc::new(
        native
            .reserve(
                class,
                NativeReservationRequest {
                    work_bytes: bytes,
                    ..NativeReservationRequest::default()
                },
                Instant::now() + Duration::from_secs(20),
            )
            .unwrap(),
    )
}

#[test]
fn same_global_recovery_owner_is_required_before_lifecycle_metadata_allocation() {
    let native = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
    let foreign = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
    let bytes = NamespaceLifecycleRegistry::retained_memory_bytes(limits()).unwrap();
    let original = reservation(&native, NativeAdmissionClass::Recovery, bytes);
    assert!(matches!(
        NamespaceLifecycleRegistry::with_retained_capacity(
            limits(),
            &foreign,
            Arc::clone(&original)
        ),
        Err(NamespaceError::Invalid)
    ));
    let ordinary = reservation(&native, NativeAdmissionClass::Ordinary, bytes);
    assert!(matches!(
        NamespaceLifecycleRegistry::with_retained_capacity(
            limits(),
            &native,
            Arc::clone(&ordinary)
        ),
        Err(NamespaceError::Invalid)
    ));
    let catalog = NamespaceCatalog::with_retained_capacity(&native, Arc::clone(&original));
    assert!(matches!(catalog, Err(NamespaceError::Capacity)));
    let registry = NamespaceLifecycleRegistry::with_retained_capacity(
        limits(),
        &native,
        Arc::clone(&original),
    )
    .unwrap();
    assert!(registry.uses_native_capacity(&native));
    assert!(!registry.uses_native_capacity(&foreign));
    assert!(!NamespaceCatalog::new().uses_native_capacity(&native));
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    drop(registry);
    // Rejected and retired metadata allocators do not consume capacity on the
    // still retained original physical reservation.
    original
        .reserve_buffer(NativeBufferClass::Work, bytes)
        .unwrap();
}

#[test]
fn metadata_work_capacity_and_original_deadline_refuse_before_any_catalog_pin() {
    let native = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
    let bytes = NamespaceLifecycleRegistry::retained_memory_bytes(limits()).unwrap();
    let original = reservation(&native, NativeAdmissionClass::Recovery, bytes - 1);
    assert!(matches!(
        NamespaceLifecycleRegistry::with_retained_capacity(
            limits(),
            &native,
            Arc::clone(&original)
        ),
        Err(NamespaceError::Capacity)
    ));
    drop(original);
    let original = reservation(&native, NativeAdmissionClass::Recovery, bytes);
    let buffer = original
        .reserve_buffer(NativeBufferClass::Work, bytes)
        .unwrap();
    assert!(matches!(
        NamespaceLifecycleRegistry::with_retained_capacity(
            limits(),
            &native,
            Arc::clone(&original)
        ),
        Err(NamespaceError::Capacity)
    ));
    drop(buffer);
    native.close();
    assert!(matches!(
        NamespaceLifecycleRegistry::with_retained_capacity(
            limits(),
            &native,
            Arc::clone(&original)
        ),
        Err(NamespaceError::Unavailable)
    ));
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
}

#[test]
fn actual_handles_and_unresolved_completions_keep_prepaid_metadata_after_catalog_close() {
    let fixture = Fixture::new();
    let read = fixture.create("retained");
    let native = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
    let bytes = NamespaceLifecycleRegistry::retained_memory_bytes(limits()).unwrap();
    let original = reservation(&native, NativeAdmissionClass::Recovery, bytes);
    let registry = NamespaceLifecycleRegistry::with_retained_capacity(
        limits(),
        &native,
        Arc::clone(&original),
    )
    .unwrap();
    let handle = registry.pin(&read).unwrap();
    let after = read
        .record()
        .transition(read.record().version, &NamespaceTransition::Quiesce, 0)
        .unwrap();
    let completion = registry.begin_transition(&read, &after, false).unwrap();
    assert!(original.reserve_buffer(NativeBufferClass::Work, 1).is_err());
    drop(original);
    drop(registry);
    assert_eq!(
        handle.with_current(&read, false, || Ok(())),
        Err(NamespaceError::Unavailable)
    );
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    drop(handle);
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    // No successful resolve is fabricated. Uncertainty stays closed, while the
    // last actual completion still owns its pending record and native keeper.
    drop(completion);
    assert!(native.snapshot().unwrap().physically_retired());
}

struct Gate {
    released: Mutex<bool>,
    wake: Condvar,
}
struct Release(Arc<Gate>);
impl Drop for Release {
    fn drop(&mut self) {
        *self.0.released.lock().unwrap() = true;
        self.0.wake.notify_one();
    }
}

#[test]
fn actual_last_stamp_destructor_releases_the_original_metadata_keeper_only_after_retirement() {
    let fixture = Fixture::new();
    let read = fixture.create("destructor");
    let native = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
    let bytes = NamespaceLifecycleRegistry::retained_memory_bytes(limits()).unwrap();
    let original = reservation(&native, NativeAdmissionClass::Recovery, bytes);
    let registry = NamespaceLifecycleRegistry::with_retained_capacity(
        limits(),
        &native,
        Arc::clone(&original),
    )
    .unwrap();
    let handle = registry.pin(&read).unwrap();
    let gate = Arc::new(Gate {
        released: Mutex::new(false),
        wake: Condvar::new(),
    });
    let release = Release(Arc::clone(&gate));
    let (entered, observed) = mpsc::sync_channel(1);
    let mut entries = registry.entries.lock().unwrap();
    let stamp = Arc::get_mut(&mut entries[0]);
    assert!(
        stamp.is_none(),
        "the live handle must retain the actual stamp"
    );
    drop(entries);
    // The observer itself is attached before pinning the independent stamp;
    // no fake retired boolean or timeout refunds native ownership.
    drop(handle);
    let mut entries = registry.entries.lock().unwrap();
    let stamp = Arc::get_mut(&mut entries[0]).unwrap();
    let blocked = Arc::clone(&gate);
    stamp.retirement_observer = Some(Arc::new(move || {
        entered.send(()).unwrap();
        let held = blocked.released.lock().unwrap();
        let (released, timeout) = blocked
            .wake
            .wait_timeout_while(held, Duration::from_secs(5), |released| !*released)
            .unwrap();
        assert!(!timeout.timed_out() && *released);
    }));
    drop(entries);
    let handle = registry.pin(&read).unwrap();
    drop(original);
    drop(registry);
    std::thread::scope(|scope| {
        let retiring = scope.spawn(move || drop(handle));
        observed.recv_timeout(Duration::from_secs(5)).unwrap();
        let snapshot = native.snapshot().unwrap();
        assert_eq!(snapshot.recovery.slots, 1);
        assert!(!snapshot.physically_retired());
        drop(release);
        retiring.join().unwrap();
    });
    assert!(native.snapshot().unwrap().physically_retired());
}

#[test]
fn retained_metadata_footprint_covers_maximum_record_and_pin_shapes() {
    let maximum = NamespaceLifecycleLimits::default();
    let bytes = NamespaceLifecycleRegistry::retained_memory_bytes(maximum).unwrap();
    assert!(bytes <= 16 * 1024 * 1024);
    let native = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
    let original = reservation(&native, NativeAdmissionClass::Recovery, bytes);
    let catalog = NamespaceCatalog::with_retained_capacity(&native, Arc::clone(&original)).unwrap();
    assert!(catalog.uses_native_capacity(&native));
    let record = NamespaceRecord::create(
        TenantId("t".repeat(256)),
        StateNamespaceId("n".repeat(256)),
        format!("sha256:{}", "f".repeat(64)),
        NamespaceQuota::default(),
    )
    .unwrap();
    let completion = catalog.lifecycle().begin_create(&record).unwrap();
    let entries = catalog.lifecycle().entries.lock().unwrap();
    assert_eq!(entries.capacity(), maximum.namespaces);
    let state = entries[0].state.lock().unwrap();
    assert_eq!(state.record, record);
    assert_eq!(state.pending.as_ref(), Some(&record));
    drop(state);
    drop(entries);
    drop(original);
    drop(catalog);
    assert!(!native.snapshot().unwrap().physically_retired());
    drop(completion);
    assert!(native.snapshot().unwrap().physically_retired());
    for invalid in [
        NamespaceLifecycleLimits {
            namespaces: 0,
            owners: 1,
        },
        NamespaceLifecycleLimits {
            namespaces: 1,
            owners: usize::MAX,
        },
    ] {
        assert_eq!(
            NamespaceLifecycleRegistry::retained_memory_bytes(invalid),
            Err(NamespaceError::Invalid)
        );
    }
}

struct Clock {
    origin: Instant,
    millis: AtomicU64,
}
impl ActivationClock for Clock {
    fn sample(&self) -> ClockSample {
        ClockSample::new(1000, self.monotonic_now())
    }
    fn monotonic_now(&self) -> Instant {
        self.origin + Duration::from_millis(self.millis.load(Ordering::SeqCst))
    }
}

#[test]
fn owner_expiry_stops_initial_allocation_without_revoking_later_current_namespace_authority() {
    let fixture = Fixture::new();
    let read = fixture.create("original-clock");
    let clock = Arc::new(Clock {
        origin: Instant::now(),
        millis: AtomicU64::new(0),
    });
    let native =
        NativeCapacityOwner::with_clock(NativeCapacityLimits::default(), clock.clone()).unwrap();
    let bytes = NamespaceLifecycleRegistry::retained_memory_bytes(limits()).unwrap();
    let original = Arc::new(
        native
            .reserve(
                NativeAdmissionClass::Recovery,
                NativeReservationRequest {
                    work_bytes: bytes,
                    ..NativeReservationRequest::default()
                },
                clock.origin + Duration::from_secs(2),
            )
            .unwrap(),
    );
    let registry = NamespaceLifecycleRegistry::with_retained_capacity(
        limits(),
        &native,
        Arc::clone(&original),
    )
    .unwrap();
    let handle = registry.pin(&read).unwrap();
    clock.millis.store(2000, Ordering::SeqCst);
    assert!(original.with_live(|| ()).is_err());
    assert!(matches!(
        NamespaceLifecycleRegistry::with_retained_capacity(
            limits(),
            &native,
            Arc::clone(&original)
        ),
        Err(NamespaceError::Unavailable)
    ));
    // Resident native capacity is physical retention only. This lifecycle
    // callback still requires separate current policy/request authority at
    // its actual caller; an expired startup allowance is never renewed.
    handle.with_current(&read, false, || Ok(())).unwrap();
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    drop(original);
    drop(registry);
    drop(handle);
    assert!(native.snapshot().unwrap().physically_retired());
}
