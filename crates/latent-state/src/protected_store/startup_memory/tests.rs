use std::time::{Duration, Instant};

use latent_core::native_capacity::{NativeCapacityLimits, NativeReservationRequest};
use latent_core::test_support::TestClock;
use latent_core::ActivationClock;

use super::*;

fn fixture() -> (ProtectedStoreConfig, NativeCapacityOwner, TestClock) {
    let config = ProtectedStoreConfig::bounded_linux(std::env::temp_dir());
    let clock = TestClock::new(100, Instant::now(), 1);
    let owner =
        NativeCapacityOwner::with_clock(NativeCapacityLimits::default(), Arc::new(clock.clone()))
            .unwrap();
    (config, owner, clock)
}

fn reserve(
    owner: &NativeCapacityOwner,
    clock: &TestClock,
    class: NativeAdmissionClass,
    work_bytes: u64,
) -> Arc<NativeReservation> {
    Arc::new(
        owner
            .reserve(
                class,
                NativeReservationRequest {
                    work_bytes,
                    ..NativeReservationRequest::default()
                },
                clock.monotonic_now() + Duration::from_secs(10),
            )
            .unwrap(),
    )
}

#[test]
fn startup_sizing_rejects_overflow_and_independent_job_resident_ceiling_pressure() {
    let (config, native, _) = fixture();
    let size = startup_memory_size(&config, 4096).unwrap();
    assert_eq!(config.startup_memory_bytes(4096), Ok(size.total));
    assert!(size.initialization > 8 * 1024 * 1024);
    assert_eq!(size.total, size.initialization + config.io.resident_bytes);
    assert_eq!(
        config.startup_memory_bytes(u64::MAX),
        Err(ProtectedStoreError::InvalidConfiguration)
    );
    let mut job_pressure = config.clone();
    job_pressure.io.job_bytes = size.initialization - 1;
    assert_eq!(
        job_pressure.startup_memory_bytes(4096),
        Err(ProtectedStoreError::InvalidConfiguration)
    );
    let mut resident_pressure = config;
    resident_pressure.io.retained_bytes = size.total - 1;
    assert_eq!(
        resident_pressure.startup_memory_bytes(4096),
        Err(ProtectedStoreError::InvalidConfiguration)
    );
    assert!(native.snapshot().unwrap().physically_retired());
}

#[test]
fn startup_memory_refuses_foreign_and_ordinary_original_owners_without_quarantine() {
    let (config, native, clock) = fixture();
    let bytes = config.startup_memory_bytes(0).unwrap();
    let foreign = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
    let recovery = reserve(&native, &clock, NativeAdmissionClass::Recovery, bytes);
    assert_eq!(
        ProtectedStoreStartupMemory::new(&foreign, Arc::clone(&recovery)).err(),
        Some(ProtectedStoreError::InvalidConfiguration)
    );
    let ordinary = reserve(&native, &clock, NativeAdmissionClass::Ordinary, bytes);
    assert_eq!(
        ProtectedStoreStartupMemory::new(&native, Arc::clone(&ordinary)).err(),
        Some(ProtectedStoreError::InvalidConfiguration)
    );
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    assert_eq!(native.snapshot().unwrap().ordinary.slots, 1);
    assert!(!native.snapshot().unwrap().quarantined);
    assert!(foreign.snapshot().unwrap().physically_retired());
    drop(recovery);
    drop(ordinary);
    assert!(native.snapshot().unwrap().physically_retired());
}

#[test]
fn startup_memory_prepays_both_native_parts_before_any_engine_allocation() {
    let (config, native, clock) = fixture();
    let size = startup_memory_size(&config, 0).unwrap();
    let original = reserve(&native, &clock, NativeAdmissionClass::Recovery, size.total);
    let prepared = ProtectedStoreStartupMemory::new(&native, Arc::clone(&original))
        .unwrap()
        .prepare(&size)
        .unwrap();
    assert!(matches!(
        original.reserve_buffer(NativeBufferClass::Work, 1),
        Err(NativeCapacityError::BufferTooLarge)
    ));
    drop(prepared.initialization);
    let reclaimed = original
        .reserve_buffer(NativeBufferClass::Work, size.initialization)
        .unwrap();
    assert!(matches!(
        original.reserve_buffer(NativeBufferClass::Work, 1),
        Err(NativeCapacityError::BufferTooLarge)
    ));
    drop(reclaimed);
    drop(prepared.resident);
    drop(prepared.original);
    drop(prepared.binding);
    drop(original);
    assert!(native.snapshot().unwrap().physically_retired());
}

#[test]
fn refused_resident_part_rolls_back_only_unused_initialization_memory() {
    let (config, native, clock) = fixture();
    let size = startup_memory_size(&config, 0).unwrap();
    let original = reserve(&native, &clock, NativeAdmissionClass::Recovery, size.total);
    let prior_buffer = original.reserve_buffer(NativeBufferClass::Work, 1).unwrap();
    assert_eq!(
        ProtectedStoreStartupMemory::new(&native, Arc::clone(&original))
            .unwrap()
            .prepare(&size)
            .err(),
        Some(ProtectedStoreError::Store(StoreError::Capacity))
    );
    assert!(matches!(
        original.reserve_buffer(NativeBufferClass::Work, size.total),
        Err(NativeCapacityError::BufferTooLarge)
    ));
    let remaining = original
        .reserve_buffer(NativeBufferClass::Work, size.total - 1)
        .unwrap();
    assert!(!native.snapshot().unwrap().quarantined);
    drop(original);
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    drop(remaining);
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    drop(prior_buffer);
    assert!(native.snapshot().unwrap().physically_retired());
}

#[test]
fn expired_original_admission_still_retains_resident_memory_until_physical_drop() {
    let (config, native, clock) = fixture();
    let size = startup_memory_size(&config, 0).unwrap();
    let original = reserve(&native, &clock, NativeAdmissionClass::Recovery, size.total);
    let witness = Arc::downgrade(&original);
    let prepared = ProtectedStoreStartupMemory::new(&native, Arc::clone(&original))
        .unwrap()
        .prepare(&size)
        .unwrap();
    clock.advance(Duration::from_secs(10));
    assert_eq!(
        prepared.initialization.check(),
        Err(ProtectedStoreError::Io(StoreIoError::AdmissionClosed))
    );
    drop(original);
    drop(prepared.original);
    drop(prepared.binding);
    drop(prepared.initialization);
    assert!(witness.upgrade().is_some());
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    assert!(!native.snapshot().unwrap().quarantined);
    drop(prepared.resident);
    assert!(witness.upgrade().is_none());
    assert!(native.snapshot().unwrap().physically_retired());
}
