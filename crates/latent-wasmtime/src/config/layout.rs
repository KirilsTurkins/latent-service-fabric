//! The pinned 47.0.3 layout and reset policy, shared by setters and identity.

use latent_core::Metadata;
use wasmtime::Config;

use super::{InstanceAllocator, WasmtimeConfig};

pub(super) const ASYNC_STACK_ZEROING: bool = false;
pub(super) const POOL_UNUSED_WARM_SLOTS: u32 = 0;
pub(super) const POOL_DECOMMIT_BATCH_SIZE: usize = 1;
pub(super) const POOL_KEEP_RESIDENT_BYTES: usize = 0;

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct MemoryLayout {
    reservation: u64,
    growth_reservation: u64,
    guard: u64,
}

impl MemoryLayout {
    pub(super) fn compiler_bounded(&self) -> bool {
        self.reservation <= 64 * 1024 * 1024 * 1024
            && self.growth_reservation <= 64 * 1024 * 1024 * 1024
            && self.guard <= 1024 * 1024 * 1024
    }
    pub(super) fn apply(&self, config: &mut Config) {
        config.memory_reservation(self.reservation);
        config.memory_reservation_for_growth(self.growth_reservation);
        config.memory_guard_size(self.guard);
        // These are the existing Wasmtime defaults, including for pooling.
        // Pooling's allocator itself prevents relocation on growth.
        config.memory_may_move(true);
        config.guard_before_linear_memory(true);
    }
}

impl WasmtimeConfig {
    pub(super) fn memory_layout(&self) -> MemoryLayout {
        match self.instance_allocator {
            InstanceAllocator::Pooling => MemoryLayout {
                reservation: self.maximum_memory_bytes,
                growth_reservation: 0,
                guard: 0,
            },
            InstanceAllocator::OnDemand => MemoryLayout {
                // Preserve the pinned engine's host-width defaults. These are
                // virtual reservations, not committed memory or RSS limits.
                reservation: if cfg!(target_pointer_width = "64") {
                    1 << 32
                } else {
                    10 << 20
                },
                growth_reservation: if cfg!(target_pointer_width = "64") {
                    2 << 30
                } else {
                    1 << 20
                },
                guard: if cfg!(target_pointer_width = "64") {
                    32 << 20
                } else {
                    64 << 10
                },
            },
        }
    }

    pub(super) fn include_engine_policy(&self, fields: &mut Metadata) {
        let layout = self.memory_layout();
        for (name, value) in [
            (
                "engine-layout-policy",
                "wasmtime-47.0.3-bounded-v1".to_owned(),
            ),
            (
                "compiler-optimization",
                self.compiler_optimization.name().to_owned(),
            ),
            ("memory-reservation-bytes", layout.reservation.to_string()),
            (
                "memory-reservation-for-growth-bytes",
                layout.growth_reservation.to_string(),
            ),
            ("memory-guard-bytes", layout.guard.to_string()),
            ("memory-may-move", "true".to_owned()),
            ("guard-before-linear-memory", "true".to_owned()),
            ("async-stack-zeroing", ASYNC_STACK_ZEROING.to_string()),
            (
                "pooling-unused-warm-slots",
                POOL_UNUSED_WARM_SLOTS.to_string(),
            ),
            (
                "pooling-decommit-batch-size",
                POOL_DECOMMIT_BATCH_SIZE.to_string(),
            ),
            (
                "pooling-linear-memory-keep-resident-bytes",
                POOL_KEEP_RESIDENT_BYTES.to_string(),
            ),
            (
                "pooling-table-keep-resident-bytes",
                POOL_KEEP_RESIDENT_BYTES.to_string(),
            ),
            (
                "pooling-async-stack-keep-resident-bytes",
                POOL_KEEP_RESIDENT_BYTES.to_string(),
            ),
        ] {
            fields.insert(name.to_owned(), value);
        }
    }
}
