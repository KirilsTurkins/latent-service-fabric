use super::*;
use crate::aot::{image_budget::mapping_bytes, AotCompilerLimits};
use latent_core::PlatformErrorCode;
use zeroize::Zeroizing;

fn settings(output: usize) -> NativeAotSettings {
    let process = AotProcessLimits {
        compiler: AotCompilerLimits {
            maximum_output_bytes: output,
            ..AotCompilerLimits::default()
        },
        ..AotProcessLimits::default()
    };
    NativeAotSettings {
        executable: PathBuf::from("/unused-approved-compiler"),
        approved_digest: [7; 32],
        authority: TrustedAotCompilerAuthority::new(
            "configuration-test",
            Zeroizing::new([3; 32]),
            process.compiler,
        )
        .unwrap(),
        process,
        cache: NativeAotCacheConfig::default(),
        images: NativeImageLimits::default(),
    }
}

#[test]
fn settings_reject_unfunded_mapping_tail_before_any_resource_is_opened() {
    let page = rustix::param::page_size();
    for output in [1, page + 1] {
        let mut config = settings(output);
        config.images.maximum_image_bytes = output;
        assert_eq!(
            config.validate().unwrap_err().code,
            PlatformErrorCode::InvalidArgument
        );
        config.images.maximum_image_bytes = mapping_bytes(output).unwrap();
        assert!(config.validate().is_ok());
    }
    let mut exact = settings(page);
    exact.images.maximum_image_bytes = page;
    exact.images.maximum_total_bytes = page;
    assert!(exact.validate().is_ok());
}

#[test]
fn raw_payload_capacity_does_not_falsely_charge_separate_entry_headers() {
    let mut config = settings(8);
    config.cache.raw.maximum_disk_bytes = 7;
    assert_eq!(
        config.validate().unwrap_err().code,
        PlatformErrorCode::InvalidArgument
    );
    config.cache.raw.maximum_disk_bytes = 8;
    assert!(config.validate().is_ok());
    config.cache.raw.maximum_staging_bytes = 7;
    assert!(config.validate().is_err());
    config.cache.raw.maximum_staging_bytes = 8;
    config.cache.raw.maximum_read_bytes = 7;
    assert!(config.validate().is_err());
    config.cache.raw.maximum_read_bytes = 8;
    assert!(config.validate().is_ok());
}
