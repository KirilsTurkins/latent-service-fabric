use super::proto;

pub(super) fn deployment() -> proto::Deployment {
    proto::Deployment {
        id: "ship".to_owned(),
        metadata: Some(proto::ObjectMetadata {
            name: "ship".to_owned(),
            tenant: Some("acme".to_owned()),
            namespace: Some("default".to_owned()),
            labels: [("tier".to_owned(), "gold".to_owned())].into(),
            annotations: [("note".to_owned(), "escaped \"value\"\n".to_owned())].into(),
        }),
        service: "echo".to_owned(),
        release_digest: format!("sha256:{}", "a".repeat(64)),
        route_weight: 37,
        grants: vec![proto::CapabilityGrant {
            capability: "latent:log/emitter@0.1.0".to_owned(),
            policy: "logs".to_owned(),
            operations: vec!["write".to_owned()],
            constraints: [("level".to_owned(), "info".to_owned())].into(),
        }],
        resources: Some(proto::ResourceBudget {
            cpu_fuel: 10_000,
            memory_bytes: 65_536,
            wall_time_limit_millis: Some(1000),
            log_bytes: 1024,
            ..proto::ResourceBudget::default()
        }),
        availability: Some(proto::AvailabilityPolicy {
            minimum_cached_copies: 2,
            minimum_zones: 1,
        }),
        placement: Some(proto::PlacementPolicy {
            trust_class: "local".to_owned(),
            architectures: vec!["x86_64".to_owned()],
            regions: vec!["eu".to_owned()],
            zones: vec!["a".to_owned()],
            required_features: vec!["simd".to_owned()],
        }),
        generation: 0,
    }
}
