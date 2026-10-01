use super::*;
use serde_json::json;

fn fixture() -> (TransactionBinding, String, serde_json::Value) {
    let companion = TransactionBinding::decode(&serde_json::to_vec(&json!({
        "apiVersion":"latent.dev/v1","kind":"TransactionBinding","capsule":"examples/java-aggregate", "deployment":"aggregate","binding":"aggregate",
        "profile":"lsf-transaction-v1","hostAbiDigest":latent_manifest::phase4_host_abi_digest(),"namespace":"aggregate","stateSchema":format!("sha256:{}", "a".repeat(64)),
        "operations":[{"operation":"update","mode":"strict-command","inputFormat":"lsf-wit-values-v1","resultFormat":"lsf-wit-values-v1"}]
    })).unwrap()).unwrap();
    let digest = format!("sha256:{}", "b".repeat(64));
    let value = json!({
        "schemaVersion":"latent.application.deferred-http-inputs.v1",
        "scope":{"capsule":companion.capsule,"deployment":companion.deployment,"transactionBinding":companion.binding,"namespace":companion.namespace,"companionDigest":digest},
        "intent":{"binding":"qualified-http","operation":"put-once","count":1,"requestedExpiryUnixMillis":null,
            "payload":{"bytes":STANDARD.encode(b"java-aggregate-put-once-v1\0"),"mediaType":"application/octet-stream","metadata":[]}},
        "adapter":{"name":"qualified-http-put-once-v1","intentFormat":1,"payloadFormat":"http-put-once-bytes-v1","idempotencyProfile":"retained-put-once-v1"},
        "contract":{"retentionHorizonMillis":"600000","maximumBodyBytes":27,"retryDelayMillis":"10"},
        "ceiling":{"maximumPayloadBytes":"27","maximumResponseBytes":"2048","maximumAttempts":3,"maximumAgeMillis":"600000","attemptTimeoutMillis":"2000"},
        "authority":{"installed":false,"ruleGranted":false,"executionQualified":false}
    });
    (companion, digest, value)
}
#[test]
fn original_signed_requirements_preserve_nul_payload_and_finite_native_ceilings() {
    let (companion, digest, input) = fixture();
    let selected =
        HttpRequirements::decode(&serde_json::to_vec(&input).unwrap(), &companion, &digest)
            .unwrap();
    assert_eq!(selected.count, 1);
    assert_eq!(selected.logical_binding, "qualified-http");
    assert_eq!(selected.maximum_body_bytes, 27);
    assert_eq!(selected.retention_horizon_millis, 600_000);
    assert_eq!(selected.retry_delay_millis, 10);
    assert_eq!(selected.ceiling.maximum_payload_bytes, 27);
    assert_eq!(selected.ceiling.maximum_response_bytes, 2048);
    assert_eq!(selected.ceiling.maximum_attempts, 3);
    assert_eq!(selected.ceiling.maximum_age_millis, 600_000);
    assert_eq!(selected.ceiling.attempt_timeout_millis, 2000);
    let original = Value {
        bytes: b"java-aggregate-put-once-v1\0".to_vec(),
        media_type: "application/octet-stream".into(),
        metadata: vec![],
    };
    assert_eq!(
        selected.payload_digest,
        latent_effects::payload::payload_digest(&original).unwrap()
    );
    let mut changed = original;
    *changed.bytes.last_mut().unwrap() = b'X';
    assert_ne!(
        selected.payload_digest,
        latent_effects::payload::payload_digest(&changed).unwrap()
    );
}
#[test]
fn claims_crossed_companions_ambiguous_payloads_and_unsigned_overflow_never_install() {
    let (companion, digest, input) = fixture();
    for (path, value) in [
        ("/authority/installed", true.into()),
        ("/authority/ruleGranted", true.into()),
        ("/authority/executionQualified", true.into()),
        ("/scope/namespace", "foreign".into()),
        (
            "/scope/companionDigest",
            format!("sha256:{}", "c".repeat(64)).into(),
        ),
        ("/scope/deployment", "foreign".into()),
        ("/intent/count", 0.into()),
        ("/intent/requestedExpiryUnixMillis", "1".into()),
        ("/contract/retentionHorizonMillis", "0600000".into()),
        ("/contract/retryDelayMillis", "18446744073709551616".into()),
        ("/ceiling/attemptTimeoutMillis", "600001".into()),
        ("/ceiling/attemptTimeoutMillis", "60001".into()),
        ("/ceiling/maximumResponseBytes", "2047".into()),
        ("/ceiling/maximumAgeMillis", "600001".into()),
        ("/intent/payload/bytes", "***".into()),
        ("/intent/payload/mediaType", "text/html".into()),
        (
            "/intent/payload/metadata",
            json!([["credential", "forbidden"]]),
        ),
    ] {
        let mut hostile = input.clone();
        *hostile.pointer_mut(path).unwrap() = value;
        assert!(
            HttpRequirements::decode(&serde_json::to_vec(&hostile).unwrap(), &companion, &digest)
                .is_err(),
            "{path}"
        );
    }
    assert!(HttpRequirements::decode(&vec![b' '; MAXIMUM_BYTES + 1], &companion, &digest).is_err());
    let original = serde_json::to_string(&input).unwrap();
    let duplicate = original.replacen("\"count\":1", "\"count\":1,\"count\":1", 1);
    assert_ne!(duplicate, original);
    assert!(HttpRequirements::decode(duplicate.as_bytes(), &companion, &digest).is_err());
}
