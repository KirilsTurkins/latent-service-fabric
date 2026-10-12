use super::*;
use crate::NatsEndpoint;
use serde_json::json;

fn setup() -> (NatsConfig, JetStreamQualification, serde_json::Value) {
    let config = NatsConfig {
        format_version: 1,
        endpoint: NatsEndpoint {
            server_name: "localhost".into(),
            peer: "127.0.0.1:4222".parse().unwrap(),
            allow_non_public_peer: true,
        },
        public_roots: true,
        extra_roots: vec![],
        topics: vec![TopicMapping {
            tenant: "a".into(),
            topic: "orders".into(),
            subject: "orders.new".into(),
            stream: "ORDERS".into(),
            duplicate_window_millis: 30_000,
        }],
        idempotency_namespace: "orders".into(),
        maximum_payload_bytes: 4096,
        timeout_millis: 1000,
    };
    let qualification = JetStreamQualification {
        format_version: 1,
        server_version: "2.14.6".into(),
        stream_created: "2026-10-01T00:00:00.123Z".into(),
        maximum_messages: 64,
        maximum_bytes: 1_048_576,
        maximum_age_millis: 0,
        maximum_message_bytes: 65_536,
    };
    let response = json!({
        "type": "io.nats.jetstream.api.v1.stream_info_response", "created": qualification.stream_created,
        "config": {"name":"ORDERS", "subjects":["orders.new"], "storage":"file", "retention":"limits", "discard":"new", "num_replicas":1,
            "max_msgs":64, "max_bytes":1_048_576, "max_age":0, "max_msg_size":65_536, "duplicate_window":30_000_000_000_u64,
            "deny_delete":true, "deny_purge":true},
    });
    (config, qualification, response)
}

#[test]
fn qualified_stream_rejects_recreation_eviction_retention_transform_and_window_changes() {
    let (config, qualification, response) = setup();
    qualification.validate(&config.topics[0], &config).unwrap();
    let check = |response: &serde_json::Value| {
        validate_response(
            &serde_json::to_vec(response).unwrap(),
            &qualification,
            &config.topics[0],
            &config,
        )
    };
    check(&response).unwrap();
    let mut changed = response.clone();
    changed["created"] = json!("2026-10-01T00:00:01.123Z");
    assert_eq!(check(&changed), Err(EventError::PermissionDenied));
    for (field, value) in [
        ("name", json!("OTHER")),
        ("subjects", json!(["other.subject"])),
        ("storage", json!("memory")),
        ("retention", json!("interest")),
        ("discard", json!("old")),
        ("num_replicas", json!(2)),
        ("max_msgs", json!(63)),
        ("max_bytes", json!(65536)),
        ("max_age", json!(1)),
        ("max_msg_size", json!(32768)),
        ("duplicate_window", json!(60_000_000_000_u64)),
        ("deny_delete", json!(false)),
        ("deny_purge", json!(false)),
        ("sealed", json!(true)),
        ("allow_rollup_hdrs", json!(true)),
        ("discard_new_per_subject", json!(true)),
        ("allow_msg_ttl", json!(true)),
        ("allow_atomic", json!(true)),
        ("allow_msg_counter", json!(true)),
        ("allow_msg_schedules", json!(true)),
        ("subject_transform", json!({})),
        ("republish", json!({})),
        ("mirror", json!({})),
        ("sources", json!([])),
    ] {
        let mut changed = response.clone();
        changed["config"][field] = value;
        assert_eq!(
            check(&changed),
            Err(EventError::PermissionDenied),
            "{field}"
        );
    }
}

#[test]
fn stream_qualification_decoding_is_finite_and_requires_pinned_identity() {
    let (config, mut qualification, response) = setup();
    assert_eq!(
        validate_response(
            &vec![b' '; 8193],
            &qualification,
            &config.topics[0],
            &config
        ),
        Err(EventError::Unavailable)
    );
    let mut deep = response.clone();
    deep["extension"] = json!([[[[[[[[[0]]]]]]]]]);
    assert_eq!(
        validate_response(
            &serde_json::to_vec(&deep).unwrap(),
            &qualification,
            &config.topics[0],
            &config
        ),
        Err(EventError::Unavailable)
    );
    for invalid in [
        "2026-10-01TZ",
        "2026-02-29T00:00:00Z",
        "2026-10-01T24:00:00Z",
        "2026-10-01T00:00:00.Z",
        "2026-10-01T00:00:00+00:00",
    ] {
        qualification.stream_created = invalid.into();
        assert_eq!(
            qualification.validate(&config.topics[0], &config),
            Err(EventError::InvalidEvent)
        );
    }
    qualification.stream_created = "2024-02-29T00:00:00Z".into();
    qualification.validate(&config.topics[0], &config).unwrap();
    qualification.server_version.clear();
    assert_eq!(
        qualification.validate(&config.topics[0], &config),
        Err(EventError::InvalidEvent)
    );
    qualification.server_version = "2.14.6".into();
    qualification.maximum_age_millis = 29_999;
    assert_eq!(
        qualification.validate(&config.topics[0], &config),
        Err(EventError::InvalidEvent)
    );
}
