mod persistence;
mod quotas;

use super::{io, AotReceiptCacheLimits, ReceiptCache};
use latent_core::ArtifactBlobDigest;
use std::path::PathBuf;
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc,
};

static NEXT: AtomicU64 = AtomicU64::new(0);

struct Directory(PathBuf);

impl Directory {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "lsf-receipts-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn open(&self, limits: AotReceiptCacheLimits) -> Arc<ReceiptCache> {
        ReceiptCache::open(&self.0, limits).unwrap()
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        io::FAIL.with(|value| value.set(None));
        std::fs::remove_dir_all(&self.0).unwrap();
    }
}

fn key(value: u8) -> ArtifactBlobDigest {
    format!("sha256:{value:064x}").parse().unwrap()
}

fn filename(value: u8) -> String {
    format!("r-{value:064x}.json")
}

fn fail(point: io::Cutpoint) {
    io::FAIL.with(|value| value.set(Some(point)));
}

#[test]
fn exact_bytes_reopen_and_affine_read_lifetime() {
    let directory = Directory::new();
    let cache = directory.open(AotReceiptCacheLimits::default());
    let bytes = vec![0x81; 8192];
    cache.publish(&key(1), &bytes).unwrap();
    let retained = cache.lookup(&key(1)).unwrap().unwrap();
    assert_eq!(retained.as_bytes(), bytes);
    assert_eq!(cache.snapshot().retained_read_bytes, 8192);
    assert_eq!(cache.snapshot().active_work, 0);
    assert_eq!(
        ReceiptCache::open(&directory.0, cache.limits())
            .err()
            .unwrap()
            .message,
        "native-receipt-cache-root-owned"
    );
    drop(cache);
    // The returned byte owner must not retain the filesystem owner lock.
    let reopened = directory.open(AotReceiptCacheLimits::default());
    assert_eq!(retained.as_bytes(), bytes);
    assert_eq!(reopened.lookup(&key(1)).unwrap().unwrap().as_bytes(), bytes);
    assert_eq!(reopened.snapshot().read_owners, 0);
}

#[test]
fn storage_does_not_parse_or_authenticate_receipts() {
    let directory = Directory::new();
    let cache = directory.open(AotReceiptCacheLimits::default());
    cache
        .publish(&key(2), b"not JSON, not a valid MAC")
        .unwrap();
    assert_eq!(
        cache.lookup(&key(2)).unwrap().unwrap().as_bytes(),
        b"not JSON, not a valid MAC"
    );
}

#[test]
fn work_gate_is_nonblocking_and_snapshot_is_independent() {
    let directory = Directory::new();
    let cache = directory.open(AotReceiptCacheLimits::default());
    cache.with_test_work(|| {
        assert_eq!(cache.snapshot().active_work, 1);
        assert_eq!(
            cache.lookup(&key(0)).err().unwrap().message,
            "native-receipt-cache-busy"
        );
    });
    assert_eq!(cache.snapshot().active_work, 0);
}

#[test]
fn missing_and_changed_indexed_files_keep_charges_until_synced_cleanup() {
    let directory = Directory::new();
    let cache = directory.open(AotReceiptCacheLimits::default());
    cache.publish(&key(1), b"original").unwrap();
    let resident = cache.snapshot().resident_disk_bytes;
    std::fs::remove_file(directory.0.join(filename(1))).unwrap();
    assert!(cache.lookup(&key(1)).unwrap().is_none());
    assert_eq!(cache.snapshot().resident_disk_bytes, resident);
    cache.reclaim(1).unwrap();
    cache.publish(&key(1), b"original").unwrap();
    std::fs::write(directory.0.join(filename(1)), b"too long replacement").unwrap();
    assert_eq!(
        cache.lookup(&key(1)).err().unwrap().message,
        "native-receipt-cache-corrupt"
    );
    assert_eq!(cache.snapshot().resident_disk_bytes, resident);
    assert_eq!(cache.snapshot().deletion_pending_bytes, 8);
    cache.reclaim(1).unwrap();
    assert_eq!(cache.snapshot().entries, 0);
}

#[test]
fn reclamation_is_bounded_and_follows_access_recency() {
    let directory = Directory::new();
    let cache = directory.open(AotReceiptCacheLimits::default());
    for value in 1..=3 {
        cache.publish(&key(value), &[value]).unwrap();
    }
    drop(cache.lookup(&key(1)).unwrap());
    assert_eq!(cache.reclaim(1).unwrap().removed_entries, 1);
    assert!(cache.lookup(&key(2)).unwrap().is_none());
    assert!(cache.lookup(&key(1)).unwrap().is_some());
    assert_eq!(cache.snapshot().entries, 2);
    assert!(cache.reclaim(0).is_err());
    assert!(cache.reclaim(17).is_err());
}
