use super::ExecutionIsolationProfile;
use crate::{
    Phase0WasmtimeEngineFactory, WasmtimeComponentEngineFactory, WasmtimeConfig,
    WasmtimeHostServices,
};
use latent_core::PlatformErrorCode;

#[test]
fn requested_external_profile_cannot_construct_an_unmanaged_or_phase_zero_backend() {
    let config = WasmtimeConfig {
        execution_isolation_profile: ExecutionIsolationProfile::ExternalCapsule,
        ..WasmtimeConfig::default()
    };
    let failures = [
        WasmtimeComponentEngineFactory::new(config.clone())
            .err()
            .unwrap(),
        WasmtimeComponentEngineFactory::with_host_services(
            config.clone(),
            WasmtimeHostServices::default(),
        )
        .err()
        .unwrap(),
        Phase0WasmtimeEngineFactory::new(config).err().unwrap(),
    ];
    for error in failures {
        assert_eq!(error.code, PlatformErrorCode::IncompatibleContract);
        assert!(!error.retryable);
        assert!(error.message.starts_with("external-capsule-"));
    }
}

#[test]
fn only_exact_node_profiles_decode_and_round_trip() {
    for profile in [
        ExecutionIsolationProfile::LocalExperimental,
        ExecutionIsolationProfile::ExternalCapsule,
    ] {
        let encoded = serde_json::to_string(&profile).unwrap();
        assert_eq!(encoded, format!("\"{}\"", profile.name()));
        assert_eq!(
            serde_json::from_str::<ExecutionIsolationProfile>(&encoded).unwrap(),
            profile
        );
    }
    for invalid in [
        "null",
        "{}",
        "[]",
        "\"\"",
        "\"secure\"",
        "\"external-capsule-v2\"",
        "\"fixed-execution-host-v1\"",
        "\"provider-inprocess-v1\"",
        "\"renderer-component-v1\"",
    ] {
        assert!(
            serde_json::from_str::<ExecutionIsolationProfile>(invalid).is_err(),
            "{invalid}"
        );
    }
}

#[test]
fn a_required_execution_profile_changes_the_prepared_and_native_policy_identity() {
    let local = WasmtimeConfig::default();
    let mut external = local.clone();
    external.execution_isolation_profile = ExecutionIsolationProfile::ExternalCapsule;
    let local = local.profile(crate::config::DispatchMode::Generic);
    let external = external.profile(crate::config::DispatchMode::Generic);
    assert_eq!(
        external.configuration["execution-isolation-profile"],
        "external-capsule-v1"
    );
    assert_ne!(
        local.configuration["configuration-digest"],
        external.configuration["configuration-digest"]
    );
    assert_eq!(
        local.configuration["host-abi-digest"],
        external.configuration["host-abi-digest"]
    );
}
