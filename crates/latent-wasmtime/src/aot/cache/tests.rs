use super::*;
use crate::aot::supervisor::InputFixture;
use latent_artifacts::RawArtifactCacheLimits;
use std::path::PathBuf;

struct Directory(PathBuf);
impl Directory {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "lsf-native-cache-read-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir(&path).unwrap();
        Self(path)
    }
}
impl Drop for Directory {
    fn drop(&mut self) {
        std::fs::remove_dir_all(&self.0).unwrap();
    }
}

#[test]
fn authenticated_receipt_with_deleted_raw_blob_becomes_cache_local_refill() {
    let fixture = InputFixture::new();
    let input = fixture.read();
    let engine = fixture.engine();
    let output = fixture.output(&input, &engine);
    let directory = Directory::new();
    let raw = RawArtifactCache::open(directory.0.join("blobs"), RawArtifactCacheLimits::default())
        .unwrap();
    let receipts = receipts::ReceiptCache::open(
        &directory.0.join("receipts"),
        AotReceiptCacheLimits::default(),
    )
    .unwrap();
    let key = RawArtifactKey::Blob(output.output_digest().clone());
    drop(
        raw.reserve_write(key, output.output().len() as u64)
            .unwrap()
            .publish(output.output())
            .unwrap(),
    );
    receipts
        .publish(&input.key().digest(), output.receipt())
        .unwrap();
    let receipt = receipts.lookup(&input.key().digest()).unwrap().unwrap();
    let proof = input.authenticate_receipt(receipt.as_bytes()).unwrap();
    drop(receipt);
    let data = directory
        .0
        .join("blobs/objects")
        .join(format!("b-{}", &output.output_digest().as_str()[7..]))
        .join("data");
    std::fs::remove_file(data).unwrap();
    let error = read_cached_blob(&raw, &proof).err().unwrap();
    assert_eq!(error.code, PlatformErrorCode::CorruptArtifact);
    assert_eq!(error.message, "native-cache-blob-missing");
    assert!(corrupt_cache(&error));
    assert!(input.check().is_ok());
    let snapshot = raw.snapshot().unwrap();
    assert_eq!(snapshot.corruptions, 1);
    assert_eq!(snapshot.pins, 0);
    assert_eq!(snapshot.retained_read_bytes, 0);
    assert_eq!(snapshot.reserved_read_bytes, 0);
}

#[test]
fn authoritative_not_found_and_cache_read_pressure_are_not_refill_errors() {
    let missing_source = super::super::error(PlatformErrorCode::NotFound, "catalog-source-missing");
    assert!(!corrupt_cache(&missing_source));
    let fixture = InputFixture::new();
    let input = fixture.read();
    let engine = fixture.engine();
    let output = fixture.output(&input, &engine);
    let proof = input.authenticate_receipt(output.receipt()).unwrap();
    let directory = Directory::new();
    let raw = RawArtifactCache::open(
        &directory.0,
        RawArtifactCacheLimits {
            maximum_read_bytes: 1,
            ..Default::default()
        },
    )
    .unwrap();
    drop(
        raw.reserve_write(
            RawArtifactKey::Blob(output.output_digest().clone()),
            output.output().len() as u64,
        )
        .unwrap()
        .publish(output.output())
        .unwrap(),
    );
    let error = read_cached_blob(&raw, &proof).err().unwrap();
    assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
    assert!(!corrupt_cache(&error));
    assert_eq!(raw.snapshot().unwrap().corruptions, 0);
    assert_eq!(raw.snapshot().unwrap().evictions, 0);
}
