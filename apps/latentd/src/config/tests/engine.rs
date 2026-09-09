use latent_wasmtime::{CompilerOptimization, InstanceAllocator};

use super::{config, document, input, CellConfig, MIB};
use crate::config::{EngineAllocator, EngineConfig, EngineOptimization};

#[test]
fn finite_engine_profiles_derive_checked_pool_capacity_without_opening_storage() {
    for allocator in [EngineAllocator::OnDemand, EngineAllocator::Pooling] {
        for optimization in [EngineOptimization::Speed, EngineOptimization::SpeedAndSize] {
            let (directory, mut config) = config();
            config.engine = EngineConfig {
                allocator,
                optimization,
            };
            config.cells.push(CellConfig {
                class: "small".to_owned(),
                capacity: 3,
                queue_capacity: 1,
                maximum_memory_bytes: 32 * MIB as u64,
            });
            let settings = config.derive().expect("bounded engine profile");
            assert!(!directory.path().join("data").exists());
            assert_eq!(settings.wasmtime.maximum_active_instances, 5);
            assert_eq!(
                settings.wasmtime.pooling_maximum_instances,
                if allocator == EngineAllocator::Pooling {
                    5
                } else {
                    1
                }
            );
            assert_eq!(
                settings.wasmtime.instance_allocator,
                if allocator == EngineAllocator::Pooling {
                    InstanceAllocator::Pooling
                } else {
                    InstanceAllocator::OnDemand
                }
            );
            assert_eq!(
                settings.wasmtime.compiler_optimization,
                if optimization == EngineOptimization::Speed {
                    CompilerOptimization::Speed
                } else {
                    CompilerOptimization::SpeedAndSize
                }
            );
            assert_eq!(settings.wasmtime.maximum_memory_bytes, 64 * MIB as u64);
            config.cells[0].capacity = u32::MAX;
            assert!(config.derive().is_err());
            assert!(!directory.path().join("data").exists());
        }
    }
}

#[test]
fn engine_json_has_closed_choices_and_preserves_omitted_defaults() {
    let omitted = input::decode(document().as_bytes()).unwrap();
    assert_eq!(omitted.engine, EngineConfig::default());
    for value in ["{}", r#"{"allocator":"on-demand","optimization":"speed"}"#] {
        let source = document().replacen('{', &format!("{{\"engine\":{value},"), 1);
        let explicit = input::decode(source.as_bytes()).unwrap();
        assert_eq!(explicit.engine, omitted.engine);
    }
    for allocator in ["on-demand", "pooling"] {
        for optimization in ["speed", "speed-and-size"] {
            let source = document().replacen('{', &format!(
                "{{\"engine\":{{\"allocator\":\"{allocator}\",\"optimization\":\"{optimization}\"}},"), 1);
            assert!(input::decode(source.as_bytes()).is_ok());
        }
    }
    for value in [
        "null",
        "[]",
        r#"["pooling","speed"]"#,
        r#"{"allocator":null}"#,
        r#"{"optimization":null}"#,
        r#"{"allocator":"unbounded"}"#,
        r#"{"optimization":"none"}"#,
        r#"{"compilerFlags":"sensitive"}"#,
        r#"{"allocator":"pooling","allocator":"on-demand"}"#,
        r#"{"optimization":"speed","optimization":"speed-and-size"}"#,
    ] {
        let source = document().replacen('{', &format!("{{\"engine\":{value},"), 1);
        let error = input::decode(source.as_bytes())
            .err()
            .unwrap_or_else(|| panic!("accepted engine JSON: {value}"));
        assert!(!error.message.contains("sensitive"));
    }
    let source = document().replacen('{', "{\"engine\":{},\"engine\":{},", 1);
    assert!(input::decode(source.as_bytes()).is_err());
}
