use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::RwLock;

use latent_core::{BoxFuture, Metadata, NodeId, PlatformError, RouteGeneration};
use latent_node::{
    HealthStatus, InventoryReporter, NodeCacheSummary, NodeDescriptor, NodeHealthObservation,
    NodeInventory, NodePressureObservation, NodeResourceTopology,
};

pub(in super::super) struct Inventory {
    pub snapshots: AtomicUsize,
    pub value: RwLock<NodeInventory>,
}

impl Inventory {
    pub fn new() -> Self {
        Self {
            snapshots: AtomicUsize::new(0),
            value: RwLock::new(NodeInventory {
                node: NodeDescriptor {
                    id: NodeId("local-test".to_owned()),
                    architecture: "x86_64".to_owned(),
                    operating_system: "linux".to_owned(),
                    cpu_features: Vec::new(),
                    trust_classes: vec!["local".to_owned()],
                    region: None,
                    zone: None,
                    endpoint: "in-memory://management".to_owned(),
                    identity: "test-node".to_owned(),
                    attributes: Metadata::new(),
                },
                cell_capacity: Vec::new(),
                memory_pressure_milli: 0,
                queue_depth: 0,
                route_generation: RouteGeneration(0),
                cache_entries: Vec::new(),
                observed_at_unix_millis: 1,
                cache_summary: NodeCacheSummary::default(),
                pressure: NodePressureObservation::default(),
                health: NodeHealthObservation {
                    status: HealthStatus::Degraded,
                    ready: false,
                    healthy: true,
                    reasons: vec!["no-usable-cell-capacity".to_owned()],
                    observed_at_unix_millis: 1,
                },
                topology: NodeResourceTopology::default(),
                quotas: None,
                retained_bytes: 4096,
            }),
        }
    }
}

impl InventoryReporter for Inventory {
    fn snapshot(&self) -> BoxFuture<'_, Result<NodeInventory, PlatformError>> {
        self.snapshots.fetch_add(1, Ordering::Relaxed);
        Box::pin(async { Ok(self.value.read().unwrap().clone()) })
    }
}
