//! A startup probe authenticates readiness only; this fixture is not a sandbox.
use latent_core::PlatformErrorCode;
use latent_wasmtime::{NativeAotCacheConfig, NativeAotSettings, NativeImageLimits, WasmtimeConfig};
use std::{path::PathBuf, time::Duration};

pub(super) fn run() {
    use super::support::diagnostics::case;
    for (maximum, name, expected) in [
        (19, "readiness-success", None),
        (
            17,
            "readiness-malformed",
            Some(PlatformErrorCode::PermissionDenied),
        ),
        (
            21,
            "probe-launch-mismatch",
            Some(PlatformErrorCode::PermissionDenied),
        ),
        (
            23,
            "probe-stalled-launch",
            Some(PlatformErrorCode::DeadlineExceeded),
        ),
    ] {
        case(name, || {
            let directory = super::support::Directory::new();
            assert_no_children();
            let mut settings = settings(directory.path());
            settings.process.compiler.maximum_output_bytes = maximum;
            if maximum == 23 {
                settings.process.job_timeout = Duration::from_secs(1);
            }
            let _stage = super::support::diagnostics::Span::new("readiness-probe");
            let result = settings.verify_compiler_readiness(&WasmtimeConfig::default());
            assert_eq!(result.err().map(|error| error.code), expected, "{maximum}");
            assert_no_children();
            assert!(!settings.cache.blob_root.exists());
            assert!(!settings.cache.receipt_root.exists());
        });
    }
    case("readiness-wrong-digest", || {
        let directory = super::support::Directory::new();
        let mut settings = settings(directory.path());
        settings.approved_digest[0] ^= 1;
        assert_eq!(
            settings
                .verify_compiler_readiness(&WasmtimeConfig::default())
                .unwrap_err()
                .code,
            PlatformErrorCode::PermissionDenied
        );
        assert_no_children();
    });
    case("readiness-relative-path", || {
        let directory = super::support::Directory::new();
        let mut settings = settings(directory.path());
        settings.executable = PathBuf::from("relative-compiler");
        assert_eq!(
            settings
                .verify_compiler_readiness(&WasmtimeConfig::default())
                .unwrap_err()
                .code,
            PlatformErrorCode::InvalidArgument
        );
        assert_no_children();
    });
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
