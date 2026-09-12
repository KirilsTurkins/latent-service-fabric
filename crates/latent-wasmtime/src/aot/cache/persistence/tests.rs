use super::*;
use latent_artifacts::RawArtifactCacheLimits;
use sha2::{Digest, Sha256};
use std::{
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};

struct Fixture {
    cache: Arc<RawArtifactCache>,
    path: PathBuf,
}

impl Fixture {
    fn new(limits: RawArtifactCacheLimits) -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "lsf-native-persist-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir(&path).unwrap();
        let cache = RawArtifactCache::open(&path, limits).unwrap();
        Self { cache, path }
    }
    fn path(&self, bytes: &[u8]) -> PathBuf {
        self.path
            .join("objects")
            .join(format!("b-{:x}", Sha256::digest(bytes)))
            .join("data")
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        std::fs::remove_dir_all(&self.path).unwrap();
    }
}
fn key(bytes: &[u8]) -> RawArtifactKey {
    RawArtifactKey::Blob(
        format!("sha256:{:x}", Sha256::digest(bytes))
            .parse()
            .unwrap(),
    )
}

#[test]
fn verified_deduplication_returns_a_pin_and_refunds_read_bytes() {
    let fixture = Fixture::new(RawArtifactCacheLimits::default());
    let bytes = b"native";
    drop(persist_blob(&fixture.cache, &key(bytes), bytes).unwrap());
    let pin = persist_blob(&fixture.cache, &key(bytes), bytes).unwrap();
    assert_eq!(
        fixture.cache.evict(&key(bytes)).unwrap(),
        RawArtifactEviction::Pinned
    );
    let snapshot = fixture.cache.snapshot().unwrap();
    assert_eq!(snapshot.retained_read_bytes, 0);
    assert_eq!(snapshot.reserved_read_bytes, 0);
    assert_eq!(snapshot.evictions, 0);
    drop(pin);
    assert_eq!(
        fixture.cache.evict(&key(bytes)).unwrap(),
        RawArtifactEviction::Removed
    );
}

#[test]
fn same_size_and_truncated_existing_native_bytes_are_replaced_exactly_once() {
    for damaged in [b"broken".as_slice(), b"bad".as_slice()] {
        let fixture = Fixture::new(RawArtifactCacheLimits::default());
        let bytes = b"native";
        drop(persist_blob(&fixture.cache, &key(bytes), bytes).unwrap());
        std::fs::write(fixture.path(bytes), damaged).unwrap();
        let pin = persist_blob(&fixture.cache, &key(bytes), bytes).unwrap();
        assert_eq!(
            pin.reserve_read(bytes.len() as u64)
                .unwrap()
                .read_verified()
                .unwrap()
                .as_bytes(),
            bytes
        );
        assert_eq!(fixture.cache.snapshot().unwrap().evictions, 1);
        drop(persist_blob(&fixture.cache, &key(bytes), bytes).unwrap());
        assert_eq!(fixture.cache.snapshot().unwrap().evictions, 1);
    }
}

#[test]
fn missing_existing_native_file_is_repaired_without_trusting_its_pin() {
    let fixture = Fixture::new(RawArtifactCacheLimits::default());
    let bytes = b"native";
    drop(persist_blob(&fixture.cache, &key(bytes), bytes).unwrap());
    std::fs::remove_file(fixture.path(bytes)).unwrap();
    drop(persist_blob(&fixture.cache, &key(bytes), bytes).unwrap());
    assert_eq!(std::fs::read(fixture.path(bytes)).unwrap(), bytes);
    assert_eq!(fixture.cache.snapshot().unwrap().evictions, 1);
}

#[test]
fn deduplication_read_pressure_does_not_delete_or_claim_success() {
    let fixture = Fixture::new(RawArtifactCacheLimits {
        maximum_read_bytes: 1,
        ..Default::default()
    });
    let bytes = b"native";
    drop(persist_blob(&fixture.cache, &key(bytes), bytes).unwrap());
    assert_eq!(
        persist_blob(&fixture.cache, &key(bytes), bytes)
            .err()
            .unwrap()
            .message,
        "raw-cache-capacity"
    );
    let snapshot = fixture.cache.snapshot().unwrap();
    assert_eq!(snapshot.evictions, 0);
    assert_eq!(snapshot.pins, 0);
    assert_eq!(std::fs::read(fixture.path(bytes)).unwrap(), bytes);
}

#[test]
fn an_independent_pin_prevents_corrupt_file_replacement_until_released() {
    let fixture = Fixture::new(RawArtifactCacheLimits::default());
    let bytes = b"native";
    let other = persist_blob(&fixture.cache, &key(bytes), bytes).unwrap();
    std::fs::write(fixture.path(bytes), b"broken").unwrap();
    assert_eq!(
        persist_blob(&fixture.cache, &key(bytes), bytes)
            .err()
            .unwrap()
            .message,
        "native-cache-persistence-busy"
    );
    assert_eq!(fixture.cache.snapshot().unwrap().evictions, 0);
    drop(other);
    drop(persist_blob(&fixture.cache, &key(bytes), bytes).unwrap());
    assert_eq!(std::fs::read(fixture.path(bytes)).unwrap(), bytes);
    assert_eq!(fixture.cache.snapshot().unwrap().evictions, 1);
}

#[test]
fn one_entry_cache_reclaims_with_its_small_configured_recovery_bound() {
    let fixture = Fixture::new(RawArtifactCacheLimits {
        maximum_entries: 1,
        maximum_recovery_entries: 2,
        ..Default::default()
    });
    drop(persist_blob(&fixture.cache, &key(b"old"), b"old").unwrap());
    drop(persist_blob(&fixture.cache, &key(b"new"), b"new").unwrap());
    assert_eq!(fixture.cache.snapshot().unwrap().evictions, 1);
    assert_eq!(std::fs::read(fixture.path(b"new")).unwrap(), b"new");
    assert!(!fixture.path(b"old").exists());
}
