use super::*;
use serde_json::json;

fn fixture() -> (TransactionBinding, String, serde_json::Value) {
    let companion = TransactionBinding::decode(&serde_json::to_vec(&json!({
        "apiVersion":"latent.dev/v1", "kind":"TransactionBinding", "capsule":"examples/transactional-aggregate",
        "deployment":"aggregate", "binding":"aggregate", "profile":"lsf-transaction-v1",
        "hostAbiDigest":latent_manifest::phase4_host_abi_digest(), "namespace":"aggregate",
        "stateSchema":format!("sha256:{}", "a".repeat(64)),
        "operations":[{"operation":"update", "mode":"strict-command", "inputFormat":"lsf-wit-values-v1", "resultFormat":"lsf-wit-values-v1"}]
    })).unwrap()).unwrap();
    let digest = format!("sha256:{}", "b".repeat(64));
    let input = json!({
        "schemaVersion":"latent.application.deferred-event-inputs.v1",
        "scope":{"capsule":companion.capsule,"deployment":companion.deployment,
            "transactionBinding":companion.binding,"namespace":companion.namespace,
            "stateSchema":companion.state_schema,"companionDigest":digest},
        "intent":{"binding":"approved-event","operation":"event","count":1,"requestedExpiryUnixMillis":null,
            "payload":{"kind":"bounded-event-value","maximumBytes":8,
                "mediaType":"application/vnd.lsf.aggregate-v1","metadata":"empty"}},
        "adapter":{"name":"nats-jetstream-effect-v1","intentFormat":1,"payloadFormat":"nats-event-value-v1"},
        "ceiling":{"maximumPayloadBytes":"8192","maximumResponseBytes":"16384",
            "maximumAttempts":3,"maximumAgeMillis":"30000","attemptTimeoutMillis":"5000"},
        "authority":{"installed":false,"ruleGranted":false,"executionQualified":false}
    });
    (companion, digest, input)
}

#[test]
fn retained_event_declaration_preserves_aggregate_payload_and_finite_original_dispatch_limits() {
    let (companion, digest, raw) = fixture();
    let selected =
        EventRequirements::decode(&serde_json::to_vec(&raw).unwrap(), &companion, &digest).unwrap();
    assert_eq!(selected.logical_binding, "approved-event");
    assert_eq!(selected.operation, "event");
    assert_eq!(selected.count, 1);
    assert_eq!(selected.maximum_value_bytes, 8);
    assert_eq!(selected.media_type, "application/vnd.lsf.aggregate-v1");
    assert_eq!(selected.ceiling.maximum_payload_bytes, 8192);
    assert_eq!(selected.ceiling.maximum_response_bytes, 16384);
    assert_eq!(selected.ceiling.maximum_attempts, 3);
    assert_eq!(selected.ceiling.maximum_age_millis, 30000);
    assert_eq!(selected.ceiling.attempt_timeout_millis, 5000);
}

#[test]
fn event_requirements_refuse_crossed_namespace_schema_companion_format_or_descriptive_grants() {
    let (companion, digest, original) = fixture();
    for (path, value) in [
        ("/scope/capsule", json!("foreign")),
        ("/scope/deployment", json!("foreign")),
        ("/scope/transactionBinding", json!("foreign")),
        ("/scope/namespace", json!("foreign")),
        (
            "/scope/stateSchema",
            json!(format!("sha256:{}", "c".repeat(64))),
        ),
        (
            "/scope/companionDigest",
            json!(format!("sha256:{}", "c".repeat(64))),
        ),
        (
            "/schemaVersion",
            json!("latent.application.deferred-event-inputs.v2"),
        ),
        ("/intent/operation", json!("publish")),
        ("/intent/count", json!(0)),
        ("/intent/count", json!(33)),
        ("/intent/requestedExpiryUnixMillis", json!("1")),
        ("/intent/payload/kind", json!("unbounded-event-value")),
        ("/intent/payload/maximumBytes", json!(0)),
        ("/intent/payload/maximumBytes", json!(8193)),
        ("/intent/payload/mediaType", json!("")),
        ("/intent/payload/metadata", json!("any")),
        ("/adapter/name", json!("unqualified-publisher")),
        ("/adapter/intentFormat", json!(2)),
        ("/adapter/payloadFormat", json!("unknown-event-format")),
        ("/authority/installed", json!(true)),
        ("/authority/ruleGranted", json!(true)),
        ("/authority/executionQualified", json!(true)),
    ] {
        let mut changed = original.clone();
        *changed.pointer_mut(path).unwrap() = value;
        assert!(
            EventRequirements::decode(&serde_json::to_vec(&changed).unwrap(), &companion, &digest)
                .is_err(),
            "{path}"
        );
    }
}

#[test]
fn event_requirements_refuse_unknown_duplicate_oversized_and_noncanonical_finite_numbers() {
    let (companion, digest, original) = fixture();
    for (path, value) in [
        ("/ceiling/maximumPayloadBytes", json!("8192x")),
        ("/ceiling/maximumResponseBytes", json!("16383")),
        ("/ceiling/maximumAgeMillis", json!("030000")),
        ("/ceiling/maximumAgeMillis", json!("18446744073709551616")),
        ("/ceiling/maximumAttempts", json!(0)),
        ("/ceiling/attemptTimeoutMillis", json!("30001")),
    ] {
        let mut changed = original.clone();
        *changed.pointer_mut(path).unwrap() = value;
        assert!(
            EventRequirements::decode(&serde_json::to_vec(&changed).unwrap(), &companion, &digest)
                .is_err(),
            "{path}"
        );
    }
    let mut unknown = original.clone();
    unknown["intent"]["payload"]["permission"] = json!(true);
    assert!(
        EventRequirements::decode(&serde_json::to_vec(&unknown).unwrap(), &companion, &digest)
            .is_err()
    );
    let raw = serde_json::to_string(&original).unwrap();
    let duplicated = raw.replacen("\"count\":1", "\"count\":1,\"count\":1", 1);
    assert_ne!(raw, duplicated);
    assert!(EventRequirements::decode(duplicated.as_bytes(), &companion, &digest).is_err());
    assert!(
        EventRequirements::decode(&vec![b' '; MAXIMUM_BYTES + 1], &companion, &digest).is_err()
    );
}
