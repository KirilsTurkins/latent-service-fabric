//! Fixed-cost adapters over the resources already owned by this node.

mod cache;
#[cfg(test)]
mod tests;
mod topology;

use std::sync::{Arc, OnceLock};

use latent_core::{BoxFuture, PlatformError, PlatformErrorCode};
use latent_node::{InventoryReporter, NodeInventory, StandaloneInventoryReporter};

pub(super) use cache::CacheSource;
pub(super) use topology::TopologySource;

/// The RPC adapter is constructed before binding. Install its single reporter
/// with the actual endpoint before opening the transport acceptance gate.
#[derive(Default)]
pub(super) struct InventorySlot {
    reporter: OnceLock<Arc<StandaloneInventoryReporter>>,
}

impl InventorySlot {
    pub(super) fn new() -> Self {
        Self::default()
    }

    pub(super) fn install(
        &self,
        reporter: Arc<StandaloneInventoryReporter>,
    ) -> Result<(), PlatformError> {
        self.reporter.set(reporter).map_err(|_| {
            super::error(
                PlatformErrorCode::StateConflict,
                "standalone inventory is already installed",
            )
        })
    }

    pub(super) fn snapshot_now(&self) -> Result<NodeInventory, PlatformError> {
        self.reporter
            .get()
            .ok_or_else(|| {
                super::error(
                    PlatformErrorCode::Unavailable,
                    "standalone inventory is not installed",
                )
            })?
            .snapshot_now()
    }
}

impl InventoryReporter for InventorySlot {
    fn snapshot(&self) -> BoxFuture<'_, Result<NodeInventory, PlatformError>> {
        Box::pin(async move { self.snapshot_now() })
    }
}
