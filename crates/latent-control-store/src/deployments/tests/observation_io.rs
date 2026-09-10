use std::io::{Error, Write};

use super::*;
use crate::deployments::observation::{CatalogWorkObserver, CatalogWorkOperation, Source};

struct PartialFailure {
    written: usize,
}
impl Write for PartialFailure {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        if self.written != 0 {
            return Err(Error::other("injected partial write"));
        }
        let count = bytes.len().min(3);
        self.written += count;
        Ok(count)
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

#[test]
fn actual_partial_write_failure_keeps_unknown_staged_bytes() {
    let observer = CatalogWorkObserver::new();
    let mut work = Source::observed(observer.clone()).begin(CatalogWorkOperation::ApplyMany);
    let mut writer = PartialFailure { written: 0 };
    let result = write_stage(&mut writer, b"more-than-three", &mut work);
    assert_eq!(writer.written, 3);
    assert_eq!(result.as_ref().unwrap_err().message, "catalog-io-failure");
    work.finish(&result);
    drop(work);
    let counts = observer.snapshot().last.unwrap().counts;
    assert_eq!(counts.stage_written_bytes, None);
    assert_eq!(counts.stage_write_failures, 1);
    assert_eq!(counts.stage_synced_bytes, 0);
}

#[test]
fn serializer_failure_counts_the_actual_partial_buffer_and_stops_at_limit() {
    let observer = CatalogWorkObserver::new();
    let mut work = Source::observed(observer.clone()).begin(CatalogWorkOperation::Open);
    let releases = crate::deployments::tests::fixtures::Releases::default();
    let catalog = crate::deployments::tests::fixtures::run(crate::deployments::compiler::compile(
        std::collections::BTreeMap::new(),
        latent_core::RouteGeneration(0),
        0,
        &releases,
        DirectoryDeploymentRepositoryConfig::default(),
    ))
    .unwrap();
    let result = encode_bytes(&catalog, 40, &mut work);
    assert_eq!(
        result.as_ref().unwrap_err().message,
        "catalog-state-byte-limit"
    );
    work.finish(&result);
    drop(work);
    let counts = observer.snapshot().last.unwrap().counts;
    assert_eq!(counts.envelope_serializations, 1);
    assert!(counts.encoded_buffer_bytes > 0);
    assert!(counts.encoded_buffer_bytes <= 40);
    assert!((1..=40).contains(&counts.encoded_capacity_max));
    assert_eq!(counts.payload_serializations, 0);
    assert_eq!(counts.payload_buffer_bytes, 0);
    assert_eq!(counts.stage_calls, 0);
}
