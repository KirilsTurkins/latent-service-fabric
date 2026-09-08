use latent_wire::management::proto;

use super::{bounds, node};

fn fixture() -> proto::NodeInventory {
    proto::NodeInventory {
        node: Some(proto::NodeDescriptor {
            id: "node-a".to_owned(),
            architecture: "x86_64".to_owned(),
            operating_system: "linux".to_owned(),
            cpu_features: vec!["sse2".to_owned()],
            trust_classes: vec!["internal".to_owned()],
            region: Some(String::new()),
            zone: None,
            endpoint: "http://127.0.0.1:1234".to_owned(),
            identity: "local".to_owned(),
            attributes: [("quote".to_owned(), "line\nvalue".to_owned())].into(),
        }),
        cell_capacity: vec![proto::CellCapacity {
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
        route_generation: u64::MAX,
        cache_entries: vec![proto::CacheEntry {
            key: "prepared".to_owned(),
            release_digest: format!("sha256:{}", "a".repeat(64)),
            tier: "memory-mapped-code".to_owned(),
            size_bytes: 5,
            last_access_unix_millis: 6,
        }],
        observed_at_unix_millis: 999,
        cache_summary: Some(proto::NodeCacheSummary {
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
        }),
        pressure: Some(proto::NodePressureObservation {
            load_available: false,
            load_sample_age_millis: None,
            cpu_pressure_milli: 7,
            memory_pressure_milli: 81,
            queue_pressure_milli: 9,
            cache_pressure_milli: 10,
        }),
        health: Some(proto::NodeHealthObservation {
            status: proto::NodeHealthStatus::Degraded as i32,
            ready: false,
            healthy: true,
            reasons: vec!["load-not-current".to_owned()],
            observed_at_unix_millis: 998,
        }),
        topology: Some(proto::NodeResourceTopology {
            available: true,
            complete: false,
            entries: vec![proto::NodeTopologyEntry {
                name: "runtime".to_owned(),
                kind: "worker".to_owned(),
                ownership: proto::ResourceOwnership::NodeFixed as i32,
                configured_count: 2,
                active_count: None,
                attributes: [("shared".to_owned(), "true".to_owned())].into(),
            }],
        }),
        quotas: Some(quota_fixture()),
        retained_bytes: 8192,
    }
}

fn quota_fixture() -> proto::NodeQuotaSummary {
    proto::NodeQuotaSummary {
        usage: Some(proto::NodeQuotaUsage {
            active_activations: 1,
            queued_activations: 2,
            reserved_cpu_fuel: 3,
            reserved_memory_bytes: 4,
        }),
        limits: Some(proto::NodeQuotaLimits {
            maximum_concurrent_activations: 5,
            maximum_queued_activations: 6,
            maximum_reserved_cpu_fuel: 7,
            maximum_reserved_memory_bytes: 8,
        }),
        retained_tenants: 9,
    }
}

#[test]
fn inventory_preserves_every_counter_family_and_unknown_vs_measured_zero() {
    let expected = fixture();
    bounds::checked(&expected, 4096).unwrap();
    let value = node::inventory(expected).unwrap();
    assert_eq!(value["routeGeneration"], u64::MAX.to_string());
    assert_eq!(value["queueDepth"], "2");
    assert_eq!(value["observedAtUnixMillis"], "999");
    assert_eq!(value["retainedBytes"], "8192");
    assert_eq!(value["node"]["region"], "");
    assert_eq!(value["node"]["zone"], serde_json::Value::Null);
    assert_eq!(value["health"]["status"], "degraded");
    assert_eq!(value["health"]["observedAtUnixMillis"], "998");
    assert_eq!(value["cellCapacity"][0]["queueCapacity"], 3);
    assert_eq!(value["cellCapacity"][0]["oldestLeaseAgeMicros"], "17");
    assert_eq!(value["cellCapacity"][0]["accepting"], false);
    assert_eq!(value["cacheEntries"][0]["lastAccessUnixMillis"], "6");
    assert_eq!(
        value["pressure"]["loadSampleAgeMillis"],
        serde_json::Value::Null
    );
    assert_eq!(
        value["topology"]["entries"][0]["activeCount"],
        serde_json::Value::Null
    );
    assert_eq!(value["topology"]["complete"], false);
    assert_eq!(value["quotas"]["usage"]["reservedMemoryBytes"], "4");
    assert_eq!(value["quotas"]["limits"]["maximumReservedCpuFuel"], "7");
    assert_eq!(value["quotas"]["retainedTenants"], "9");
    for (name, expected) in [
        ("entries", 11),
        ("maximumEntries", 12),
        ("sourceBytes", 13),
        ("maximumSourceBytes", 14),
        ("metadataBytes", 15),
        ("maximumMetadataBytes", 16),
        ("compiledImageBytes", 17),
        ("maximumCompiledImageBytes", 18),
        ("preparing", 19),
        ("maximumConcurrentPreparations", 20),
        ("preparingSourceBytes", 21),
        ("preparingMetadataBytes", 22),
        ("hits", 23),
        ("misses", u64::MAX),
        ("evictions", 25),
        ("invalidations", 26),
    ] {
        assert_eq!(value["cacheSummary"][name], expected.to_string());
    }
    let mut measured = fixture();
    measured.pressure.as_mut().unwrap().load_sample_age_millis = Some(0);
    measured.topology.as_mut().unwrap().entries[0].active_count = Some(0);
    measured.quotas = None;
    let value = node::inventory(measured).unwrap();
    assert_eq!(value["pressure"]["loadSampleAgeMillis"], "0");
    assert_eq!(value["topology"]["entries"][0]["activeCount"], "0");
    assert_eq!(value["quotas"], serde_json::Value::Null);
}

#[test]
fn unknown_inventory_enum_and_incomplete_required_fields_are_protocol_failures() {
    let mut value = fixture();
    value.health.as_mut().unwrap().status = 987;
    assert!(node::inventory(value).is_err());
    let mut value = fixture();
    value.topology.as_mut().unwrap().entries[0].ownership = 0;
    assert!(node::inventory(value).is_err());
    let mut value = fixture();
    value.cache_entries[0].tier = "unknown".to_owned();
    assert!(node::inventory(value).is_err());
    let mut value = fixture();
    value.quotas.as_mut().unwrap().usage = None;
    assert!(node::inventory(value).is_err());
    let mut value = fixture();
    value.cache_summary = None;
    assert!(node::inventory(value).is_err());
}
