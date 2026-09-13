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

#[test]
fn host_abi_identity_is_bound_to_prepared_and_native_compatibility() {
    let limits = AotCompilerLimits::default();
    let config = WasmtimeConfig::default();
    let current = config.profile(DispatchMode::Generic);
    let checked = ValidatedAotProfile::from_config(&config, limits).unwrap();
    assert_eq!(
        checked.capability_contract_digest(),
        &crate::bindings::host_abi_digest()
    );
    assert_eq!(
        current.configuration["host-abi-profile"],
        latent_core::PHASE3_HOST_ABI_V2.id
    );
    let policy = declared_digest(&current, limits).unwrap();
    for field in ["host-abi-profile", "host-abi-digest"] {
        let mut stale = current.clone();
        stale.configuration.remove(field);
        assert_ne!(declared_digest(&stale, limits).unwrap(), policy);
        stale
            .configuration
            .insert(field.into(), "legacy-or-forged".into());
        assert_ne!(declared_digest(&stale, limits).unwrap(), policy);
    }
    let mut old = Sha256::new();
    latent_core::PHASE3_HOST_ABI_V1.visit_identity_bytes(|part| old.update(part));
    assert_ne!(
        &<[u8; 32]>::from(old.finalize()),
        checked.capability_contract_digest()
    );
}
