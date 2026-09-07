use latent_core::Metadata;
use latent_telemetry::{MetricKind, MetricPoint};

use super::{CellClassCapacity, NodeCacheSummary, NodeInventory};

impl NodeInventory {
    /// Fixed metric names and at most five allow-listed class values. IDs,
    /// topology names, cache descriptors and arbitrary attributes are omitted.
    /// Integer gauges use the telemetry port's f64 representation; exact u64
    /// generations and counters remain available in the inventory itself.
    #[must_use]
    pub fn metric_points(&self) -> Vec<MetricPoint> {
        let mut metrics = Points {
            values: Vec::with_capacity(128),
            observed_at: self.observed_at_unix_millis,
        };
        for cell in self.cell_capacity.iter().take(5) {
            let class = match cell.class.as_str() {
                "tiny" => "tiny",
                "small" => "small",
                "standard" => "standard",
                "large" => "large",
                "extra-large" => "extra-large",
                _ => continue,
            };
            metrics.cells(cell, class);
        }
        metrics.gauge("latent.route.generation", self.route_generation.0, "1");
        metrics.gauge("latent.node.queue_depth", self.queue_depth, "1");
        metrics.gauge("latent.node.ready", u64::from(self.health.ready), "1");
        metrics.gauge("latent.node.healthy", u64::from(self.health.healthy), "1");
        metrics.gauge(
            "latent.node.load_available",
            u64::from(self.pressure.load_available),
            "1",
        );
        if self.pressure.load_available {
            metrics.gauge(
                "latent.node.cpu_pressure_milli",
                u64::from(self.pressure.cpu_pressure_milli),
                "1",
            );
            metrics.gauge(
                "latent.node.memory_pressure_milli",
                u64::from(self.pressure.memory_pressure_milli),
                "1",
            );
        }
        metrics.gauge(
            "latent.node.queue_pressure_milli",
            u64::from(self.pressure.queue_pressure_milli),
            "1",
        );
        metrics.gauge(
            "latent.cache.available",
            u64::from(self.cache_summary.available),
            "1",
        );
        if self.cache_summary.available {
            metrics.cache(self.cache_summary);
        }
        if let Some(quotas) = self.quotas {
            for (name, value, unit) in [
                (
                    "latent.quota.reserved_activations",
                    u64::from(quotas.usage.active_activations),
                    "1",
                ),
                (
                    "latent.quota.queued_activations",
                    u64::from(quotas.usage.queued_activations),
                    "1",
                ),
                (
                    "latent.quota.reserved_cpu_fuel",
                    quotas.usage.reserved_cpu_fuel,
                    "1",
                ),
                (
                    "latent.quota.reserved_memory_bytes",
                    quotas.usage.reserved_memory_bytes,
                    "By",
                ),
                (
                    "latent.quota.retained_tenants",
                    quotas.retained_tenants,
                    "1",
                ),
            ] {
                metrics.gauge(name, value, unit);
            }
        }
        debug_assert!(metrics.values.len() <= 128);
        metrics.values
    }
}

struct Points {
    values: Vec<MetricPoint>,
    observed_at: u64,
}

impl Points {
    fn gauge(&mut self, name: &str, value: u64, unit: &str) {
        self.push(name, MetricKind::Gauge, value, unit, None);
    }

    #[expect(
        clippy::cast_precision_loss,
        reason = "The telemetry contract represents numeric samples as f64; exact counters remain in NodeInventory."
    )]
    fn push(&mut self, name: &str, kind: MetricKind, value: u64, unit: &str, class: Option<&str>) {
        self.values.push(MetricPoint {
            name: name.to_owned(),
            kind,
            value: value as f64,
            unit: unit.to_owned(),
            attributes: class.map_or_else(Metadata::new, |class| {
                Metadata::from([("cell_class".to_owned(), class.to_owned())])
            }),
            observed_at_unix_millis: self.observed_at,
        });
    }

    fn cells(&mut self, cell: &CellClassCapacity, class: &str) {
        self.push(
            "latent.scheduler.observation_available",
            MetricKind::Gauge,
            u64::from(cell.observation_available),
            "1",
            Some(class),
        );
        if !cell.observation_available {
            return;
        }
        self.push(
            "latent.scheduler.accepting",
            MetricKind::Gauge,
            u64::from(cell.accepting),
            "1",
            Some(class),
        );
        for (name, value, unit) in [
            ("latent.cell.capacity", u64::from(cell.total), "1"),
            ("latent.cell.available", u64::from(cell.available), "1"),
            ("latent.cell.active", u64::from(cell.active), "1"),
            ("latent.cell.quarantined", u64::from(cell.quarantined), "1"),
            (
                "latent.scheduler.queue_depth",
                u64::from(cell.queue_depth),
                "1",
            ),
            (
                "latent.scheduler.queue_capacity",
                u64::from(cell.queue_capacity),
                "1",
            ),
            (
                "latent.scheduler.queued_tenants",
                u64::from(cell.queued_tenants),
                "1",
            ),
            ("latent.scheduler.max_wait", cell.max_wait_micros, "us"),
            (
                "latent.cell.oldest_lease_age",
                cell.oldest_lease_age_micros,
                "us",
            ),
        ] {
            self.push(name, MetricKind::Gauge, value, unit, Some(class));
        }
        for (name, value, unit) in [
            ("latent.scheduler.rejected", cell.rejected, "1"),
            ("latent.scheduler.cancellations", cell.cancellations, "1"),
            ("latent.scheduler.expired", cell.expired, "1"),
            ("latent.scheduler.granted", cell.granted, "1"),
            ("latent.scheduler.total_wait", cell.total_wait_micros, "us"),
        ] {
            self.push(name, MetricKind::Counter, value, unit, Some(class));
        }
    }

    fn cache(&mut self, cache: NodeCacheSummary) {
        for (name, value, unit) in [
            ("latent.cache.entries", cache.entries, "1"),
            ("latent.cache.maximum_entries", cache.maximum_entries, "1"),
            ("latent.cache.source_bytes", cache.source_bytes, "By"),
            (
                "latent.cache.maximum_source_bytes",
                cache.maximum_source_bytes,
                "By",
            ),
            ("latent.cache.metadata_bytes", cache.metadata_bytes, "By"),
            (
                "latent.cache.maximum_metadata_bytes",
                cache.maximum_metadata_bytes,
                "By",
            ),
            (
                "latent.cache.compiled_image_bytes",
                cache.compiled_image_bytes,
                "By",
            ),
            (
                "latent.cache.maximum_compiled_image_bytes",
                cache.maximum_compiled_image_bytes,
                "By",
            ),
            ("latent.cache.preparing", cache.preparing, "1"),
            (
                "latent.cache.maximum_concurrent_preparations",
                cache.maximum_concurrent_preparations,
                "1",
            ),
            (
                "latent.cache.preparing_source_bytes",
                cache.preparing_source_bytes,
                "By",
            ),
            (
                "latent.cache.preparing_metadata_bytes",
                cache.preparing_metadata_bytes,
                "By",
            ),
        ] {
            self.gauge(name, value, unit);
        }
        for (name, value) in [
            ("latent.cache.hits", cache.hits),
            ("latent.cache.misses", cache.misses),
            ("latent.cache.evictions", cache.evictions),
            ("latent.cache.invalidations", cache.invalidations),
        ] {
            self.push(name, MetricKind::Counter, value, "1", None);
        }
    }
}
