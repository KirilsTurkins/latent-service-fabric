use std::mem::size_of;

use latent_artifacts::CacheEntryDescriptor;
use latent_core::{BoxFuture, PlatformError};

use super::bounds::{self, Cost};
use super::health;
use super::{
    class_name, exhausted, invalid, CacheInventoryWriter, CellClassCapacity, InventoryReporter,
    NodeCacheSummary, NodeDescriptor, NodeHealthObservation, NodeInventory, NodeQuotaSummary,
    NodeResourceTopology, NodeTopologyEntry, NodeTopologyWriter, StandaloneInventoryConfig,
    StandaloneInventorySources,
};

/// One reporter borrows existing node-owned sources. It creates no timer,
/// exporter, worker, service registry, or independent resource ledger.
pub struct StandaloneInventoryReporter {
    config: StandaloneInventoryConfig,
    node: NodeDescriptor,
    sources: StandaloneInventorySources,
}

impl StandaloneInventoryReporter {
    pub fn new(
        config: StandaloneInventoryConfig,
        node: NodeDescriptor,
        sources: StandaloneInventorySources,
    ) -> Result<Self, PlatformError> {
        bounds::config(&config)?;
        let mut cost = Cost::new(&config)?;
        cost.node(&node)?;
        reserve_collections(&config, &mut cost)?;
        Ok(Self {
            config,
            node,
            sources,
        })
    }

    /// Sources are individually coherent snapshots; no cross-layer atomicity is
    /// implied. Work and response allocation depend only on configured bounds.
    pub fn snapshot_now(&self) -> Result<NodeInventory, PlatformError> {
        let sample = self.sources.clock.sample();
        let mut cost = Cost::new(&self.config)?;
        cost.node(&self.node)?;
        reserve_collections(&self.config, &mut cost)?;
        let mut health = NodeHealthObservation::new(sample.unix_millis());
        let cell_capacity = self.cells(&mut health)?;
        let queue_depth = cell_capacity
            .iter()
            .map(|cell| u64::from(cell.queue_depth))
            .sum();
        let queue_capacity = cell_capacity
            .iter()
            .map(|cell| u64::from(cell.queue_capacity))
            .sum();
        let quotas = self.quotas(&mut health);
        let mut pressure = health::load(
            &self.sources,
            sample.monotonic(),
            self.config.maximum_load_age,
            &mut health,
        );
        pressure.queue_pressure_milli = health::ratio(queue_depth, queue_capacity);
        let (cache_summary, cache_entries) = self.cache(&mut cost, &mut health)?;
        pressure.cache_pressure_milli = cache_pressure(cache_summary);
        let topology = self.topology(&mut cost, &mut health)?;
        Ok(NodeInventory {
            node: self.node.clone(),
            cell_capacity,
            memory_pressure_milli: pressure.memory_pressure_milli,
            queue_depth,
            route_generation: self.sources.routes.generation(),
            cache_entries,
            observed_at_unix_millis: sample.unix_millis(),
            cache_summary,
            pressure,
            health,
            topology,
            quotas,
            retained_bytes: cost.used(),
        })
    }

    fn cells(
        &self,
        health: &mut NodeHealthObservation,
    ) -> Result<Vec<CellClassCapacity>, PlatformError> {
        let mut cells = Vec::with_capacity(self.config.cell_classes.len());
        for class in &self.config.cell_classes {
            let result = self.sources.scheduler.snapshot(*class);
            let observation_available = result.is_ok();
            let value = result.unwrap_or_else(|_| {
                health.degrade("scheduler-unavailable", false, false);
                super::SchedulerInventorySnapshot::default()
            });
            let s = value.observations;
            if u64::from(s.available) + u64::from(s.active_leases) + u64::from(s.quarantined)
                != u64::from(s.capacity)
                || s.queue_depth > value.queue_capacity
                || s.queued_tenants > s.queue_depth
                || (s.accepting && value.queue_capacity == 0)
            {
                return Err(invalid("invalid-inventory-scheduler-snapshot"));
            }
            cells.push(CellClassCapacity {
                class: class_name(*class).to_owned(),
                observation_available,
                accepting: s.accepting,
                total: s.capacity,
                available: s.available,
                active: s.active_leases,
                quarantined: s.quarantined,
                queue_depth: s.queue_depth,
                queue_capacity: value.queue_capacity,
                queued_tenants: s.queued_tenants,
                rejected: s.rejected,
                cancellations: s.cancellations,
                expired: s.expired,
                granted: s.granted,
                total_wait_micros: s.total_wait_micros,
                max_wait_micros: s.max_wait_micros,
                oldest_lease_age_micros: s.oldest_lease_age_micros,
            });
        }
        let usable: u64 = cells
            .iter()
            .map(|cell| u64::from(cell.total - cell.quarantined))
            .sum();
        if usable == 0 {
            health.degrade("no-usable-execution-cells", false, false);
        } else {
            if !cells
                .iter()
                .any(|cell| cell.accepting && cell.total > cell.quarantined)
            {
                health.degrade("scheduler-not-accepting", false, true);
            }
            if cells.iter().any(|cell| cell.quarantined != 0) {
                health.degrade("execution-cells-quarantined", true, true);
            }
        }
        Ok(cells)
    }

    fn quotas(&self, health: &mut NodeHealthObservation) -> Option<NodeQuotaSummary> {
        if let (Ok(usage), Ok(tenants)) = (
            self.sources.quotas.usage(),
            self.sources.quotas.retained_tenant_count(),
        ) {
            Some(NodeQuotaSummary {
                usage,
                limits: self.sources.quotas.policy().limits,
                retained_tenants: u64::try_from(tenants).unwrap_or(u64::MAX),
            })
        } else {
            health.degrade("quota-unavailable", false, false);
            None
        }
    }

    fn cache(
        &self,
        cost: &mut Cost,
        health: &mut NodeHealthObservation,
    ) -> Result<(NodeCacheSummary, Vec<CacheEntryDescriptor>), PlatformError> {
        let mut entries = Vec::with_capacity(self.config.maximum_cache_descriptors);
        let mut writer = CacheInventoryWriter {
            summary: None,
            entries: &mut entries,
            cost,
            maximum: self.config.maximum_cache_descriptors,
            failed: false,
        };
        let result = self.sources.cache.snapshot(&mut writer);
        if writer.failed {
            return Err(exhausted());
        }
        let summary = writer.summary.filter(|summary| summary.available);
        if result.is_err() || summary.is_none() {
            health.degrade("cache-unavailable", true, true);
            entries.clear();
            return Ok((NodeCacheSummary::default(), entries));
        }
        Ok((summary.expect("available summary"), entries))
    }

    fn topology(
        &self,
        cost: &mut Cost,
        health: &mut NodeHealthObservation,
    ) -> Result<NodeResourceTopology, PlatformError> {
        let mut entries = Vec::with_capacity(self.config.maximum_topology_entries);
        let mut writer = NodeTopologyWriter {
            entries: &mut entries,
            cost,
            maximum: self.config.maximum_topology_entries,
            failed: false,
            truncated: false,
        };
        let result = self.sources.topology.snapshot(&mut writer);
        if writer.failed {
            return Err(exhausted());
        }
        let complete = result.as_ref().is_ok_and(|complete| *complete) && !writer.truncated;
        if result.is_err() {
            health.degrade("topology-unavailable", true, true);
            entries.clear();
        } else if !complete {
            health.degrade("topology-incomplete", true, true);
        }
        Ok(NodeResourceTopology {
            entries,
            available: result.is_ok(),
            complete,
        })
    }
}

impl InventoryReporter for StandaloneInventoryReporter {
    fn snapshot(&self) -> BoxFuture<'_, Result<NodeInventory, PlatformError>> {
        Box::pin(async move { self.snapshot_now() })
    }
}

fn reserve_collections(
    config: &StandaloneInventoryConfig,
    cost: &mut Cost,
) -> Result<(), PlatformError> {
    // Count the complete selected capacities before allocating any response Vec.
    cost.charge(config.cell_classes.len() * (size_of::<CellClassCapacity>() + 16))?;
    cost.charge(config.maximum_cache_descriptors * size_of::<CacheEntryDescriptor>())?;
    cost.charge(config.maximum_topology_entries * size_of::<NodeTopologyEntry>())
}

fn cache_pressure(cache: NodeCacheSummary) -> u32 {
    if !cache.available {
        return 0;
    }
    [
        (cache.entries, cache.maximum_entries),
        (cache.source_bytes, cache.maximum_source_bytes),
        (cache.metadata_bytes, cache.maximum_metadata_bytes),
        (
            cache.compiled_image_bytes,
            cache.maximum_compiled_image_bytes,
        ),
        (cache.preparing, cache.maximum_concurrent_preparations),
    ]
    .into_iter()
    .map(|(used, maximum)| health::ratio(used, maximum))
    .max()
    .unwrap_or(0)
}
