use super::*;

#[test]
fn previous_patch_version_and_layout_cannot_alias_the_current_aot_policy() {
    let limits = AotCompilerLimits::default();
    let config = WasmtimeConfig::default();
    let runtime = config.detected_runtime_profile().unwrap();
    let current = config.profile_with_runtime(DispatchMode::Generic, Some(&runtime));
    let checked = ValidatedAotProfile::from_config(&config, limits).unwrap();
    let policy = declared_digest(&current, limits).unwrap();
    assert_eq!(&policy, checked.security_policy_digest());

    // Keep every other field fixed. Even if an upstream patch were to preserve
    // native code compatibility, its declared version must invalidate our key.
    let mut previous = current.clone();
    previous.wasmtime_version = "47.0.3".into();
    assert_ne!(previous.wasmtime_version, current.wasmtime_version);
    assert_ne!(declared_digest(&previous, limits).unwrap(), policy);

    // Layout policy has an independent identity, so changing only its version
    // cannot bypass the exact configuration boundary either.
    previous = current;
    previous.configuration.insert(
        "engine-layout-policy".into(),
        "wasmtime-47.0.3-bounded-v1".into(),
    );
    assert_ne!(declared_digest(&previous, limits).unwrap(), policy);
}
