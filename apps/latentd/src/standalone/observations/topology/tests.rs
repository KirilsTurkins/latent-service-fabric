use super::*;
use crate::standalone::observations::tests::reporter;
use latent_node::EmptyCacheInventorySource;

struct FixedRows(u64);
impl NodeTopologySource for FixedRows {
    fn snapshot(&self, writer: &mut NodeTopologyWriter<'_>) -> Result<bool, PlatformError> {
        write_rows(writer, fixture(self.0))
    }
}

fn fixture(compiler_workers_live: u64) -> impl Iterator<Item = Row> {
    rows(
        Limits {
            invocation_threads: 3,
            control_threads: 2,
            invocation_stack_bytes: 3 * count(crate::worker_stacks::THREAD_MAPPING_ALLOWANCE),
            control_stack_bytes: 2 * count(crate::worker_stacks::THREAD_MAPPING_ALLOWANCE),
            connections: 10,
            rpcs: 11,
            control_jobs: 2,
            cells: 4,
            instances: 4,
            cleanup_slots: 68,
            canary: None,
        },
        Observed {
            invocation_threads: 2,
            control_threads: 1,
            transport: TransportSnapshot {
                accepting: false,
                active_connections: 3,
                active_rpcs: 5,
                active_control_jobs: 1,
                ..TransportSnapshot::default()
            },
            resources: RuntimeResourceSnapshot {
                active_invocations: 2,
                live_stores: 1,
                live_host_states: 1,
                live_component_instances: 1,
                live_temporary_buffers: 2,
                live_cancellation_probes: 2,
                stores_created: 100_000,
            },
            compiler_maximum_workers: 4,
            compiler_workers_live,
            cell_leases: 3,
            instances: 4,
            cleanup_driver_alive: 1,
            cleanup_slots: 6,
        },
    )
}

#[test]
fn fixed_topology_distinguishes_measurements_unknowns_and_architectural_zeros() {
    let reporter = reporter(
        Arc::new(EmptyCacheInventorySource),
        Arc::new(FixedRows(2)),
        24,
    );
    let inventory = reporter.snapshot_now().expect("fixed topology");
    assert!(inventory.topology.available && inventory.topology.complete);
    assert_eq!(inventory.topology.entries.len(), 24);
    let lookup = |name: &str| {
        inventory
            .topology
            .entries
            .iter()
            .find(|row| row.name == name)
            .expect("named row")
    };
    assert_eq!(
        (
            lookup("standalone-node").configured_count,
            lookup("standalone-node").active_count
        ),
        (1, Some(1))
    );
    assert_eq!(
        (
            lookup("invocation-runtime").configured_count,
            lookup("invocation-runtime").active_count
        ),
        (3, Some(2))
    );
    assert_eq!(
        (
            lookup("control-runtime").configured_count,
            lookup("control-runtime").active_count
        ),
        (2, Some(1))
    );
    let stack = lookup("control-runtime-stack");
    assert_eq!(stack.kind, "byte");
    assert_eq!(stack.ownership, ResourceOwnership::NodeFixed);
    assert_eq!(
        (stack.configured_count, stack.active_count),
        (
            2 * count(crate::worker_stacks::THREAD_MAPPING_ALLOWANCE),
            Some(count(crate::worker_stacks::THREAD_MAPPING_ALLOWANCE))
        )
    );
    assert_eq!(
        lookup("grpc-listener").active_count,
        None,
        "gated is not an observed dead listener"
    );
    assert_eq!(lookup("wasmtime-epoch").active_count, None);
    let compiler = lookup("wasmtime-compiler");
    assert_eq!(compiler.kind, "thread");
    assert_eq!(compiler.ownership, ResourceOwnership::NodeFixed);
    assert_eq!(
        (compiler.configured_count, compiler.active_count),
        (4, Some(2)),
        "idle live workers count independently of compiler jobs"
    );
    assert_eq!(lookup("accepted-connections").active_count, Some(3));
    assert_eq!(lookup("in-flight-rpcs").active_count, Some(5));
    assert_eq!(lookup("control-jobs").active_count, Some(1));
    assert_eq!(lookup("invocation-cleanup-driver").active_count, Some(1));
    assert_eq!(lookup("invocation-cleanup-slots").configured_count, 68);
    assert_eq!(lookup("invocation-cleanup-slots").active_count, Some(6));
    assert_eq!(lookup("execution-cell-leases").active_count, Some(3));
    assert_eq!(
        lookup("prepared-instance-reservations").active_count,
        Some(4)
    );
    assert_eq!(
        lookup("guest-stores").active_count,
        Some(1),
        "lifetime stores-created is not current occupancy"
    );
    for row in inventory
        .topology
        .entries
        .iter()
        .filter(|row| row.ownership == ResourceOwnership::ServiceResident)
    {
        assert_eq!((row.configured_count, row.active_count), (0, Some(0)));
    }
    assert!(inventory.retained_bytes <= 256 * 1024);
}

#[test]
fn short_topology_selection_is_bounded_and_explicitly_incomplete() {
    for maximum_rows in [2, 21] {
        let reporter = reporter(
            Arc::new(EmptyCacheInventorySource),
            Arc::new(FixedRows(2)),
            maximum_rows,
        );
        let inventory = reporter.snapshot_now().expect("bounded partial topology");
        assert_eq!(inventory.topology.entries.len(), maximum_rows);
        assert!(inventory.topology.available);
        assert!(!inventory.topology.complete);
        assert!(inventory
            .health
            .reasons
            .iter()
            .any(|reason| reason == "topology-incomplete"));
    }
}

#[test]
fn retired_compiler_workers_report_observed_zero_with_configuration_retained() {
    let reporter = reporter(
        Arc::new(EmptyCacheInventorySource),
        Arc::new(FixedRows(0)),
        24,
    );
    let inventory = reporter.snapshot_now().expect("retired worker topology");
    let compiler = inventory
        .topology
        .entries
        .iter()
        .find(|row| row.name == "wasmtime-compiler")
        .expect("compiler topology");
    assert_eq!(
        (compiler.configured_count, compiler.active_count),
        (4, Some(0)),
        "retired workers leave an observed zero, not an unavailable count"
    );
    assert!(inventory.topology.available && inventory.topology.complete);
}

struct AllOptionalRows {
    catalog: Arc<latent_artifacts::DirectoryArtifactRepository>,
    http: bool,
}

impl NodeTopologySource for AllOptionalRows {
    fn snapshot(&self, writer: &mut NodeTopologyWriter<'_>) -> Result<bool, PlatformError> {
        let entries: [NodeTopologyEntry; capacity::CATALOG_ROWS] = [catalog::entry(&self.catalog)];
        for entry in entries {
            if !writer.push(&entry)? {
                return Ok(false);
            }
        }
        if self.http && !write_rows(writer, optional::http_rows(http_snapshot()))? {
            return Ok(false);
        }
        if !write_rows(writer, fixture(2))?
            || !write_rows(writer, optional::policy_rows(2, 1, 8, 3))?
            || !write_rows(
                writer,
                optional::rollout_rows(
                    4,
                    latent_rollout::CoordinatorSnapshot {
                        worker_live: true,
                        queued_commands: 2,
                        active_commands: 1,
                        ..latent_rollout::CoordinatorSnapshot::default()
                    },
                ),
            )?
        {
            return Ok(false);
        }
        write_rows(
            writer,
            optional::canary_rows(
                latent_telemetry::Phase2CanaryOutcomeWindowConfig::default(),
                latent_telemetry::Phase2CanaryWindowSnapshot {
                    tracked_series: 2,
                    total_samples: 3,
                    live_samples: 1,
                    snapshot_owners: 1,
                    ..latent_telemetry::Phase2CanaryWindowSnapshot::default()
                },
            ),
        )
    }
}

fn http_snapshot() -> crate::standalone::http::HttpSnapshot {
    crate::standalone::http::HttpSnapshot {
        listener_alive: true,
        owner_alive: true,
        joined: false,
        failed: false,
        accepting: true,
        maximum_connections: 4,
        connections: 1,
        maximum_exchanges: 8,
        exchanges: 2,
        maximum_buffer_bytes: 4096,
        reserved_buffer_bytes: 128,
        assets: None,
        response_cache_entries: 0,
        response_cache_owners: 0,
        response_cache_reserved_bytes: 0,
    }
}

#[test]
fn standalone_capacity_covers_every_optional_topology_row() {
    let directory = tempfile::TempDir::new().expect("owned empty catalog");
    let catalog = latent_artifacts::DirectoryArtifactRepository::open(
        directory.path().join("catalog"),
        latent_artifacts::DirectoryArtifactRepositoryConfig::default(),
    )
    .expect("bounded catalog");
    let catalog = Arc::new(catalog);
    for (http, expected) in [(false, 33), (true, 38)] {
        let source = Arc::new(AllOptionalRows {
            catalog: catalog.clone(),
            http,
        });
        let old = reporter(
            Arc::new(EmptyCacheInventorySource),
            source.clone(),
            latent_node::StandaloneInventoryConfig::default().maximum_topology_entries,
        )
        .snapshot_now()
        .expect("bounded old selection");
        assert_eq!(old.topology.entries.len(), 32);
        assert!(old.topology.available && !old.topology.complete);
        if !http {
            assert_eq!(
                old.topology.entries.last().unwrap().name,
                "canary-live-samples"
            );
        }
        assert!(old
            .health
            .reasons
            .iter()
            .any(|v| v == "topology-incomplete"));

        let current = reporter(
            Arc::new(EmptyCacheInventorySource),
            source,
            capacity::MAXIMUM_ENTRIES,
        )
        .snapshot_now()
        .expect("all fixed standalone rows");
        assert_eq!(capacity::MAXIMUM_ENTRIES, 38);
        assert!(current.topology.available && current.topology.complete);
        assert_eq!(current.topology.entries.len(), expected);
        let names: std::collections::BTreeSet<_> = current
            .topology
            .entries
            .iter()
            .map(|entry| entry.name.as_str())
            .collect();
        assert_eq!(names.len(), expected, "every fixed row is distinct");
        assert!(names.contains("publication-catalog"));
        assert_eq!(names.contains("http-buffer-reservations"), http);
        assert!(names.contains("invocation-runtime-stack"));
        assert!(names.contains("control-runtime-stack"));
        assert!(names.contains("capability-policy-read-owners"));
        assert!(names.contains("rollout-control-commands"));
        let last = current.topology.entries.last().expect("last optional row");
        assert_eq!(last.name, "canary-snapshot-owners");
        assert_eq!((last.configured_count, last.active_count), (4, Some(1)));
        assert!(current.retained_bytes <= 256 * 1024);
        assert!(!current
            .health
            .reasons
            .iter()
            .any(|v| v == "topology-incomplete"));
        println!(
            "TOPOLOGY_CAPACITY http={http} old=32 old_complete=false selected=38 rows={expected} complete=true retained={} cap=262144",
            current.retained_bytes
        );
    }
}

#[test]
fn standalone_topology_precharges_exact_selected_vec_capacity() {
    let snapshot = |maximum_rows| {
        reporter(
            Arc::new(EmptyCacheInventorySource),
            Arc::new(latent_node::EmptyNodeTopologySource),
            maximum_rows,
        )
        .snapshot_now()
        .expect("empty source still prepays all selected row slots")
    };
    let old = snapshot(32);
    let current = snapshot(capacity::MAXIMUM_ENTRIES);
    assert!(current.topology.available && current.topology.complete);
    assert!(old.topology.entries.is_empty() && current.topology.entries.is_empty());
    assert_eq!(old.topology.entries.capacity(), 32);
    assert_eq!(current.topology.entries.capacity(), 38);
    let extra = 6 * std::mem::size_of::<NodeTopologyEntry>();
    assert_eq!(current.retained_bytes - old.retained_bytes, extra);
    assert!(current.retained_bytes <= 256 * 1024);
    println!(
        "TOPOLOGY_PRECHARGE extra_slots=6 slot_bytes={} extra_bytes={extra} cap=262144",
        std::mem::size_of::<NodeTopologyEntry>()
    );
}
