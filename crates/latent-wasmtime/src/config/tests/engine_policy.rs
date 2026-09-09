use std::collections::BTreeSet;

use super::*;
use wasmtime::{Config, Engine, OptLevel};

#[test]
fn explicit_default_matches_the_pinned_engine_layout_and_optimization() {
    let old = Engine::new(&Config::new()).unwrap();
    let mut configured = Config::new();
    WasmtimeConfig::default()
        .apply_engine(&mut configured)
        .unwrap();
    let current = Engine::new(&configured).unwrap();
    assert_eq!(
        current.get_cranelift_opt_level(),
        old.get_cranelift_opt_level()
    );
    assert_eq!(current.get_cranelift_opt_level(), Some(OptLevel::Speed));
    assert_eq!(
        current.get_memory_reservation(),
        old.get_memory_reservation()
    );
    assert_eq!(
        current.get_memory_reservation_for_growth(),
        old.get_memory_reservation_for_growth()
    );
    assert_eq!(current.get_memory_guard_size(), old.get_memory_guard_size());
    assert_eq!(
        current.get_guard_before_linear_memory(),
        old.get_guard_before_linear_memory()
    );
    assert_eq!(current.get_memory_may_move(), old.get_memory_may_move());
    assert_eq!(
        current.get_async_stack_zeroing(),
        old.get_async_stack_zeroing()
    );
}

#[test]
fn four_profiles_bind_actual_engine_policy_and_remain_distinct() {
    let mut identities = BTreeSet::new();
    for allocator in [InstanceAllocator::OnDemand, InstanceAllocator::Pooling] {
        for optimization in [
            CompilerOptimization::Speed,
            CompilerOptimization::SpeedAndSize,
        ] {
            let policy = WasmtimeConfig {
                instance_allocator: allocator,
                compiler_optimization: optimization,
                pooling_maximum_instances: 2,
                ..WasmtimeConfig::default()
            };
            let profile = policy.profile(DispatchMode::Generic);
            assert!(identities.insert(profile.configuration["configuration-digest"].clone()));
            let mut configured = Config::new();
            policy.apply_engine(&mut configured).unwrap();
            let engine = Engine::new(&configured).unwrap();
            assert_eq!(
                engine.get_cranelift_opt_level(),
                Some(match optimization {
                    CompilerOptimization::Speed => OptLevel::Speed,
                    CompilerOptimization::SpeedAndSize => OptLevel::SpeedAndSize,
                })
            );
            assert_eq!(
                profile.configuration["compiler-optimization"],
                optimization.name()
            );
            for (name, actual) in [
                ("memory-reservation-bytes", engine.get_memory_reservation()),
                (
                    "memory-reservation-for-growth-bytes",
                    engine.get_memory_reservation_for_growth(),
                ),
                ("memory-guard-bytes", engine.get_memory_guard_size()),
            ] {
                assert_eq!(profile.configuration[name], actual.to_string());
            }
            assert!(engine.get_consume_fuel() && engine.get_epoch_interruption());
            assert!(engine.get_memory_init_cow());
            assert!(!engine.get_async_stack_zeroing());
            assert!(engine.get_guard_before_linear_memory());
            assert_eq!(engine.get_async_stack_size(), policy.async_stack_bytes);
            assert_eq!(engine.get_max_wasm_stack(), policy.maximum_wasm_stack_bytes);
            if let Some(pool) = engine.get_pooling_config() {
                assert_eq!(pool.get_max_unused_warm_slots(), 0);
                assert_eq!(pool.get_decommit_batch_size(), 1);
                assert_eq!(pool.get_memory_keep_resident(), 0);
                assert_eq!(pool.get_table_keep_resident(), 0);
                assert_eq!(pool.get_async_stack_keep_resident(), 0);
                assert_eq!(pool.get_total_core_instances(), 8);
                assert_eq!(pool.get_total_memories(), 4);
                assert_eq!(pool.get_total_tables(), 4);
                assert_eq!(pool.get_total_stacks(), 2);
            } else {
                assert_eq!(allocator, InstanceAllocator::OnDemand);
            }
        }
    }
    assert_eq!(identities.len(), 4);
}

#[test]
fn pooling_rejects_host_sized_products_before_mutating_engine_configuration() {
    let changes: &[fn(&mut WasmtimeConfig)] = &[
        |c| c.pooling_maximum_component_instance_bytes = usize::MAX,
        |c| c.pooling_maximum_core_instance_bytes = usize::MAX,
        |c| c.maximum_memory_bytes = usize::MAX as u64,
        |c| c.maximum_table_elements = usize::MAX,
        |c| c.async_stack_bytes = usize::MAX,
    ];
    for change in changes {
        let mut policy = WasmtimeConfig {
            instance_allocator: InstanceAllocator::Pooling,
            pooling_maximum_instances: 2,
            ..WasmtimeConfig::default()
        };
        change(&mut policy);
        let mut configured = Config::new();
        configured.consume_fuel(false);
        assert_eq!(
            policy.apply_engine(&mut configured).unwrap_err().code,
            PlatformErrorCode::InvalidArgument
        );
        assert!(!Engine::new(&configured).unwrap().get_consume_fuel());
    }
}
