use super::super::{proto, ManagementConversionError};
use latent_admission::{QuotaLimits, QuotaUsage};
use latent_artifacts::{CacheEntryDescriptor, CacheTier};
use latent_core::{NodeId, ReleaseDigest, RouteGeneration};
use latent_node as domain;

type Error = ManagementConversionError;

fn required<T>(value: Option<T>, field: &'static str) -> Result<T, Error> {
    value.ok_or_else(|| Error::new(field, "required field is absent"))
}

pub fn node_inventory_to_proto(
    value: domain::NodeInventory,
) -> Result<proto::NodeInventory, Error> {
    Ok(proto::NodeInventory {
        node: Some(descriptor_to_proto(value.node)),
        cell_capacity: value.cell_capacity.into_iter().map(cell_to_proto).collect(),
        memory_pressure_milli: value.memory_pressure_milli,
        queue_depth: value.queue_depth,
        route_generation: value.route_generation.0,
        cache_entries: value
            .cache_entries
            .into_iter()
            .map(cache_to_proto)
            .collect(),
        observed_at_unix_millis: value.observed_at_unix_millis,
        cache_summary: Some(summary_to_proto(value.cache_summary)),
        pressure: Some(pressure_to_proto(value.pressure)),
        health: Some(health_to_proto(value.health)),
        topology: Some(topology_to_proto(value.topology)),
        quotas: value.quotas.map(quota_to_proto),
        retained_bytes: u64::try_from(value.retained_bytes)
            .map_err(|_| Error::new("retained_bytes", "out of range"))?,
    })
}

pub fn node_inventory_from_proto(
    value: proto::NodeInventory,
) -> Result<domain::NodeInventory, Error> {
    Ok(domain::NodeInventory {
        node: descriptor_from_proto(required(value.node, "node")?),
        cell_capacity: value
            .cell_capacity
            .into_iter()
            .map(cell_from_proto)
            .collect(),
        memory_pressure_milli: value.memory_pressure_milli,
        queue_depth: value.queue_depth,
        route_generation: RouteGeneration(value.route_generation),
        cache_entries: value
            .cache_entries
            .into_iter()
            .map(cache_from_proto)
            .collect::<Result<_, _>>()?,
        observed_at_unix_millis: value.observed_at_unix_millis,
        cache_summary: summary_from_proto(required(value.cache_summary, "cache_summary")?),
        pressure: pressure_from_proto(required(value.pressure, "pressure")?),
        health: health_from_proto(required(value.health, "health")?)?,
        topology: topology_from_proto(required(value.topology, "topology")?)?,
        quotas: value.quotas.map(quota_from_proto).transpose()?,
        retained_bytes: usize::try_from(value.retained_bytes)
            .map_err(|_| Error::new("retained_bytes", "out of range"))?,
    })
}

fn cell_to_proto(value: domain::CellClassCapacity) -> proto::CellCapacity {
    proto::CellCapacity {
        class: value.class,
        observation_available: value.observation_available,
        accepting: value.accepting,
        total: value.total,
        available: value.available,
        active: value.active,
        quarantined: value.quarantined,
        queue_depth: value.queue_depth,
        queue_capacity: value.queue_capacity,
        queued_tenants: value.queued_tenants,
        rejected: value.rejected,
        cancellations: value.cancellations,
        expired: value.expired,
        granted: value.granted,
        total_wait_micros: value.total_wait_micros,
        max_wait_micros: value.max_wait_micros,
        oldest_lease_age_micros: value.oldest_lease_age_micros,
    }
}

fn cell_from_proto(value: proto::CellCapacity) -> domain::CellClassCapacity {
    domain::CellClassCapacity {
        class: value.class,
        observation_available: value.observation_available,
        accepting: value.accepting,
        total: value.total,
        available: value.available,
        active: value.active,
        quarantined: value.quarantined,
        queue_depth: value.queue_depth,
        queue_capacity: value.queue_capacity,
        queued_tenants: value.queued_tenants,
        rejected: value.rejected,
        cancellations: value.cancellations,
        expired: value.expired,
        granted: value.granted,
        total_wait_micros: value.total_wait_micros,
        max_wait_micros: value.max_wait_micros,
        oldest_lease_age_micros: value.oldest_lease_age_micros,
    }
}

fn summary_to_proto(value: domain::NodeCacheSummary) -> proto::NodeCacheSummary {
    proto::NodeCacheSummary {
        available: value.available,
        entries: value.entries,
        maximum_entries: value.maximum_entries,
        source_bytes: value.source_bytes,
        maximum_source_bytes: value.maximum_source_bytes,
        metadata_bytes: value.metadata_bytes,
        maximum_metadata_bytes: value.maximum_metadata_bytes,
        compiled_image_bytes: value.compiled_image_bytes,
        maximum_compiled_image_bytes: value.maximum_compiled_image_bytes,
        preparing: value.preparing,
        maximum_concurrent_preparations: value.maximum_concurrent_preparations,
        preparing_source_bytes: value.preparing_source_bytes,
        preparing_metadata_bytes: value.preparing_metadata_bytes,
        hits: value.hits,
        misses: value.misses,
        evictions: value.evictions,
        invalidations: value.invalidations,
    }
}

fn summary_from_proto(value: proto::NodeCacheSummary) -> domain::NodeCacheSummary {
    domain::NodeCacheSummary {
        available: value.available,
        entries: value.entries,
        maximum_entries: value.maximum_entries,
        source_bytes: value.source_bytes,
        maximum_source_bytes: value.maximum_source_bytes,
        metadata_bytes: value.metadata_bytes,
        maximum_metadata_bytes: value.maximum_metadata_bytes,
        compiled_image_bytes: value.compiled_image_bytes,
        maximum_compiled_image_bytes: value.maximum_compiled_image_bytes,
        preparing: value.preparing,
        maximum_concurrent_preparations: value.maximum_concurrent_preparations,
        preparing_source_bytes: value.preparing_source_bytes,
        preparing_metadata_bytes: value.preparing_metadata_bytes,
        hits: value.hits,
        misses: value.misses,
        evictions: value.evictions,
        invalidations: value.invalidations,
    }
}

fn pressure_to_proto(value: domain::NodePressureObservation) -> proto::NodePressureObservation {
    proto::NodePressureObservation {
        load_available: value.load_available,
        load_sample_age_millis: value.load_sample_age_millis,
        cpu_pressure_milli: value.cpu_pressure_milli,
        memory_pressure_milli: value.memory_pressure_milli,
        queue_pressure_milli: value.queue_pressure_milli,
        cache_pressure_milli: value.cache_pressure_milli,
    }
}

fn pressure_from_proto(value: proto::NodePressureObservation) -> domain::NodePressureObservation {
    domain::NodePressureObservation {
        load_available: value.load_available,
        load_sample_age_millis: value.load_sample_age_millis,
        cpu_pressure_milli: value.cpu_pressure_milli,
        memory_pressure_milli: value.memory_pressure_milli,
        queue_pressure_milli: value.queue_pressure_milli,
        cache_pressure_milli: value.cache_pressure_milli,
    }
}

fn descriptor_to_proto(value: domain::NodeDescriptor) -> proto::NodeDescriptor {
    proto::NodeDescriptor {
        id: value.id.0,
        architecture: value.architecture,
        operating_system: value.operating_system,
        cpu_features: value.cpu_features,
        trust_classes: value.trust_classes,
        region: value.region,
        zone: value.zone,
        endpoint: value.endpoint,
        identity: value.identity,
        attributes: value.attributes.into_iter().collect(),
    }
}
fn descriptor_from_proto(value: proto::NodeDescriptor) -> domain::NodeDescriptor {
    domain::NodeDescriptor {
        id: NodeId(value.id),
        architecture: value.architecture,
        operating_system: value.operating_system,
        cpu_features: value.cpu_features,
        trust_classes: value.trust_classes,
        region: value.region,
        zone: value.zone,
        endpoint: value.endpoint,
        identity: value.identity,
        attributes: value.attributes.into_iter().collect(),
    }
}
fn cache_to_proto(value: CacheEntryDescriptor) -> proto::CacheEntry {
    let tier = match value.tier {
        CacheTier::Metadata => "metadata",
        CacheTier::RawArtifact => "raw-artifact",
        CacheTier::AheadOfTime => "ahead-of-time",
        CacheTier::MemoryMappedCode => "memory-mapped-code",
        CacheTier::ImportsPrepared => "imports-prepared",
        CacheTier::Snapshot => "snapshot",
        CacheTier::Fused => "fused",
    };
    proto::CacheEntry {
        key: value.key,
        release_digest: value.release_digest.0,
        tier: tier.to_owned(),
        size_bytes: value.size_bytes,
        last_access_unix_millis: value.last_access_unix_millis,
    }
}
fn cache_from_proto(value: proto::CacheEntry) -> Result<CacheEntryDescriptor, Error> {
    let tier = match value.tier.as_str() {
        "metadata" => CacheTier::Metadata,
        "raw-artifact" => CacheTier::RawArtifact,
        "ahead-of-time" => CacheTier::AheadOfTime,
        "memory-mapped-code" => CacheTier::MemoryMappedCode,
        "imports-prepared" => CacheTier::ImportsPrepared,
        "snapshot" => CacheTier::Snapshot,
        "fused" => CacheTier::Fused,
        _ => return Err(Error::new("cache_entries.tier", "unknown cache tier")),
    };
    Ok(CacheEntryDescriptor {
        key: value.key,
        release_digest: ReleaseDigest(value.release_digest),
        tier,
        size_bytes: value.size_bytes,
        last_access_unix_millis: value.last_access_unix_millis,
    })
}
fn health_to_proto(value: domain::NodeHealthObservation) -> proto::NodeHealthObservation {
    let status = match value.status {
        domain::HealthStatus::Healthy => proto::NodeHealthStatus::Healthy,
        domain::HealthStatus::Degraded => proto::NodeHealthStatus::Degraded,
        domain::HealthStatus::Unhealthy => proto::NodeHealthStatus::Unhealthy,
    };
    proto::NodeHealthObservation {
        status: status as i32,
        ready: value.ready,
        healthy: value.healthy,
        reasons: value.reasons,
        observed_at_unix_millis: value.observed_at_unix_millis,
    }
}
fn health_from_proto(
    value: proto::NodeHealthObservation,
) -> Result<domain::NodeHealthObservation, Error> {
    let status = match proto::NodeHealthStatus::try_from(value.status) {
        Ok(proto::NodeHealthStatus::Healthy) => domain::HealthStatus::Healthy,
        Ok(proto::NodeHealthStatus::Degraded) => domain::HealthStatus::Degraded,
        Ok(proto::NodeHealthStatus::Unhealthy) => domain::HealthStatus::Unhealthy,
        _ => return Err(Error::new("health.status", "unknown health status")),
    };
    Ok(domain::NodeHealthObservation {
        status,
        ready: value.ready,
        healthy: value.healthy,
        reasons: value.reasons,
        observed_at_unix_millis: value.observed_at_unix_millis,
    })
}
fn topology_to_proto(value: domain::NodeResourceTopology) -> proto::NodeResourceTopology {
    proto::NodeResourceTopology {
        available: value.available,
        complete: value.complete,
        entries: value
            .entries
            .into_iter()
            .map(|entry| {
                let ownership = match entry.ownership {
                    domain::ResourceOwnership::NodeFixed => proto::ResourceOwnership::NodeFixed,
                    domain::ResourceOwnership::ActivationScoped => {
                        proto::ResourceOwnership::ActivationScoped
                    }
                    domain::ResourceOwnership::ServiceResident => {
                        proto::ResourceOwnership::ServiceResident
                    }
                };
                proto::NodeTopologyEntry {
                    name: entry.name,
                    kind: entry.kind,
                    ownership: ownership as i32,
                    configured_count: entry.configured_count,
                    active_count: entry.active_count,
                    attributes: entry.attributes.into_iter().collect(),
                }
            })
            .collect(),
    }
}
fn topology_from_proto(
    value: proto::NodeResourceTopology,
) -> Result<domain::NodeResourceTopology, Error> {
    let entries = value
        .entries
        .into_iter()
        .map(|entry| {
            let ownership = match proto::ResourceOwnership::try_from(entry.ownership) {
                Ok(proto::ResourceOwnership::NodeFixed) => domain::ResourceOwnership::NodeFixed,
                Ok(proto::ResourceOwnership::ActivationScoped) => {
                    domain::ResourceOwnership::ActivationScoped
                }
                Ok(proto::ResourceOwnership::ServiceResident) => {
                    domain::ResourceOwnership::ServiceResident
                }
                _ => {
                    return Err(Error::new(
                        "topology.entries.ownership",
                        "unknown resource ownership",
                    ))
                }
            };
            Ok(domain::NodeTopologyEntry {
                name: entry.name,
                kind: entry.kind,
                ownership,
                configured_count: entry.configured_count,
                active_count: entry.active_count,
                attributes: entry.attributes.into_iter().collect(),
            })
        })
        .collect::<Result<_, Error>>()?;
    Ok(domain::NodeResourceTopology {
        entries,
        available: value.available,
        complete: value.complete,
    })
}
fn quota_to_proto(value: domain::NodeQuotaSummary) -> proto::NodeQuotaSummary {
    proto::NodeQuotaSummary {
        usage: Some(proto::NodeQuotaUsage {
            active_activations: value.usage.active_activations,
            queued_activations: value.usage.queued_activations,
            reserved_cpu_fuel: value.usage.reserved_cpu_fuel,
            reserved_memory_bytes: value.usage.reserved_memory_bytes,
        }),
        limits: Some(proto::NodeQuotaLimits {
            maximum_concurrent_activations: value.limits.maximum_concurrent_activations,
            maximum_queued_activations: value.limits.maximum_queued_activations,
            maximum_reserved_cpu_fuel: value.limits.maximum_reserved_cpu_fuel,
            maximum_reserved_memory_bytes: value.limits.maximum_reserved_memory_bytes,
        }),
        retained_tenants: value.retained_tenants,
    }
}
fn quota_from_proto(value: proto::NodeQuotaSummary) -> Result<domain::NodeQuotaSummary, Error> {
    let usage = required(value.usage, "quotas.usage")?;
    let limits = required(value.limits, "quotas.limits")?;
    Ok(domain::NodeQuotaSummary {
        usage: QuotaUsage {
            active_activations: usage.active_activations,
            queued_activations: usage.queued_activations,
            reserved_cpu_fuel: usage.reserved_cpu_fuel,
            reserved_memory_bytes: usage.reserved_memory_bytes,
        },
        limits: QuotaLimits {
            maximum_concurrent_activations: limits.maximum_concurrent_activations,
            maximum_queued_activations: limits.maximum_queued_activations,
            maximum_reserved_cpu_fuel: limits.maximum_reserved_cpu_fuel,
            maximum_reserved_memory_bytes: limits.maximum_reserved_memory_bytes,
        },
        retained_tenants: value.retained_tenants,
    })
}
