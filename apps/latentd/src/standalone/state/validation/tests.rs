use super::*;
use latent_core::{
    native_capacity::{
        NativeAdmissionClass, NativeBufferClass, NativeBufferPermit, NativeCapacityLimits,
        NativeCapacityOwner, NativeReservationRequest,
    },
    ActivationClock, ClockSample,
};
use latent_effects::authority::EffectTime;
use latent_state::{
    embedded::{AtomicBatch, EmbeddedStore, ExpectedRow, RowMutation, StoreLimits},
    tenant::TenantRecord,
};
use std::{
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};

struct Clock {
    start: Instant,
    elapsed_millis: AtomicU64,
}

impl ActivationClock for Clock {
    fn sample(&self) -> ClockSample {
        ClockSample::new(1000, self.monotonic_now())
    }

    fn monotonic_now(&self) -> Instant {
        self.start + Duration::from_millis(self.elapsed_millis.load(Ordering::SeqCst))
    }
}

struct Fixture {
    store: EmbeddedStore,
    identity: StoreIdentity,
    capacity: NativeCapacityOwner,
    clock: Arc<Clock>,
    original: NativeReservation,
    _memory: NativeBufferPermit,
}

impl Fixture {
    fn new() -> Self {
        let store = EmbeddedStore::open_file(tempfile::tempfile().unwrap(), StoreLimits::default())
            .unwrap();
        let clock = Arc::new(Clock {
            start: Instant::now(),
            elapsed_millis: AtomicU64::new(0),
        });
        let projection: Arc<dyn ActivationClock> = clock.clone();
        let capacity =
            NativeCapacityOwner::with_clock(NativeCapacityLimits::default(), projection).unwrap();
        let original = capacity
            .reserve(
                NativeAdmissionClass::Recovery,
                NativeReservationRequest {
                    request_bytes: 0,
                    work_bytes: 8 * 1024 * 1024,
                    response_bytes: 0,
                },
                clock.start + Duration::from_secs(20),
            )
            .unwrap();
        let memory = original
            .reserve_buffer(NativeBufferClass::Work, 8 * 1024 * 1024)
            .unwrap();
        Self {
            store,
            identity: StoreIdentity::new("validator-store".into()).unwrap(),
            capacity,
            clock,
            original,
            _memory: memory,
        }
    }

    fn initialize_identity(&self) {
        let view = self.store.snapshot().unwrap();
        let batch = self
            .identity
            .prepare_initialization(&view)
            .unwrap()
            .unwrap();
        drop(view);
        self.store.apply(batch).unwrap();
    }

    fn install(&self, quotas: &[TenantQuota]) {
        let view = self.store.snapshot().unwrap();
        let plan = tenant::prepare_install(&view, quotas).unwrap();
        drop(view);
        plan.publish(&self.store, || live(&self.original)).unwrap();
    }

    fn validate(&self, quotas: &[TenantQuota]) -> Result<(), StoreError> {
        validate(
            &self.store.snapshot().unwrap(),
            &self.identity,
            quotas,
            &self.original,
        )
    }

    fn replace(&self, key: RowKey, value: Option<Vec<u8>>) {
        let view = self.store.snapshot().unwrap();
        let previous = view.get(&key).unwrap();
        drop(view);
        self.store
            .apply(AtomicBatch {
                expectations: vec![ExpectedRow {
                    key: key.clone(),
                    value: previous,
                }],
                mutations: vec![RowMutation { key, value }],
            })
            .unwrap();
    }

    fn bytes(&self) -> Vec<(u8, Vec<u8>, Vec<u8>)> {
        let view = self.store.snapshot().unwrap();
        let mut rows = Vec::new();
        for family in FAMILIES {
            let page = view
                .scan_after(family, b"", None, 128, 2 * 1024 * 1024)
                .unwrap();
            assert!(page.resume.is_none());
            rows.extend(
                page.rows
                    .into_iter()
                    .map(|(key, value)| (family as u8, key.key, value)),
            );
        }
        rows
    }
}

fn quota() -> TenantQuota {
    TenantQuota {
        tenant: TenantId("tenant".into()),
        limits: TenantUsage {
            state_keys: 16,
            state_bytes: 64 * 1024,
            tombstone_keys: 16,
            tombstone_bytes: 64 * 1024,
            result_rows: 16,
            result_bytes: 64 * 1024,
            effect_rows: 16,
            effect_bytes: 64 * 1024,
            payload_bytes: 64 * 1024,
            recovery_bytes: 32 * 1024,
            metadata_rows: 64,
            metadata_bytes: 256 * 1024,
        },
    }
}

#[test]
fn empty_and_matching_identity_only_validation_never_installs_accounting_or_changes_identity() {
    let fixture = Fixture::new();
    let quotas = [quota()];
    assert_eq!(fixture.validate(&quotas), Ok(()));
    assert!(fixture.bytes().is_empty());
    fixture.initialize_identity();
    let original = fixture.bytes();
    assert_eq!(fixture.validate(&quotas), Ok(()));
    assert_eq!(fixture.bytes(), original);
    let view = fixture.store.snapshot().unwrap();
    assert!(view.get(&tenant::guard_key()).unwrap().is_none());
    assert!(fixture
        .identity
        .prepare_initialization(&view)
        .unwrap()
        .is_none());
    let different = StoreIdentity::new("different-store".into()).unwrap();
    assert_eq!(
        validate(&view, &different, &quotas, &fixture.original),
        Err(StoreError::Corrupt)
    );
    drop(view);
    assert_eq!(fixture.bytes(), original);
}

#[test]
fn zero_target_bootstrap_accepts_only_closed_global_controls_and_cannot_omit_installed_tenant_ownership(
) {
    let fixture = Fixture::new();
    fixture.initialize_identity();
    let epoch = DispatchCatalog::begin_exclusive_epoch(
        &fixture.store,
        EffectTime {
            unix_millis: 1000,
            continuity_proven: true,
        },
        None,
    )
    .unwrap();
    let original = fixture.bytes();
    assert_eq!(fixture.validate(&[]), Ok(()));
    assert_eq!(fixture.bytes(), original);
    assert_eq!(
        DispatchCatalog::checkpoint(&fixture.store.snapshot().unwrap()).unwrap(),
        Some((epoch.generation(), 1000))
    );
    fixture.install(&[quota()]);
    let installed = fixture.bytes();
    assert_eq!(fixture.validate(&[]), Err(StoreError::UnsupportedFormat));
    assert_eq!(fixture.bytes(), installed);
}

#[test]
fn nonempty_startup_requires_the_exact_installed_tenant_manifest_without_changing_any_counter() {
    let fixture = Fixture::new();
    fixture.initialize_identity();
    let quotas = [quota()];
    fixture.install(&quotas);
    let installed = fixture.bytes();
    assert_eq!(fixture.validate(&quotas), Ok(()));
    assert_eq!(fixture.bytes(), installed);
    let mut changed = quotas.clone();
    changed[0].limits.state_bytes += 1;
    assert_eq!(
        fixture.validate(&changed),
        Err(StoreError::UnsupportedFormat)
    );
    assert_eq!(fixture.bytes(), installed);
    fixture.replace(tenant::guard_key(), None);
    let missing = fixture.bytes();
    assert_eq!(
        fixture.validate(&quotas),
        Err(StoreError::UnsupportedFormat)
    );
    assert_eq!(fixture.bytes(), missing);
}

#[test]
fn unknown_closed_prefixes_and_corrupt_owned_records_cannot_be_accepted_as_opaque_startup_rows() {
    for (key, value) in [
        (
            RowKey {
                family: Family::Maintenance,
                key: b"unknown-v1\0".to_vec(),
            },
            b"opaque".to_vec(),
        ),
        (StoreIdentity::row_key(), b"LSI\0\x01".to_vec()),
        (StoreIdentity::row_key(), b"LSI\0\x02".to_vec()),
        (
            latent_effects::dispatch_store::effect_row_key(&"e".repeat(64)).unwrap(),
            b"LER\0\x02".to_vec(),
        ),
    ] {
        let fixture = Fixture::new();
        fixture.initialize_identity();
        let quotas = [quota()];
        fixture.install(&quotas);
        fixture.replace(key, Some(value));
        let unsupported = fixture.bytes();
        assert!(fixture.validate(&quotas).is_err());
        assert_eq!(fixture.bytes(), unsupported);
    }
}

#[test]
fn supported_counter_bytes_cannot_claim_unobserved_result_ownership_or_be_repaired_by_startup() {
    let fixture = Fixture::new();
    fixture.initialize_identity();
    let quotas = [quota()];
    fixture.install(&quotas);
    let key = tenant::quota_key(&quotas[0].tenant).unwrap();
    let view = fixture.store.snapshot().unwrap();
    let mut record = TenantRecord::decode(&view.get(&key).unwrap().unwrap()).unwrap();
    drop(view);
    record.generation += 1;
    record.usage.result_rows = 1;
    record.usage.result_bytes = 4096;
    let encoded = record.encode().unwrap();
    fixture.replace(key, Some(encoded));
    let counterfeit = fixture.bytes();
    assert_eq!(fixture.validate(&quotas), Err(StoreError::Corrupt));
    assert_eq!(fixture.bytes(), counterfeit);
}

#[test]
fn the_original_global_close_and_deadline_refuse_readiness_without_refunding_native_ownership() {
    for expired in [false, true] {
        let fixture = Fixture::new();
        fixture.initialize_identity();
        if expired {
            fixture.clock.elapsed_millis.store(20_000, Ordering::SeqCst);
        } else {
            fixture.capacity.close();
        }
        let original = fixture.bytes();
        assert_eq!(fixture.validate(&[]), Err(StoreError::Unavailable));
        assert_eq!(fixture.bytes(), original);
        let capacity = fixture.capacity.clone();
        assert_eq!(capacity.snapshot().unwrap().recovery.slots, 1);
        assert!(!capacity.snapshot().unwrap().physically_retired());
        drop(fixture);
        assert!(capacity.snapshot().unwrap().physically_retired());
    }
}
