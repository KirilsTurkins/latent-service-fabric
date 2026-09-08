use super::*;
use crate::standalone::observations::tests::reporter;
use latent_node::EmptyCacheInventorySource;

struct FixedRows;
impl NodeTopologySource for FixedRows {
    fn snapshot(&self, writer: &mut NodeTopologyWriter<'_>) -> Result<bool, PlatformError> {
        write_rows(writer, fixture())
    }
}

fn fixture() -> impl Iterator<Item = Row> {
    rows(
        Limits {
            invocation_threads: 3,
            control_threads: 2,
            connections: 10,
            rpcs: 11,
            control_jobs: 2,
            cells: 4,
            instances: 4,
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
            cell_leases: 3,
            instances: 4,
        },
    )
}

#[test]
fn fixed_topology_distinguishes_measurements_unknowns_and_architectural_zeros() {
    let reporter = reporter(Arc::new(EmptyCacheInventorySource), Arc::new(FixedRows), 32);
    let inventory = reporter.snapshot_now().expect("fixed topology");
    assert!(inventory.topology.available && inventory.topology.complete);
    assert_eq!(inventory.topology.entries.len(), 19);
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
    assert_eq!(
        lookup("grpc-listener").active_count,
        None,
        "gated is not an observed dead listener"
    );
    assert_eq!(lookup("wasmtime-epoch").active_count, None);
    assert_eq!(lookup("accepted-connections").active_count, Some(3));
    assert_eq!(lookup("in-flight-rpcs").active_count, Some(5));
    assert_eq!(lookup("control-jobs").active_count, Some(1));
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
    let reporter = reporter(Arc::new(EmptyCacheInventorySource), Arc::new(FixedRows), 2);
    let inventory = reporter.snapshot_now().expect("bounded partial topology");
    assert_eq!(inventory.topology.entries.len(), 2);
    assert!(inventory.topology.available);
    assert!(!inventory.topology.complete);
    assert!(inventory
        .health
        .reasons
        .iter()
        .any(|reason| reason == "topology-incomplete"));
}
