use latent_artifacts::{DirectoryArtifactRepositoryConfig, RawArtifactCacheLimits};
use latent_core::PlatformError;
use latent_manifest::ManifestLimits;
use latent_wasmtime::{
    AotProcessLimits, AotReceiptCacheLimits, AotResourceLimits, NativeImageLimits,
};
use std::time::Duration;

use super::{invalid, IsolatedAotConfig, NodeConfig};
const MIB: usize = 1024 * 1024;
pub(super) type Limits = (
    AotProcessLimits,
    RawArtifactCacheLimits,
    AotReceiptCacheLimits,
    NativeImageLimits,
);

pub(super) fn derive(
    config: &IsolatedAotConfig,
    node: &NodeConfig,
    artifacts: DirectoryArtifactRepositoryConfig,
) -> Result<Limits, PlatformError> {
    let failure = || invalid("isolatedAot.limits");
    let jobs = node.cache.preparations.min(8);
    let output = config.process.maximum_output_bytes;
    if !(1..=256 * MIB).contains(&output)
        || !(1..=300_000).contains(&config.process.job_timeout_millis)
        || !(1..=16_384).contains(&config.cache.entries)
        || config.cache.disk_bytes < output as u64
    {
        return Err(failure());
    }
    let defaults = AotProcessLimits::default();
    let mut process = AotProcessLimits {
        maximum_component_bytes: artifacts.max_component_bytes,
        compiler: latent_wasmtime::AotCompilerLimits {
            maximum_output_bytes: output,
            ..defaults.compiler
        },
        job_timeout: Duration::from_millis(config.process.job_timeout_millis),
        sandbox: latent_wasmtime::AotSandboxLimits {
            address_space_bytes: config.process.address_space_bytes,
            cpu_seconds: config.process.job_timeout_millis.div_ceil(1000),
            ..defaults.sandbox
        },
        ..defaults
    };
    let documents = artifacts
        .max_metadata_bytes
        .min(process.maximum_document_bytes)
        .checked_add(
            ManifestLimits::default()
                .max_document_bytes
                .min(process.maximum_document_bytes),
        )
        .and_then(|value| value.checked_add(process.maximum_metadata_bytes))
        .and_then(|value| value.checked_add(MIB))
        .and_then(|value| value.checked_mul(jobs))
        .ok_or_else(failure)?;
    process.resources = AotResourceLimits {
        maximum_jobs: jobs,
        maximum_input_bytes: jobs
            .checked_mul(artifacts.max_component_bytes)
            .ok_or_else(failure)?,
        maximum_document_bytes: documents,
        maximum_native_bytes: jobs.checked_mul(output).ok_or_else(failure)?,
        maximum_outputs: jobs,
    };
    process.validate().map_err(|_| failure())?;
    let recovery = config.cache.entries.checked_mul(2).ok_or_else(failure)?;
    let raw = RawArtifactCacheLimits {
        maximum_entries: config.cache.entries,
        maximum_disk_bytes: config.cache.disk_bytes,
        maximum_object_bytes: output as u64,
        maximum_staging_bytes: (128 * MIB).max(output) as u64,
        maximum_read_bytes: (128 * MIB).max(output) as u64,
        maximum_recovery_entries: recovery,
        ..RawArtifactCacheLimits::default()
    };
    raw.validate().map_err(|_| failure())?;
    let receipts = AotReceiptCacheLimits {
        maximum_entries: config.cache.entries,
        // Receipt inventory includes its marker, root lock and one stage.
        maximum_recovery_entries: recovery
            .max(config.cache.entries.checked_add(3).ok_or_else(failure)?),
        ..AotReceiptCacheLimits::default()
    };
    receipts.validate().map_err(|_| failure())?;
    let images = NativeImageLimits {
        maximum_images: config.images.maximum_images,
        maximum_image_bytes: config.images.maximum_image_bytes,
        maximum_total_bytes: config.images.maximum_total_bytes,
    };
    images.validate().map_err(|_| failure())?;
    if rounded(output, page_size())? > images.maximum_image_bytes {
        return Err(failure());
    }
    Ok((process, raw, receipts, images))
}

fn rounded(bytes: usize, page: usize) -> Result<usize, PlatformError> {
    if page == 0 {
        return Err(invalid("isolatedAot.pageSize"));
    }
    bytes
        .checked_add(page - 1)
        .and_then(|value| (value / page).checked_mul(page))
        .ok_or_else(|| invalid("isolatedAot.limits"))
}

fn page_size() -> usize {
    #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
    {
        rustix::param::page_size()
    }
    #[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
    {
        4096
    } // Only platform-independent limit tests reach this fallback.
}
