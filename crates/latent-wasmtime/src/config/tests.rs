use super::*;

#[test]
fn legacy_alias_preserves_the_existing_default_policy() {
    let config = Phase0WasmtimeConfig::default();
    config.validate().unwrap();
    assert_eq!(config.maximum_component_bytes, 16 * 1024 * 1024);
    assert_eq!(config.maximum_memory_bytes, 64 * 1024 * 1024);
    assert_eq!(config.maximum_fuel, 100_000_000);
    assert_eq!(config.maximum_wasm_stack_bytes, 512 * 1024);
    assert_eq!(config.async_stack_bytes, 2 * 1024 * 1024);
    assert_eq!(config.prepared_cache_maximum_entries, 8);
    assert_eq!(config.prepared_cache_maximum_source_bytes, 64 * 1024 * 1024);
    assert!(config.prepared_cache_enabled && config.copy_on_write_images);
    assert_eq!(config.invocation_log_maximum_entries, 8);
    assert_eq!(config.invocation_log_maximum_bytes, 16 * 1024);
    assert_eq!(config.retained_log_maximum_entries, 256);
    assert_eq!(config.retained_log_maximum_bytes, 512 * 1024);
    assert_eq!(config.epoch_deadline_ticks, 1);
    assert_eq!(config.epoch_tick_interval_millis, 5);
    assert_eq!(config.instance_allocator, Phase0InstanceAllocator::OnDemand);
    assert_eq!(config.pooling_maximum_instances, 1);
}

#[test]
fn generic_and_legacy_payload_adapters_have_distinct_compatibility() {
    let config = WasmtimeConfig::default();
    let generic = config.profile(DispatchMode::Generic);
    let legacy = config.profile(DispatchMode::Phase0);
    assert_eq!(generic.id, GENERIC_BACKEND_ID);
    assert_eq!(legacy.id, PHASE0_BACKEND_ID);
    assert_ne!(
        generic.configuration["configuration-digest"],
        legacy.configuration["configuration-digest"]
    );
    assert_eq!(
        generic.configuration["configuration-digest"],
        config.configuration_digest(DispatchMode::Generic)
    );
    assert_eq!(
        legacy.configuration["hostcall-fuel"],
        "per-call-echo-world-max-transfer"
    );
    assert_eq!(generic.configuration["ambient-wasi-authority"], "none");
    assert!(generic.async_support && generic.fuel_enabled && generic.epoch_interruption_enabled);
}

#[test]
fn changes_to_execution_and_preparation_bounds_change_compatibility() {
    let config = WasmtimeConfig::default();
    let before = config.configuration_digest(DispatchMode::Generic);
    let changes: &[fn(&mut WasmtimeConfig)] = &[
        |c| c.maximum_memory_bytes /= 2,
        |c| c.maximum_fuel /= 2,
        |c| c.maximum_wasm_stack_bytes /= 2,
        |c| c.maximum_instances_per_store /= 2,
        |c| c.maximum_memories_per_store /= 2,
        |c| c.maximum_tables_per_store /= 2,
        |c| c.maximum_table_elements /= 2,
        |c| c.maximum_active_instances /= 2,
        |c| c.maximum_concurrent_preparations += 1,
        |c| c.maximum_artifact_metadata_bytes /= 2,
        |c| c.prepared_cache_maximum_metadata_bytes /= 2,
        |c| c.prepared_cache_maximum_compiled_image_bytes /= 2,
        |c| c.hostcall_fuel *= 2,
        |c| c.epoch_deadline_ticks += 1,
        |c| c.copy_on_write_images = false,
        |c| c.instance_allocator = InstanceAllocator::Pooling,
        |c| c.pooling_maximum_core_instances_per_component += 1,
        |c| c.value_codec_limits.max_output_bytes /= 2,
        |c| c.value_codec_limits.max_decoded_value_bytes /= 2,
        |c| c.value_codec_limits.max_type_nodes /= 2,
        |c| {
            c.context_policy
                .metadata_prefixes
                .push("public.".to_owned());
        },
        |c| c.context_policy.claim_keys.push("role".to_owned()),
        |c| c.context_policy.baggage_keys.push("region".to_owned()),
    ];
    for (index, change) in changes.iter().enumerate() {
        let mut policy = config.clone();
        change(&mut policy);
        policy.validate().unwrap();
        assert_ne!(
            before,
            policy.configuration_digest(DispatchMode::Generic),
            "policy change {index} was omitted"
        );
    }
}

#[test]
fn invalid_and_overflowing_policy_is_rejected_before_engine_construction() {
    let invalid: &[fn(&mut WasmtimeConfig)] = &[
        |c| c.maximum_component_bytes = 0,
        |c| c.maximum_memory_bytes = 0,
        |c| c.maximum_fuel = 0,
        |c| c.maximum_active_instances = 0,
        |c| c.maximum_concurrent_preparations = 0,
        |c| c.maximum_artifact_metadata_bytes = 0,
        |c| c.prepared_cache_maximum_metadata_bytes = 0,
        |c| c.prepared_cache_maximum_compiled_image_bytes = 0,
        |c| c.async_stack_bytes = c.maximum_wasm_stack_bytes - 1,
        |c| c.epoch_tick_interval_millis = 0,
        |c| c.epoch_tick_interval_millis = 1_001,
        |c| c.epoch_deadline_ticks = u64::MAX,
        |c| c.cpu_feature_set = String::new(),
        |c| c.cpu_feature_set = "x".repeat(257),
        |c| c.target_triple = "unsupported-target".to_owned(),
        |c| c.context_policy.metadata_prefixes.push(String::new()),
        |c| {
            c.instance_allocator = InstanceAllocator::Pooling;
            c.pooling_maximum_instances = u32::MAX;
        },
        |c| {
            c.prepared_cache_maximum_source_bytes = usize::MAX;
            c.maximum_concurrent_preparations = 2;
        },
    ];
    for change in invalid {
        let mut config = WasmtimeConfig::default();
        change(&mut config);
        assert_eq!(
            config.validate().unwrap_err().code,
            PlatformErrorCode::InvalidArgument
        );
    }
    let at_boundary = WasmtimeConfig {
        epoch_tick_interval_millis: 100,
        epoch_deadline_ticks: 10,
        ..WasmtimeConfig::default()
    };
    at_boundary.validate().unwrap();
}

#[test]
fn context_policy_compatibility_is_order_independent_and_namespace_framed() {
    let mut config = WasmtimeConfig::default();
    config.context_policy.metadata_prefixes = vec!["guest.".to_owned(), "public.".to_owned()];
    config.context_policy.claim_keys = vec!["role".to_owned(), "scope".to_owned()];
    config.context_policy.baggage_keys = vec!["region".to_owned(), "zone".to_owned()];
    config.validate().unwrap();
    let before = config.configuration_digest(DispatchMode::Generic);
    config.context_policy.metadata_prefixes.reverse();
    config.context_policy.claim_keys.reverse();
    config.context_policy.baggage_keys.reverse();
    assert_eq!(before, config.configuration_digest(DispatchMode::Generic));

    // Moving the same exposed name to a different namespace changes behavior.
    std::mem::swap(
        &mut config.context_policy.claim_keys,
        &mut config.context_policy.baggage_keys,
    );
    assert_ne!(before, config.configuration_digest(DispatchMode::Generic));
    let profile = config.profile(DispatchMode::Generic);
    assert_eq!(
        profile.configuration["context-exposure-policy"],
        "explicit-allowlists-v1"
    );
    assert_eq!(profile.configuration["context-metadata-prefix-count"], "2");
}

#[test]
fn applying_policy_enables_required_containment_and_caps_pool_concurrency() {
    let config = WasmtimeConfig::default();
    let mut engine = wasmtime::Config::new();
    engine.consume_fuel(false).epoch_interruption(false);
    config.apply_engine(&mut engine).unwrap();
    let engine = wasmtime::Engine::new(&engine).unwrap();
    assert!(engine.get_consume_fuel() && engine.get_epoch_interruption());
    assert_eq!(engine.get_max_wasm_stack(), config.maximum_wasm_stack_bytes);
    assert_eq!(engine.get_async_stack_size(), config.async_stack_bytes);
    assert_eq!(engine.get_memory_init_cow(), config.copy_on_write_images);
    assert_eq!(
        config.active_instance_limit(),
        config.maximum_active_instances
    );

    let pooling = WasmtimeConfig {
        instance_allocator: InstanceAllocator::Pooling,
        pooling_maximum_instances: 2,
        maximum_active_instances: 8,
        ..config
    };
    assert_eq!(pooling.active_instance_limit(), 2);
    pooling.apply_engine(&mut wasmtime::Config::new()).unwrap();
}
