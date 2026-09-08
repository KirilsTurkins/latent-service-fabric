use latent_node::{NodeInventory, ResourceOwnership};
use serde_json::{json, Value};

pub(in super::super) fn inventory(value: &NodeInventory) -> Value {
    let cache = value.cache_summary;
    let cells: Vec<_> = value.cell_capacity.iter().map(|cell| json!({"class":cell.class,"total":cell.total,
        "available":cell.available,"active":cell.active,"quarantined":cell.quarantined,"queueDepth":cell.queue_depth,
        "queuedTenants":cell.queued_tenants,"queueCapacity":cell.queue_capacity,"accepting":cell.accepting,
        "granted":cell.granted.to_string(),"rejected":cell.rejected.to_string(),"cancellations":cell.cancellations.to_string(),
        "expired":cell.expired.to_string(),"totalWaitMicros":cell.total_wait_micros.to_string(),"maxWaitMicros":cell.max_wait_micros.to_string()})).collect();
    let topology: Vec<_> = value.topology.entries.iter().map(|entry| json!({"name":entry.name,"kind":entry.kind,
        "ownership":match entry.ownership { ResourceOwnership::NodeFixed=>"node-fixed",ResourceOwnership::ActivationScoped=>"activation-scoped",ResourceOwnership::ServiceResident=>"service-resident" },
        "configuredCount":entry.configured_count.to_string(),"activeCount":entry.active_count.map(|count|count.to_string()),"attributes":entry.attributes})).collect();
    json!({"nodeId":value.node.id.0,"observedAtUnixMillis":value.observed_at_unix_millis.to_string(),
        "queueDepth":value.queue_depth.to_string(),"routeGeneration":value.route_generation.0.to_string(),"cellCapacity":cells,
        "ready":value.health.ready,"healthy":value.health.healthy,
        "cacheSummary":{"available":cache.available,"entries":cache.entries.to_string(),"maximumEntries":cache.maximum_entries.to_string(),
            "sourceBytes":cache.source_bytes.to_string(),"maximumSourceBytes":cache.maximum_source_bytes.to_string(),
            "metadataBytes":cache.metadata_bytes.to_string(),"maximumMetadataBytes":cache.maximum_metadata_bytes.to_string(),
            "compiledImageBytes":cache.compiled_image_bytes.to_string(),"maximumCompiledImageBytes":cache.maximum_compiled_image_bytes.to_string(),
            "preparing":cache.preparing.to_string(),"maximumConcurrentPreparations":cache.maximum_concurrent_preparations.to_string(),
            "preparingSourceBytes":cache.preparing_source_bytes.to_string(),"preparingMetadataBytes":cache.preparing_metadata_bytes.to_string(),
            "hits":cache.hits.to_string(),"misses":cache.misses.to_string(),"evictions":cache.evictions.to_string(),"invalidations":cache.invalidations.to_string()},
        "quotas":value.quotas.map(|quota|json!({"retainedTenants":quota.retained_tenants.to_string(),"usage":{
            "activeActivations":quota.usage.active_activations,"queuedActivations":quota.usage.queued_activations,
            "reservedCpuFuel":quota.usage.reserved_cpu_fuel.to_string(),"reservedMemoryBytes":quota.usage.reserved_memory_bytes.to_string()}})),
        "topology":{"available":value.topology.available,"complete":value.topology.complete,"entries":topology}})
}

pub(in super::super) fn backend(value: latent_wasmtime::RuntimeResourceSnapshot) -> Value {
    json!({"active_invocations":value.active_invocations.to_string(),"live_stores":value.live_stores.to_string(),
        "live_host_states":value.live_host_states.to_string(),"live_component_instances":value.live_component_instances.to_string(),
        "live_temporary_buffers":value.live_temporary_buffers.to_string(),"live_cancellation_probes":value.live_cancellation_probes.to_string(),
        "stores_created":value.stores_created.to_string()})
}

pub(in super::super) fn ownership(
    node: &crate::standalone::StandaloneNode,
    journal_config: latent_node::LocalActivationJournalConfig,
    maximum_active_correlations: usize,
) -> Value {
    let cancellation = node.manager.cancellation_snapshot();
    let journal = node.manager.journal().snapshot();
    let observer = node.observer.snapshot();
    let sink = node.sink.snapshot();
    let pipeline = node.telemetry.snapshot();
    json!({
        "cancellation":{"active_registrations":cancellation.active_registrations.to_string()},
        "journal":{
            "active":journal.active.to_string(),"terminal":journal.terminal.to_string(),
            "reserved_bytes":journal.reserved_bytes.to_string(),"retained_bytes":journal.retained_bytes.to_string(),
            "evicted":journal.evicted.to_string(),"begun":journal.begun.to_string(),"completed":journal.completed.to_string(),
            "maximum_active":journal_config.maximum_active.to_string(),"maximum_terminal":journal_config.maximum_terminal.to_string(),
            "maximum_record_bytes":journal_config.maximum_record_bytes.to_string(),"maximum_retained_bytes":journal_config.maximum_retained_bytes.to_string()},
        "observer":{
            "active_correlations":observer.active_correlations.to_string(),"maximum_active_correlations":maximum_active_correlations.to_string(),
            "received":observer.received.to_string(),"completed":observer.completed.to_string(),"guest_logs":observer.guest_logs.to_string(),
            "observations_dropped":observer.observations_dropped.to_string(),"capacity_drops":observer.capacity_drops.to_string(),
            "invalid_records":observer.invalid_records.to_string(),"unknown_correlations":observer.unknown_correlations.to_string(),
            "submission_errors":observer.submission_errors.to_string(),"panics":observer.panics.to_string()},
        "sink":{
            "entries":sink.entries.to_string(),"retained_bytes":sink.retained_bytes.to_string(),
            "maximum_entries":sink.maximum_entries.to_string(),"maximum_bytes":sink.maximum_bytes.to_string(),
            "evicted_entries":sink.evicted_entries.to_string(),"dropped_oversized":sink.dropped_oversized.to_string()},
        "pipeline":{
            "queue_depth":pipeline.queue_depth.to_string(),"queue_capacity":pipeline.queue_capacity.to_string(),
            "accepted":pipeline.accepted.to_string(),"exported":pipeline.exported.to_string(),
            "dropped_queue_full":pipeline.dropped_queue_full.to_string(),"dropped_queue_closed":pipeline.dropped_queue_closed.to_string(),
            "dropped_invalid_record":pipeline.dropped_invalid_record.to_string(),"sink_failures":pipeline.sink_failures.to_string(),
            "sink_timeouts":pipeline.sink_timeouts.to_string(),"flush_timeouts":pipeline.flush_timeouts.to_string(),
            "shutdown_timeouts":pipeline.shutdown_timeouts.to_string(),"worker_panics":pipeline.worker_panics.to_string()}
    })
}
