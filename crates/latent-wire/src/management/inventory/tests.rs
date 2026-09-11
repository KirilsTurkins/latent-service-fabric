use super::super::{proto, ManagementLimits};
use super::*;
use latent_admission::{QuotaLimits, QuotaUsage};
use latent_artifacts::{CacheEntryDescriptor, CacheTier};
use latent_core::{Metadata, NodeId, ReleaseDigest, RouteGeneration};
use latent_node::*;
use prost::Message;

fn fixture() -> NodeInventory {
    NodeInventory {
        node: NodeDescriptor {
            id: NodeId("node-a".to_owned()),
            architecture: "x86_64".to_owned(),
            operating_system: "linux".to_owned(),
            cpu_features: vec!["sse2".to_owned()],
            trust_classes: vec!["local".to_owned()],
            region: Some(String::new()),
            zone: None,
            endpoint: "http://127.0.0.1:1".to_owned(),
            identity: "operator-node".to_owned(),
            attributes: Metadata::from([("owner".to_owned(), "node".to_owned())]),
        },
        cell_capacity: vec![CellClassCapacity {
            class: "small".to_owned(),
            observation_available: true,
            accepting: false,
            total: 4,
            available: 2,
            active: 1,
            quarantined: 1,
            queue_depth: 2,
            queue_capacity: 3,
            queued_tenants: 2,
            rejected: 11,
            cancellations: 12,
            expired: 13,
            granted: 14,
            total_wait_micros: 15,
            max_wait_micros: 16,
            oldest_lease_age_micros: 17,
        }],
        memory_pressure_milli: 81,
        queue_depth: 2,
        route_generation: RouteGeneration(u64::MAX),
        cache_entries: vec![CacheEntryDescriptor {
            key: "prepared".to_owned(),
            release_digest: ReleaseDigest(format!("sha256:{}", "a".repeat(64))),
            tier: CacheTier::MemoryMappedCode,
            size_bytes: 5,
            last_access_unix_millis: 6,
        }],
        observed_at_unix_millis: 999,
        cache_summary: cache_summary(),
        pressure: NodePressureObservation {
            load_available: false,
            load_sample_age_millis: None,
            cpu_pressure_milli: 7,
            memory_pressure_milli: 81,
            queue_pressure_milli: 9,
            cache_pressure_milli: 10,
        },
        health: NodeHealthObservation {
            status: HealthStatus::Degraded,
            ready: false,
            healthy: true,
            reasons: vec!["load-not-current".to_owned()],
            observed_at_unix_millis: 998,
        },
        topology: NodeResourceTopology {
            entries: vec![NodeTopologyEntry {
                name: "runtime".to_owned(),
                kind: "worker".to_owned(),
                ownership: ResourceOwnership::NodeFixed,
                configured_count: 2,
                active_count: None,
                attributes: Metadata::from([("shared".to_owned(), "true".to_owned())]),
            }],
            available: true,
            complete: false,
        },
        quotas: Some(NodeQuotaSummary {
            usage: QuotaUsage {
                active_activations: 1,
                queued_activations: 2,
                reserved_cpu_fuel: 3,
                reserved_memory_bytes: 4,
            },
            limits: QuotaLimits {
                maximum_concurrent_activations: 5,
                maximum_queued_activations: 6,
                maximum_reserved_cpu_fuel: 7,
                maximum_reserved_memory_bytes: 8,
            },
            retained_tenants: 9,
        }),
        retained_bytes: 8192,
    }
}

fn cache_summary() -> NodeCacheSummary {
    NodeCacheSummary {
        available: false,
        entries: 11,
        maximum_entries: 12,
        source_bytes: 13,
        maximum_source_bytes: 14,
        metadata_bytes: 15,
        maximum_metadata_bytes: 16,
        compiled_image_bytes: 17,
        maximum_compiled_image_bytes: 18,
        preparing: 19,
        maximum_concurrent_preparations: 20,
        preparing_source_bytes: 21,
        preparing_metadata_bytes: 22,
        hits: 23,
        misses: u64::MAX,
        evictions: 25,
        invalidations: 26,
    }
}

#[test]
fn every_inventory_field_round_trips_through_protobuf_without_unknown_zero_coercion() {
    let expected = fixture();
    let wire = node_inventory_to_proto(expected.clone()).unwrap();
    let encoded = wire.encode_to_vec();
    let decoded = proto::NodeInventory::decode(encoded.as_slice()).unwrap();
    assert_eq!(node_inventory_from_proto(decoded).unwrap(), expected);
    let mut measured_zero = expected;
    measured_zero.pressure.load_available = true;
    measured_zero.pressure.load_sample_age_millis = Some(0);
    measured_zero.topology.entries[0].active_count = Some(0);
    measured_zero.quotas = None;
    let wire = node_inventory_to_proto(measured_zero.clone()).unwrap();
    assert_eq!(node_inventory_from_proto(wire).unwrap(), measured_zero);
}

#[test]
fn cache_tiers_health_and_ownership_variants_are_lossless() {
    for tier in [
        CacheTier::Metadata,
        CacheTier::RawArtifact,
        CacheTier::AheadOfTime,
        CacheTier::MemoryMappedCode,
        CacheTier::ImportsPrepared,
        CacheTier::Snapshot,
        CacheTier::Fused,
    ] {
        let mut expected = fixture();
        expected.cache_entries[0].tier = tier;
        assert_eq!(
            node_inventory_from_proto(node_inventory_to_proto(expected.clone()).unwrap()).unwrap(),
            expected
        );
    }
    for (health, ownership) in [
        (HealthStatus::Healthy, ResourceOwnership::NodeFixed),
        (HealthStatus::Degraded, ResourceOwnership::ActivationScoped),
        (HealthStatus::Unhealthy, ResourceOwnership::ServiceResident),
    ] {
        let mut expected = fixture();
        expected.health.status = health;
        expected.topology.entries[0].ownership = ownership;
        assert_eq!(
            node_inventory_from_proto(node_inventory_to_proto(expected.clone()).unwrap()).unwrap(),
            expected
        );
    }
}

#[test]
fn missing_required_observations_and_unknown_variants_are_errors() {
    for case in 0..4 {
        let mut wire = node_inventory_to_proto(fixture()).unwrap();
        match case {
            0 => wire.pressure = None,
            1 => wire.health.as_mut().unwrap().status = 999,
            2 => wire.topology.as_mut().unwrap().entries[0].ownership = 999,
            _ => wire.cache_entries[0].tier = "future".to_owned(),
        }
        assert!(node_inventory_from_proto(wire).is_err());
    }
}

#[test]
fn inventory_bounds_reject_large_spare_capacity_before_conversion() {
    let limits = ManagementLimits {
        max_response_bytes: 16 * 1024,
        ..ManagementLimits::default()
    };
    let mut value = fixture();
    validate_inventory(&value, &limits).unwrap();
    value.node.identity = String::with_capacity(32 * 1024);
    value.node.identity.push('x');
    assert_eq!(
        validate_inventory(&value, &limits).unwrap_err().code(),
        tonic::Code::ResourceExhausted
    );
}
