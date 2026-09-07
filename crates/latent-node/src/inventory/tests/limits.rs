use latent_core::PlatformErrorCode;

use super::*;

#[test]
fn invalid_and_overallocated_node_descriptors_fail_before_any_source_query() {
    let fixture = Fixture::new();
    for case in 0..3 {
        let mut node = node();
        match case {
            0 => {
                node.identity = String::with_capacity(513);
                node.identity.push('x');
            }
            1 => node.cpu_features = Vec::with_capacity(33),
            _ => {
                node.attributes = (0..33)
                    .map(|index| (index.to_string(), "v".to_owned()))
                    .collect();
            }
        }
        let error = StandaloneInventoryReporter::new(
            StandaloneInventoryConfig::default(),
            node,
            fixture.sources(),
        )
        .err()
        .expect("descriptor allocation bound");
        assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
    }
    assert_eq!(fixture.routes.reads.load(Ordering::Relaxed), 0);
}

#[test]
fn minimum_structural_allocation_and_fixed_class_limits_are_validated_at_startup() {
    let fixture = Fixture::new();
    let too_small = StandaloneInventoryConfig {
        maximum_snapshot_bytes: 1,
        ..StandaloneInventoryConfig::default()
    };
    assert_eq!(
        StandaloneInventoryReporter::new(too_small, node(), fixture.sources())
            .err()
            .expect("fixed DTO costs")
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    let duplicate = StandaloneInventoryConfig {
        cell_classes: vec![CellClass::Standard, CellClass::Standard],
        ..StandaloneInventoryConfig::default()
    };
    assert_eq!(
        StandaloneInventoryReporter::new(duplicate, node(), fixture.sources())
            .err()
            .expect("duplicate class")
            .message,
        "duplicate-inventory-cell-class"
    );
}

struct OversizedCache;
impl CacheInventorySource for OversizedCache {
    fn snapshot(&self, writer: &mut CacheInventoryWriter<'_>) -> Result<(), PlatformError> {
        writer.set_summary(cache_summary())?;
        let mut entry = descriptor();
        entry.key = String::with_capacity(513);
        entry.key.push('x');
        assert!(writer.push_descriptor(&entry).is_err());
        // Ignoring a failed write cannot turn an invalid partial snapshot valid.
        Ok(())
    }
}

#[test]
fn descriptor_spare_capacity_cannot_bypass_the_preclone_writer_bound() {
    let fixture = Fixture::new();
    let mut sources = fixture.sources();
    sources.cache = Arc::new(OversizedCache);
    let reporter =
        StandaloneInventoryReporter::new(StandaloneInventoryConfig::default(), node(), sources)
            .expect("reporter");
    assert_eq!(
        reporter
            .snapshot_now()
            .expect_err("invalid descriptor")
            .code,
        PlatformErrorCode::ResourceExhausted
    );
}

struct LargeRow;
impl NodeTopologySource for LargeRow {
    fn snapshot(&self, writer: &mut NodeTopologyWriter<'_>) -> Result<bool, PlatformError> {
        let row = NodeTopologyEntry {
            name: "fixed-row".to_owned(),
            kind: "process".to_owned(),
            ownership: ResourceOwnership::NodeFixed,
            configured_count: 1,
            active_count: Some(1),
            attributes: (0..16)
                .map(|index| (index.to_string(), "v".to_owned()))
                .collect(),
        };
        writer.push(&row)
    }
}

#[test]
fn aggregate_snapshot_bytes_reject_individually_bounded_topology_fields() {
    let fixture = Fixture::new();
    let mut sources = fixture.sources();
    sources.topology = Arc::new(LargeRow);
    let config = StandaloneInventoryConfig {
        maximum_snapshot_bytes: 16 * 1024,
        ..StandaloneInventoryConfig::default()
    };
    let reporter =
        StandaloneInventoryReporter::new(config, node(), sources).expect("fixed base fits");
    assert_eq!(
        reporter
            .snapshot_now()
            .expect_err("aggregate allocation")
            .message,
        "inventory-snapshot-capacity"
    );
}

struct NominalTopology {
    rows: usize,
    examined: AtomicUsize,
}
impl NodeTopologySource for NominalTopology {
    fn snapshot(&self, writer: &mut NodeTopologyWriter<'_>) -> Result<bool, PlatformError> {
        let selected = writer.remaining().min(self.rows);
        for index in 0..selected {
            self.examined.fetch_add(1, Ordering::Relaxed);
            writer.push(&NodeTopologyEntry {
                name: format!("fixed-kind-{index}"),
                kind: "execution-host".to_owned(),
                ownership: ResourceOwnership::NodeFixed,
                configured_count: 1,
                active_count: None,
                attributes: Metadata::new(),
            })?;
        }
        Ok(selected == self.rows)
    }
}

#[test]
fn topology_selection_is_bounded_without_allocating_nominal_dormant_catalog_rows() {
    let fixture = Fixture::new();
    let topology = Arc::new(NominalTopology {
        rows: 100_000,
        examined: AtomicUsize::new(0),
    });
    let mut sources = fixture.sources();
    sources.topology = topology.clone();
    let config = StandaloneInventoryConfig {
        maximum_topology_entries: 2,
        maximum_cache_descriptors: 0,
        ..StandaloneInventoryConfig::default()
    };
    let reporter =
        StandaloneInventoryReporter::new(config.clone(), node(), sources).expect("reporter");
    let inventory = reporter.snapshot_now().expect("bounded selection");
    assert_eq!(inventory.topology.entries.len(), 2);
    assert_eq!(topology.examined.load(Ordering::Relaxed), 2);
    assert!(!inventory.topology.complete);
    assert!(inventory.topology.available);
    assert!(inventory
        .topology
        .entries
        .iter()
        .all(|row| row.active_count.is_none()));
    assert!(inventory.retained_bytes <= config.maximum_snapshot_bytes);
}

struct FailedSources;
impl CacheInventorySource for FailedSources {
    fn snapshot(&self, writer: &mut CacheInventoryWriter<'_>) -> Result<(), PlatformError> {
        writer.set_summary(cache_summary())?;
        writer.push_descriptor(&descriptor())?;
        Err(invalid("private source failure text"))
    }
}
impl NodeTopologySource for FailedSources {
    fn snapshot(&self, writer: &mut NodeTopologyWriter<'_>) -> Result<bool, PlatformError> {
        writer.push(&NodeTopologyEntry {
            name: "partial".to_owned(),
            kind: "process".to_owned(),
            ownership: ResourceOwnership::NodeFixed,
            configured_count: 1,
            active_count: Some(1),
            attributes: Metadata::new(),
        })?;
        Err(invalid("private topology failure text"))
    }
}

#[test]
fn source_failures_drop_partial_rows_and_keep_diagnostic_health_explicit() {
    let fixture = Fixture::new();
    let mut sources = fixture.sources();
    sources.cache = Arc::new(FailedSources);
    sources.topology = Arc::new(FailedSources);
    let inventory =
        StandaloneInventoryReporter::new(StandaloneInventoryConfig::default(), node(), sources)
            .expect("reporter")
            .snapshot_now()
            .expect("degraded observation");
    assert!(!inventory.cache_summary.available);
    assert!(inventory.cache_entries.is_empty());
    assert!(!inventory.topology.available);
    assert!(inventory.topology.entries.is_empty());
    assert_eq!(inventory.health.status, HealthStatus::Degraded);
    assert!(
        inventory.health.ready,
        "optional observability failure does not reject activation"
    );
    assert_eq!(
        inventory.health.reasons,
        ["cache-unavailable", "topology-unavailable"]
    );
}

#[test]
fn saturated_occupancy_ratios_do_not_overflow_or_invent_usage_when_disabled() {
    assert_eq!(health::ratio(u64::MAX, u64::MAX), 1000);
    assert_eq!(health::ratio(u64::MAX, 1), 1000);
    assert_eq!(health::ratio(0, 0), 0);
    assert_eq!(health::ratio(1, 0), 1000);
}
