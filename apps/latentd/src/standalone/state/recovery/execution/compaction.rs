//! Run physical compaction under the original protected offline writer.
use super::{awaited, protected, storage, Codecs};
use latent_core::{native_capacity::NativeBufferClass, PlatformError};
use latent_state::{
    embedded::{CompactionLimits, FencedStoreError, StoreError},
    protected_store::ProtectedStoreOwner,
    recovery::maintenance::namespace_expectations,
    store_io::StoreIoKind,
};
use std::{
    sync::Arc,
    time::{Duration, Instant},
};

const WORK_BYTES: u64 = 8 * 1024 * 1024;
const MAXIMUM_IO_BYTES: u64 = 64 * 1024 * 1024;
const MAXIMUM_GROWTH_BYTES: u64 = 256 * 1024;

pub(super) async fn compact(
    store: &ProtectedStoreOwner,
    codecs: &Arc<Codecs>,
    expected_view: Vec<u8>,
) -> Result<serde_json::Value, PlatformError> {
    let permit = codecs
        .original
        .reserve_buffer(NativeBufferClass::Work, WORK_BYTES)
        .map_err(|_| super::super::capacity())?;
    let worker = Arc::clone(codecs);
    let job = store
        .with_store_retaining(
            StoreIoKind::RecoveryWrite,
            WORK_BYTES,
            Arc::clone(codecs) as Arc<dyn std::any::Any + Send + Sync>,
            move |engine| {
                let _permit = permit;
                let view = engine.snapshot()?;
                worker.closure(&view)?;
                let observed = worker.selected_view(&view)?;
                if observed.view_token()? != expected_view {
                    return Err(StoreError::Conflict);
                }
                let checks = namespace_expectations(
                    &view,
                    &observed.namespace.tenant,
                    &observed.namespace.id,
                    observed.namespace.version.incarnation,
                )?;
                drop(view);
                let limits = CompactionLimits {
                    deadline: worker
                        .authority
                        .deadline
                        .min(Instant::now() + Duration::from_secs(5)),
                    maximum_read_bytes: MAXIMUM_IO_BYTES,
                    maximum_write_bytes: MAXIMUM_IO_BYTES,
                    maximum_io_operations: 8192,
                    maximum_scratch_bytes: WORK_BYTES,
                    maximum_growth_bytes: MAXIMUM_GROWTH_BYTES,
                };
                let report = match engine.compact_fenced(limits, &checks, || {
                    worker.fence("state-checkpoint", || {
                        worker
                            .original
                            .with_live(|| ())
                            .map_err(|_| StoreError::SnapshotExpired)
                    })
                }) {
                    Ok(report) => report,
                    Err(FencedStoreError::Store(error)) => return Err(error),
                    Err(FencedStoreError::Fence(error)) => return Ok(Err(error)),
                };
                worker.check().map_err(|_| StoreError::CommitUncertain)?;
                Ok(Ok(serde_json::json!({
                    "action": "compact-namespace",
                    "view": expected_view,
                    "changed": report.changed,
                    "fileBytesBefore": report.file_bytes_before.to_string(),
                    "fileBytesAfter": report.observed_file_bytes.to_string(),
                    "peakFileBytes": report.peak_file_bytes.to_string(),
                    "readBytes": report.read_bytes.to_string(),
                    "writeBytes": report.write_bytes.to_string(),
                    "ioOperations": report.io_operations.to_string(),
                    "elapsedMicros": report.elapsed_micros.to_string(),
                    "scratchRequirementBytes": report.scratch_requirement_bytes.to_string(),
                    "scratchLimitBytes": report.scratch_limit_bytes.to_string(),
                })))
            },
        )
        .map_err(protected)?;
    awaited(job, codecs)
        .await?
        .map_err(protected)?
        .map_err(storage)
}
