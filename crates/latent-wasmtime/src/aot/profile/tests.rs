use super::*;

#[test]
fn runtime_engine_profile_matches_compiler_and_child_across_supported_settings() {
    use crate::{CompilerOptimization, InstanceAllocator};

    let limits = AotCompilerLimits::default();
    for allocator in [InstanceAllocator::OnDemand, InstanceAllocator::Pooling] {
        for java in [false, true] {
            for modified in [false, true] {
                let mut config = WasmtimeConfig {
                    instance_allocator: allocator,
                    java_guest: java,
                    fuel_async_yield_interval: java.then_some(10_000),
                    transactional_state: modified,
                    compiler_optimization: if modified {
                        CompilerOptimization::SpeedAndSize
                    } else {
                        CompilerOptimization::Speed
                    },
                    copy_on_write_images: !modified,
                    maximum_wasm_stack_bytes: if modified { 128 * 1024 } else { 64 * 1024 },
                    async_stack_bytes: 256 * 1024,
                    maximum_memory_bytes: if java { 8 * 1024 * 1024 } else { 1024 * 1024 },
                    pooling_maximum_instances: 1,
                    pooling_maximum_core_instances_per_component: 1,
                    pooling_maximum_memories_per_component: 1,
                    pooling_maximum_tables_per_component: 1,
                    maximum_table_elements: 16,
                    ..WasmtimeConfig::default()
                };
                if modified {
                    config.context_policy.claim_keys.push("allowed".into());
                }
                if java && allocator == InstanceAllocator::Pooling {
                    assert!(config.validate().is_err());
                    assert!(ValidatedAotProfile::from_config(&config, limits).is_err());
                    assert!(ValidatedAotProfile::with_runtime_engine(&config, limits).is_err());
                    continue;
                }
                let compiler = ValidatedAotProfile::from_config(&config, limits).unwrap();
                let (runtime, paired) =
                    ValidatedAotProfile::with_runtime_engine(&config, limits).unwrap();
                assert_eq!(paired, compiler);
                assert_eq!(paired.bootstrap().unwrap(), compiler.bootstrap().unwrap());
                compiler.check_engine(&runtime).unwrap();
                let (child, actual) =
                    engine_from_bootstrap(&paired.bootstrap().unwrap(), limits).unwrap();
                assert_eq!(&actual, paired.engine_compatibility());
                paired.check_engine(&child).unwrap();
            }
        }
    }
}

#[test]
fn runtime_engine_profile_retains_compiler_only_limits_before_allocation() {
    use crate::InstanceAllocator;

    let limits = AotCompilerLimits::default();
    for config in [
        WasmtimeConfig {
            maximum_wasm_stack_bytes: 64 * 1024 * 1024 + 1,
            async_stack_bytes: 128 * 1024 * 1024,
            ..WasmtimeConfig::default()
        },
        WasmtimeConfig {
            async_stack_bytes: 128 * 1024 * 1024 + 1,
            ..WasmtimeConfig::default()
        },
        WasmtimeConfig {
            instance_allocator: InstanceAllocator::Pooling,
            maximum_memory_bytes: 65 * 1024 * 1024 * 1024,
            pooling_maximum_instances: 1,
            pooling_maximum_core_instances_per_component: 1,
            pooling_maximum_memories_per_component: 1,
            pooling_maximum_tables_per_component: 1,
            ..WasmtimeConfig::default()
        },
    ] {
        config.validate().unwrap();
        let compiler = ValidatedAotProfile::from_config(&config, limits).unwrap_err();
        let paired = ValidatedAotProfile::with_runtime_engine(&config, limits).unwrap_err();
        assert_eq!(paired.code, latent_core::PlatformErrorCode::InvalidArgument);
        assert_eq!(paired.code, compiler.code);
        assert_eq!(paired.message, compiler.message);
    }
}

#[test]
fn typed_function_references_are_explicit_in_native_policy_identity() {
    let limits = AotCompilerLimits::default();
    let config = WasmtimeConfig::default();
    let runtime = config.detected_runtime_profile().unwrap();
    let current = config.profile_with_runtime(DispatchMode::Generic, Some(&runtime));
    let checked = ValidatedAotProfile::from_config(&config, limits).unwrap();
    let policy = declared_digest(&current, limits).unwrap();
    assert_eq!(&policy, checked.security_policy_digest());
    assert_eq!(current.configuration["wasm-function-references"], "true");
    let mut stale = current.clone();
    stale.configuration.remove("wasm-function-references");
    assert_ne!(declared_digest(&stale, limits).unwrap(), policy);
    stale
        .configuration
        .insert("wasm-function-references".into(), "false".into());
    assert_ne!(declared_digest(&stale, limits).unwrap(), policy);

    let java = WasmtimeConfig {
        java_guest: true,
        fuel_async_yield_interval: Some(10_000),
        ..config
    };
    let java_checked = ValidatedAotProfile::from_config(&java, limits).unwrap();
    assert_eq!(
        java.profile(DispatchMode::Generic).configuration["wasm-function-references"],
        "false"
    );
    assert_ne!(java_checked.security_policy_digest(), &policy);
    assert_ne!(
        java_checked.engine_compatibility(),
        checked.engine_compatibility()
    );
}

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
        latent_core::PHASE3_HOST_ABI_CURRENT.id
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
