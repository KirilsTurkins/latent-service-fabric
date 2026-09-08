use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use latent_core::{Metadata, PlatformError};
use latent_node::{NodeTopologyEntry, NodeTopologySource, NodeTopologyWriter, ResourceOwnership};
use latent_scheduler::{CellClass, LocalScheduler};
use latent_wasmtime::{RuntimeResourceSnapshot, WasmtimeBackend};

use crate::config::NodeSettings;
use crate::standalone::transport::{TransportHandle, TransportSnapshot};

pub(in crate::standalone) struct TopologySource {
    limits: Limits,
    backend: Arc<WasmtimeBackend>,
    scheduler: Arc<LocalScheduler>,
    transport: TransportHandle,
    invocation_threads: Arc<AtomicUsize>,
    control_threads: Arc<AtomicUsize>,
}

impl TopologySource {
    pub(in crate::standalone) fn new(
        settings: &NodeSettings,
        backend: Arc<WasmtimeBackend>,
        scheduler: Arc<LocalScheduler>,
        transport: TransportHandle,
        invocation_threads: Arc<AtomicUsize>,
        control_threads: Arc<AtomicUsize>,
    ) -> Self {
        Self {
            limits: Limits {
                // Each runtime permits at most one additional blocking thread.
                invocation_threads: count(settings.runtime_workers).saturating_add(1),
                control_threads: count(settings.control_workers).saturating_add(1),
                connections: count(settings.transport.maximum_connections),
                rpcs: count(settings.transport.maximum_rpcs),
                control_jobs: count(settings.transport.maximum_control_jobs),
                cells: settings
                    .admission
                    .cell_classes
                    .values()
                    .map(|class| u64::from(class.parallelism))
                    .sum(),
                instances: count(backend.maximum_instance_reservations()),
            },
            backend,
            scheduler,
            transport,
            invocation_threads,
            control_threads,
        }
    }
}

impl NodeTopologySource for TopologySource {
    fn snapshot(&self, writer: &mut NodeTopologyWriter<'_>) -> Result<bool, PlatformError> {
        // All five possible classes form a fixed bound, including disabled ones.
        let cell_leases = [
            CellClass::Tiny,
            CellClass::Small,
            CellClass::Standard,
            CellClass::Large,
            CellClass::ExtraLarge,
        ]
        .into_iter()
        .map(|class| u64::from(self.scheduler.observations(class).active_leases))
        .sum();
        let observed = Observed {
            invocation_threads: count(self.invocation_threads.load(Ordering::Acquire)),
            control_threads: count(self.control_threads.load(Ordering::Acquire)),
            transport: self.transport.snapshot(),
            resources: self.backend.resource_snapshot(),
            cell_leases,
            instances: count(self.backend.active_instance_reservations()),
        };
        write_rows(writer, rows(self.limits, observed))
    }
}

fn count(value: usize) -> u64 {
    u64::try_from(value).unwrap_or(u64::MAX)
}

#[derive(Clone, Copy)]
struct Limits {
    invocation_threads: u64,
    control_threads: u64,
    connections: u64,
    rpcs: u64,
    control_jobs: u64,
    cells: u64,
    instances: u64,
}

#[derive(Clone, Copy)]
struct Observed {
    invocation_threads: u64,
    control_threads: u64,
    transport: TransportSnapshot,
    resources: RuntimeResourceSnapshot,
    cell_leases: u64,
    instances: u64,
}

struct Row {
    name: &'static str,
    kind: &'static str,
    ownership: ResourceOwnership,
    configured: u64,
    active: Option<u64>,
}

fn row(
    name: &'static str,
    kind: &'static str,
    ownership: ResourceOwnership,
    configured: u64,
    active: Option<u64>,
) -> Row {
    Row {
        name,
        kind,
        ownership,
        configured,
        active,
    }
}

fn rows(limits: Limits, observed: Observed) -> impl Iterator<Item = Row> {
    node_rows(limits, observed)
        .into_iter()
        .chain(activation_rows(limits, observed))
        .chain(service_rows())
}

fn node_rows(limits: Limits, observed: Observed) -> [Row; 8] {
    use ResourceOwnership::NodeFixed;
    [
        row("standalone-node", "process", NodeFixed, 1, Some(1)),
        row(
            "invocation-runtime",
            "thread",
            NodeFixed,
            limits.invocation_threads,
            Some(observed.invocation_threads),
        ),
        row(
            "control-runtime",
            "thread",
            NodeFixed,
            limits.control_threads,
            Some(observed.control_threads),
        ),
        // Configuration is known, but no OS-thread observation is exposed here.
        row("wasmtime-epoch", "thread", NodeFixed, 1, None),
        // Accepting=false also covers a bound but gated listener. Neither that
        // gate nor a retained transport handle proves the listener is alive.
        row("grpc-listener", "listener", NodeFixed, 1, None),
        row(
            "accepted-connections",
            "connection",
            NodeFixed,
            limits.connections,
            Some(count(observed.transport.active_connections)),
        ),
        row(
            "in-flight-rpcs",
            "rpc",
            NodeFixed,
            limits.rpcs,
            Some(count(observed.transport.active_rpcs)),
        ),
        row(
            "control-jobs",
            "job",
            NodeFixed,
            limits.control_jobs,
            Some(count(observed.transport.active_control_jobs)),
        ),
    ]
}

fn activation_rows(limits: Limits, observed: Observed) -> [Row; 8] {
    use ResourceOwnership::ActivationScoped;
    let resources = observed.resources;
    [
        row(
            "execution-cell-leases",
            "cell",
            ActivationScoped,
            limits.cells,
            Some(observed.cell_leases),
        ),
        row(
            "prepared-instance-reservations",
            "reservation",
            ActivationScoped,
            limits.instances,
            Some(observed.instances),
        ),
        row(
            "guest-invocations",
            "invocation",
            ActivationScoped,
            limits.cells,
            Some(resources.active_invocations),
        ),
        row(
            "guest-stores",
            "store",
            ActivationScoped,
            limits.instances,
            Some(resources.live_stores),
        ),
        row(
            "guest-host-states",
            "host-state",
            ActivationScoped,
            limits.instances,
            Some(resources.live_host_states),
        ),
        row(
            "guest-component-instances",
            "component-instance",
            ActivationScoped,
            limits.instances,
            Some(resources.live_component_instances),
        ),
        row(
            "guest-value-buffers",
            "buffer-group",
            ActivationScoped,
            limits.instances,
            Some(resources.live_temporary_buffers),
        ),
        row(
            "guest-cancellation-probes",
            "probe",
            ActivationScoped,
            limits.instances,
            Some(resources.live_cancellation_probes),
        ),
    ]
}

fn service_rows() -> [Row; 3] {
    use ResourceOwnership::ServiceResident;
    [
        // These are architectural zeros for this standalone composition, not a
        // scan of processes, threads, listeners, deployments, or services.
        row(
            "resident-service-processes",
            "process",
            ServiceResident,
            0,
            Some(0),
        ),
        row(
            "resident-service-threads",
            "thread",
            ServiceResident,
            0,
            Some(0),
        ),
        row(
            "resident-service-listeners",
            "listener",
            ServiceResident,
            0,
            Some(0),
        ),
    ]
}

fn write_rows(
    writer: &mut NodeTopologyWriter<'_>,
    rows: impl IntoIterator<Item = Row>,
) -> Result<bool, PlatformError> {
    for row in rows {
        // Avoid even the bounded row strings when the caller's selection is full.
        if writer.remaining() == 0 {
            return Ok(false);
        }
        let entry = NodeTopologyEntry {
            name: row.name.to_owned(),
            kind: row.kind.to_owned(),
            ownership: row.ownership,
            configured_count: row.configured,
            active_count: row.active,
            attributes: Metadata::new(),
        };
        if !writer.push(&entry)? {
            return Ok(false);
        }
    }
    Ok(true)
}

#[cfg(test)]
mod tests;
