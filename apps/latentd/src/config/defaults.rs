use super::{
    CacheConfig, CatalogConfig, ExecutionConfig, LimitConfig, RetentionConfig, TelemetryConfig,
    WorkerConfig, MIB,
};

impl Default for WorkerConfig {
    fn default() -> Self {
        Self {
            runtime: 2,
            control: 2,
        }
    }
}

impl Default for ExecutionConfig {
    fn default() -> Self {
        Self {
            maximum_cpu_fuel: 100_000_000,
            maximum_wall_time_millis: 1000,
            maximum_log_bytes: 16 * 1024,
        }
    }
}

impl Default for LimitConfig {
    fn default() -> Self {
        Self {
            maximum_component_bytes: 16 * MIB,
            maximum_payload_bytes: MIB,
            maximum_connections: 32,
        }
    }
}

impl Default for CacheConfig {
    fn default() -> Self {
        Self {
            entries: 8,
            source_bytes: 64 * MIB,
            metadata_bytes: 8 * MIB,
            compiled_image_bytes: 128 * MIB,
            preparations: 1,
        }
    }
}

impl Default for CatalogConfig {
    fn default() -> Self {
        Self {
            release_entries: 4096,
            release_index_bytes: 64 * MIB,
            deployments: 4096,
            deployment_state_bytes: 64 * MIB,
        }
    }
}

impl Default for RetentionConfig {
    fn default() -> Self {
        Self {
            terminal_entries: 1024,
            terminal_ttl_millis: 300_000,
            bytes: 256 * MIB,
        }
    }
}

impl Default for TelemetryConfig {
    fn default() -> Self {
        Self {
            queue_entries: 128,
            retained_entries: 1024,
            retained_bytes: 8 * MIB,
        }
    }
}
