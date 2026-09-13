use super::*;
use crate::{CompilerOptimization, InstanceAllocator, WasmtimeConfig};

#[test]
fn child_bootstrap_preserves_real_native_engine_identity_without_runtime_workers() {
    for allocator in [InstanceAllocator::OnDemand, InstanceAllocator::Pooling] {
        let config = WasmtimeConfig {
            instance_allocator: allocator,
            ..WasmtimeConfig::default()
        };
        let profile =
            ValidatedAotProfile::from_config(&config, AotCompilerLimits::default()).unwrap();
        let bytes = profile.bootstrap().unwrap();
        assert!(bytes.len() < profile::MAX_BOOTSTRAP_BYTES);
        let (engine, actual) =
            profile::engine_from_bootstrap(&bytes, AotCompilerLimits::default()).unwrap();
        assert_eq!(&actual, profile.engine_compatibility());
        profile.check_engine(&engine).unwrap();
        // The child settings omit allocator fields entirely. The pooling
        // configuration's memory layout still participates in code generation.
        assert!(!String::from_utf8(bytes).unwrap().contains("pooling"));
    }
}

#[test]
fn compiler_only_hash_matches_actual_runtime_pooling_and_codegen_settings() {
    for allocator in [InstanceAllocator::OnDemand, InstanceAllocator::Pooling] {
        for modified in [false, true] {
            let config = WasmtimeConfig {
                instance_allocator: allocator,
                compiler_optimization: if modified {
                    CompilerOptimization::SpeedAndSize
                } else {
                    CompilerOptimization::Speed
                },
                copy_on_write_images: !modified,
                maximum_wasm_stack_bytes: if modified { 128 * 1024 } else { 64 * 1024 },
                async_stack_bytes: 256 * 1024,
                maximum_memory_bytes: 1024 * 1024,
                pooling_maximum_instances: 1,
                pooling_maximum_core_instances_per_component: 1,
                pooling_maximum_memories_per_component: 1,
                pooling_maximum_tables_per_component: 1,
                maximum_table_elements: 16,
                ..WasmtimeConfig::default()
            };
            let profile =
                ValidatedAotProfile::from_config(&config, AotCompilerLimits::default()).unwrap();
            let mut actual = wasmtime::Config::new();
            config.apply_engine(&mut actual).unwrap();
            // Exercise the real runtime allocator setup with one tiny pool,
            // without a factory, worker, ticker, Store or guest compilation.
            let runtime = wasmtime::Engine::new(&actual).unwrap();
            profile.check_engine(&runtime).unwrap();
        }
    }
}

#[test]
fn engine_policy_and_host_security_change_identity_while_cpu_labels_grant_no_features() {
    let config = WasmtimeConfig::default();
    let baseline = ValidatedAotProfile::from_config(&config, AotCompilerLimits::default()).unwrap();
    let mut changed = config.clone();
    changed.cpu_feature_set = "pretend-new-native-features".into();
    let renamed = ValidatedAotProfile::from_config(&changed, AotCompilerLimits::default()).unwrap();
    assert_ne!(renamed.digest(), baseline.digest());
    assert_eq!(
        renamed.engine_compatibility(),
        baseline.engine_compatibility()
    );
    changed = config.clone();
    changed.context_policy.claim_keys.push("allowed".into());
    let security =
        ValidatedAotProfile::from_config(&changed, AotCompilerLimits::default()).unwrap();
    assert_ne!(security.digest(), baseline.digest());
    assert_eq!(
        security.engine_compatibility(),
        baseline.engine_compatibility()
    );
    changed = config;
    changed.compiler_optimization = CompilerOptimization::SpeedAndSize;
    let optimized =
        ValidatedAotProfile::from_config(&changed, AotCompilerLimits::default()).unwrap();
    assert_ne!(
        optimized.engine_compatibility(),
        baseline.engine_compatibility()
    );
    let (engine, _) = profile::engine_from_bootstrap(
        &optimized.bootstrap().unwrap(),
        AotCompilerLimits::default(),
    )
    .unwrap();
    assert!(baseline.check_engine(&engine).is_err());
}

#[test]
fn bootstrap_rejects_closed_shape_and_actual_engine_mismatch_before_compilation() {
    let limits = AotCompilerLimits::default();
    let profile = ValidatedAotProfile::from_config(&WasmtimeConfig::default(), limits).unwrap();
    let bytes = profile.bootstrap().unwrap();
    let original = String::from_utf8(bytes.clone()).unwrap();
    for text in [
        original.replacen(
            "\"formatVersion\":1",
            "\"formatVersion\":1,\"formatVersion\":1",
            1,
        ),
        original.replacen("\"formatVersion\":1", "\"formatVersion\":1.0", 1),
        original.replacen("\"formatVersion\":1", "\"formatVersion\":null", 1),
        original.replacen(
            "\"formatVersion\":1",
            "\"unknown\":true,\"formatVersion\":1",
            1,
        ),
    ] {
        assert!(profile::engine_from_bootstrap(text.as_bytes(), limits).is_err());
    }
    let mut value: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    value["settings"]["optimization"] = "speed-and-size".into();
    assert!(profile::engine_from_bootstrap(&serde_json::to_vec(&value).unwrap(), limits).is_err());
    value["settings"]["maximumWasmStackBytes"] = u64::MAX.into();
    assert!(profile::engine_from_bootstrap(&serde_json::to_vec(&value).unwrap(), limits).is_err());
    assert!(
        profile::engine_from_bootstrap(&vec![b' '; profile::MAX_BOOTSTRAP_BYTES + 1], limits)
            .is_err()
    );
}

#[test]
fn every_lowered_profile_bound_and_hard_limit_is_checked() {
    let config = WasmtimeConfig::default();
    for limits in [
        AotCompilerLimits {
            maximum_profile_bytes: 1,
            ..AotCompilerLimits::default()
        },
        AotCompilerLimits {
            maximum_profile_entries: 1,
            ..AotCompilerLimits::default()
        },
        AotCompilerLimits {
            maximum_identity_bytes: 1,
            ..AotCompilerLimits::default()
        },
    ] {
        assert!(ValidatedAotProfile::from_config(&config, limits).is_err());
    }
    for limits in [
        AotCompilerLimits {
            maximum_output_bytes: 0,
            ..AotCompilerLimits::default()
        },
        AotCompilerLimits {
            maximum_output_bytes: usize::MAX,
            ..AotCompilerLimits::default()
        },
        AotCompilerLimits {
            maximum_profile_entries: 513,
            ..AotCompilerLimits::default()
        },
        AotCompilerLimits {
            maximum_profile_bytes: 512 * 1024 + 1,
            ..AotCompilerLimits::default()
        },
        AotCompilerLimits {
            maximum_identity_bytes: 4097,
            ..AotCompilerLimits::default()
        },
    ] {
        assert!(limits.validate().is_err());
    }
}
