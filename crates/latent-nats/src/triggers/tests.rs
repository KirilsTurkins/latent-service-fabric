use super::{consumer, wire, RootBudget, TriggerBinding, TriggerConfig};
use crate::{EventError, NatsEndpoint};
use serde_json::json;

fn config() -> TriggerConfig {
    TriggerConfig {
        format_version: 1,
        endpoint: NatsEndpoint {
            peer: "127.0.0.1:4222".parse().unwrap(),
            server_name: "localhost".into(),
            allow_non_public_peer: true,
        },
        public_roots: true,
        extra_roots: vec![],
        bindings: vec![TriggerBinding {
            id: "orders".into(),
            tenant: "tenant-a".into(),
            principal_subject: "orders-ingress".into(),
            service: "callee".into(),
            contract: "tests:local/api@1.0.0".into(),
            function: "answer".into(),
            route: None,
            stream: "ORDERS".into(),
            consumer: "PROCESS".into(),
            filter_subject: "orders.new".into(),
            budget: RootBudget {
                cpu_fuel: 1000,
                memory_bytes: 65536,
                wall_time_millis: 1000,
                child_calls: 0,
                outbound_requests: 0,
                blob_read_bytes: 0,
                blob_write_bytes: 0,
                log_bytes: 0,
            },
        }],
        maximum_payload_bytes: 1024,
        operation_timeout_millis: 1000,
        poll_interval_millis: 10,
        maximum_deliveries: 3,
        ack_wait_millis: 3000,
        redelivery_delay_millis: 100,
    }
}
#[test]
fn configuration_roundtrip_rejects_ambiguous_scope_and_retained_capacity() {
    let mut c = config();
    let bytes = c.to_json().unwrap();
    assert_eq!(
        TriggerConfig::from_json(&bytes).unwrap().to_json().unwrap(),
        bytes
    );
    let mut foreign = c.bindings[0].clone();
    foreign.id = "foreign".into();
    foreign.tenant = "tenant-b".into();
    foreign.consumer = "OTHER".into();
    c.bindings.push(foreign);
    assert_eq!(c.validate(), Err(EventError::InvalidEvent));
    c.bindings.pop();
    c.bindings[0].service.reserve(1024);
    assert_eq!(c.validate(), Err(EventError::InvalidEvent));
    let mut document: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
    document["principalFromHeader"] = json!("tenant");
    assert!(TriggerConfig::from_json(&serde_json::to_vec(&document).unwrap()).is_err());
}
#[test]
fn acknowledgements_cannot_address_foreign_consumers_or_arbitrary_subjects() {
    let c = config();
    let binding = &c.bindings[0];
    for reply in [
        "$JS.ACK.ORDERS.PROCESS.1.2.3.4.0",
        "$JS.ACK._.AB12.ORDERS.PROCESS.1.2.3.4.0",
    ] {
        assert_eq!(
            wire::identity(reply, binding).unwrap(),
            wire::DeliveryIdentity {
                delivery: 1,
                sequence: 2
            }
        );
    }
    for reply in [
        "$JS.ACK.OTHER.PROCESS.1.2.3.4.0",
        "$JS.ACK.ORDERS.OTHER.1.2.3.4.0",
        "$JS.ACK.ORDERS.PROCESS.0.2.3.4.0",
        "$JS.ACK.ORDERS.PROCESS.1.2.3.4.0.extra",
        "$JS.ACK.domain.AB12.ORDERS.PROCESS.1.2.3.4.0",
        "untrusted.subject",
        "$JS.ACK.ORDERS.PROCESS.4294967296.2.3.4.0",
    ] {
        assert!(wire::identity(reply, binding).is_err(), "{reply}");
    }
}
#[test]
fn broker_consumer_must_match_finite_operator_profile() {
    let c = config();
    let b = &c.bindings[0];
    let info = json!({"stream_name":"ORDERS","name":"PROCESS","config":{
        "durable_name":"PROCESS","name":"PROCESS","filter_subject":"orders.new",
        "ack_policy":"explicit","replay_policy":"instant","deliver_policy":"all",
        "ack_wait":3_000_000_000u64,"max_deliver":3,"max_waiting":1,"max_ack_pending":1,
        "max_batch":1,"max_bytes":10240,"max_expires":100_000_000}});
    assert_eq!(
        consumer::validate(&serde_json::to_vec(&info).unwrap(), b, &c),
        Ok(())
    );
    for (key, value) in [
        ("max_deliver", json!(-1)),
        ("max_ack_pending", json!(0)),
        ("max_batch", json!(10)),
        ("filter_subject", json!("orders.>")),
        ("deliver_subject", json!("push.destination")),
        ("backoff", json!([100_000])),
        ("ack_policy", json!("none")),
        ("headers_only", json!(true)),
    ] {
        let mut changed = info.clone();
        changed["config"][key] = value;
        assert!(
            consumer::validate(&serde_json::to_vec(&changed).unwrap(), b, &c).is_err(),
            "{key}"
        );
    }
}
