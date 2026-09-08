use latent_wire::management::{node_inventory_from_proto, node_inventory_to_proto, proto};
use serde_json::{json, Value};

use crate::error::Failure;

use super::invalid_response;

pub(super) fn inventory(value: proto::NodeInventory) -> Result<Value, Failure> {
    // Consume the bounded message through the shared lossless converter. This
    // checks required fields and enum vocabulary without cloning the inventory.
    let domain = node_inventory_from_proto(value).map_err(|_| invalid_response())?;
    let value = node_inventory_to_proto(domain).map_err(|_| invalid_response())?;
    let node = value.node.ok_or_else(invalid_response)?;
    let health = value.health.ok_or_else(invalid_response)?;
    let pressure = value.pressure.ok_or_else(invalid_response)?;
    let topology = value.topology.ok_or_else(invalid_response)?;
    let status = match proto::NodeHealthStatus::try_from(health.status) {
        Ok(proto::NodeHealthStatus::Healthy) => "healthy",
        Ok(proto::NodeHealthStatus::Degraded) => "degraded",
        Ok(proto::NodeHealthStatus::Unhealthy) => "unhealthy",
        _ => return Err(invalid_response()),
    };
    let cells = value.cell_capacity.iter().map(cell).collect::<Vec<_>>();
    let cache_entries = value.cache_entries.into_iter().map(|entry| json!({
        "key":entry.key,"releaseDigest":entry.release_digest,"tier":entry.tier,
        "sizeBytes":entry.size_bytes.to_string(),"lastAccessUnixMillis":entry.last_access_unix_millis.to_string(),
    })).collect::<Vec<_>>();
    let topology_entries = topology
        .entries
        .iter()
        .map(topology_entry)
        .collect::<Result<Vec<_>, _>>()?;
    Ok(json!({
        "node":{
            "id":node.id,"architecture":node.architecture,"operatingSystem":node.operating_system,
            "cpuFeatures":node.cpu_features,"trustClasses":node.trust_classes,"region":node.region,"zone":node.zone,
            "endpoint":node.endpoint,"identity":node.identity,"attributes":node.attributes,
        },
        "cellCapacity":cells,"memoryPressureMilli":value.memory_pressure_milli,
        "queueDepth":value.queue_depth.to_string(),"routeGeneration":value.route_generation.to_string(),
        "cacheEntries":cache_entries,"observedAtUnixMillis":value.observed_at_unix_millis.to_string(),
        "cacheSummary":cache_summary(value.cache_summary.ok_or_else(invalid_response)?),
        "pressure":{
            "loadAvailable":pressure.load_available,"loadSampleAgeMillis":pressure.load_sample_age_millis.map(|v|v.to_string()),
            "cpuPressureMilli":pressure.cpu_pressure_milli,"memoryPressureMilli":pressure.memory_pressure_milli,
            "queuePressureMilli":pressure.queue_pressure_milli,"cachePressureMilli":pressure.cache_pressure_milli,
        },
        "health":{
            "status":status,"ready":health.ready,"healthy":health.healthy,"reasons":health.reasons,
            "observedAtUnixMillis":health.observed_at_unix_millis.to_string(),
        },
        "topology":{"available":topology.available,"complete":topology.complete,"entries":topology_entries},
        "quotas":value.quotas.map(quotas).transpose()?,"retainedBytes":value.retained_bytes.to_string(),
    }))
}

fn cell(value: &proto::CellCapacity) -> Value {
    json!({
        "class":value.class,"observationAvailable":value.observation_available,"accepting":value.accepting,
        "total":value.total,"available":value.available,"active":value.active,"quarantined":value.quarantined,
        "queueDepth":value.queue_depth,"queueCapacity":value.queue_capacity,"queuedTenants":value.queued_tenants,
        "rejected":value.rejected.to_string(),"cancellations":value.cancellations.to_string(),"expired":value.expired.to_string(),
        "granted":value.granted.to_string(),"totalWaitMicros":value.total_wait_micros.to_string(),
        "maxWaitMicros":value.max_wait_micros.to_string(),"oldestLeaseAgeMicros":value.oldest_lease_age_micros.to_string(),
    })
}

fn cache_summary(value: proto::NodeCacheSummary) -> Value {
    json!({
        "available":value.available,"entries":value.entries.to_string(),"maximumEntries":value.maximum_entries.to_string(),
        "sourceBytes":value.source_bytes.to_string(),"maximumSourceBytes":value.maximum_source_bytes.to_string(),
        "metadataBytes":value.metadata_bytes.to_string(),"maximumMetadataBytes":value.maximum_metadata_bytes.to_string(),
        "compiledImageBytes":value.compiled_image_bytes.to_string(),"maximumCompiledImageBytes":value.maximum_compiled_image_bytes.to_string(),
        "preparing":value.preparing.to_string(),"maximumConcurrentPreparations":value.maximum_concurrent_preparations.to_string(),
        "preparingSourceBytes":value.preparing_source_bytes.to_string(),"preparingMetadataBytes":value.preparing_metadata_bytes.to_string(),
        "hits":value.hits.to_string(),"misses":value.misses.to_string(),"evictions":value.evictions.to_string(),"invalidations":value.invalidations.to_string(),
    })
}

fn topology_entry(value: &proto::NodeTopologyEntry) -> Result<Value, Failure> {
    let ownership = match proto::ResourceOwnership::try_from(value.ownership) {
        Ok(proto::ResourceOwnership::NodeFixed) => "node-fixed",
        Ok(proto::ResourceOwnership::ActivationScoped) => "activation-scoped",
        Ok(proto::ResourceOwnership::ServiceResident) => "service-resident",
        _ => return Err(invalid_response()),
    };
    Ok(json!({
        "name":value.name,"kind":value.kind,"ownership":ownership,"configuredCount":value.configured_count.to_string(),
        "activeCount":value.active_count.map(|v|v.to_string()),"attributes":value.attributes,
    }))
}

fn quotas(value: proto::NodeQuotaSummary) -> Result<Value, Failure> {
    let usage = value.usage.ok_or_else(invalid_response)?;
    let limits = value.limits.ok_or_else(invalid_response)?;
    Ok(json!({
        "usage":{
            "activeActivations":usage.active_activations,"queuedActivations":usage.queued_activations,
            "reservedCpuFuel":usage.reserved_cpu_fuel.to_string(),"reservedMemoryBytes":usage.reserved_memory_bytes.to_string(),
        },
        "limits":{
            "maximumConcurrentActivations":limits.maximum_concurrent_activations,"maximumQueuedActivations":limits.maximum_queued_activations,
            "maximumReservedCpuFuel":limits.maximum_reserved_cpu_fuel.to_string(),"maximumReservedMemoryBytes":limits.maximum_reserved_memory_bytes.to_string(),
        },
        "retainedTenants":value.retained_tenants.to_string(),
    }))
}
