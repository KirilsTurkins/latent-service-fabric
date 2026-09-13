//! A startup probe authenticates readiness only; this fixture is not a sandbox.
use latent_core::PlatformErrorCode;
use latent_wasmtime::{NativeAotCacheConfig, NativeAotSettings, NativeImageLimits, WasmtimeConfig};
use std::{path::PathBuf, time::Duration};

pub(super) fn run() {
    let directory = super::support::Directory::new();
    assert_no_children();
    for (maximum, expected) in [
        (19, None),
        (17, Some(PlatformErrorCode::PermissionDenied)),
        (21, Some(PlatformErrorCode::PermissionDenied)),
        (23, Some(PlatformErrorCode::DeadlineExceeded)),
    ] {
        let mut settings = settings(directory.path());
        settings.process.compiler.maximum_output_bytes = maximum;
        if maximum == 23 {
            settings.process.job_timeout = Duration::from_secs(1);
        }
        let result = settings.verify_compiler_readiness(&WasmtimeConfig::default());
        assert_eq!(result.err().map(|error| error.code), expected, "{maximum}");
        assert_no_children();
        assert!(!settings.cache.blob_root.exists());
        assert!(!settings.cache.receipt_root.exists());
    }
    let mut settings = settings(directory.path());
    settings.approved_digest[0] ^= 1;
    assert_eq!(
        settings
            .verify_compiler_readiness(&WasmtimeConfig::default())
            .unwrap_err()
            .code,
        PlatformErrorCode::PermissionDenied
    );
    settings.executable = PathBuf::from("relative-compiler");
    assert_eq!(
        settings
            .verify_compiler_readiness(&WasmtimeConfig::default())
            .unwrap_err()
            .code,
        PlatformErrorCode::InvalidArgument
    );
    assert_no_children();
    eprintln!("isolated AOT readiness: six bounded success/rejection/reap scenarios passed");
}

fn settings(root: &std::path::Path) -> NativeAotSettings {
    let limits = super::support::limits();
    let (executable, digest) = super::driver::executable();
    NativeAotSettings {
        executable: executable.clone(),
        approved_digest: *digest,
        authority: super::support::authority(limits),
        process: limits,
        cache: NativeAotCacheConfig {
            blob_root: root.join("absent-blobs"),
            receipt_root: root.join("absent-receipts"),
            ..NativeAotCacheConfig::default()
        },
        images: NativeImageLimits::default(),
        audit: None,
    }
}

fn assert_no_children() {
    assert!(
        std::fs::read_to_string("/proc/thread-self/children")
            .unwrap()
            .trim()
            .is_empty(),
        "the calling thread retains no running or zombie child after a probe"
    );
}
