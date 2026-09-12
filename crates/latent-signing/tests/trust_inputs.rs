use base64::{engine::general_purpose::STANDARD, Engine};
use ed25519_dalek::VerifyingKey;
use latent_artifacts::package::artifact_blob_digest;
use latent_signing::{
    generate_signing_key, PublisherPolicy, PublisherPolicyConfig, PublisherTrust,
    RevocationSnapshot, RevocationSnapshotConfig, SignatureFailure, SignatureLimits,
    SignatureResult, MAX_PROOF_AGE_SECONDS, MAX_SIGNATURE_LIFETIME_SECONDS,
};
use serde_json::{json, Value};

const PUBLIC_KEY: &str = include_str!("fixtures/openssl-public-key.txt");
type Decode = fn(&[u8], SignatureLimits) -> SignatureResult<()>;

fn policy_value() -> Value {
    json!({
        "formatVersion": 1, "scope": "test:publisher", "generation": 1,
        "validFrom": 900, "validUntil": 3000,
        "maxSignatureLifetimeSeconds": 2000, "maxProofAgeSeconds": 60,
        "keys": [{"publisherId": "fixture", "publicKey": PUBLIC_KEY.trim(),
                  "validFrom": 900, "validUntil": 3000}],
    })
}

fn policy(value: &Value) -> PublisherPolicy {
    PublisherPolicy::from_json(
        &serde_json::to_vec(value).unwrap(),
        SignatureLimits::default(),
    )
    .unwrap()
}

fn revocation_value(policy: &PublisherPolicy) -> Value {
    json!({
        "formatVersion": 1, "scope": "test:publisher", "generation": 1,
        "policyDigest": policy.digest().as_str(), "validFrom": 900, "validUntil": 3000,
        "revokedKeys": [], "revokedPublishers": [],
    })
}

fn decode_policy(bytes: &[u8], limits: SignatureLimits) -> SignatureResult<()> {
    PublisherPolicy::from_json(bytes, limits).map(drop)
}

fn decode_revocations(bytes: &[u8], limits: SignatureLimits) -> SignatureResult<()> {
    RevocationSnapshot::from_json(bytes, limits).map(drop)
}

#[test]
fn trust_json_rejects_duplicate_unknown_deep_and_noninteger_fields() {
    let policy = policy_value();
    let revocations = revocation_value(&self::policy(&policy));
    let cases: [(Value, Decode, SignatureFailure); 2] = [
        (policy, decode_policy, SignatureFailure::InvalidPolicy),
        (
            revocations,
            decode_revocations,
            SignatureFailure::InvalidRevocations,
        ),
    ];
    for (value, decode, malformed) in cases {
        let text = serde_json::to_string(&value).unwrap();
        for changed in [
            text.replacen('{', "{\"unknown\":1,", 1),
            text.replace("\"generation\":1", "\"generation\":1,\"generation\":1"),
            text.replace("\"generation\":1", "\"generation\":1.0"),
            text.replace("\"generation\":1", "\"generation\":1e0"),
            text.replace("\"generation\":1", "\"generation\":-0"),
            text.replace("\"generation\":1", "\"generation\":18446744073709551616"),
        ] {
            assert_eq!(
                decode(changed.as_bytes(), SignatureLimits::default())
                    .unwrap_err()
                    .reason(),
                malformed
            );
        }
        // Tiny nested input crosses the structural ceiling before typed parsing.
        let nested = format!("{}1{}", "[".repeat(17), "]".repeat(17));
        let changed = format!("{{\"unknown\":{nested},{}", &text[1..]);
        assert_eq!(
            decode(changed.as_bytes(), SignatureLimits::default())
                .unwrap_err()
                .reason(),
            SignatureFailure::ResourceLimit
        );
    }
}

#[test]
fn exact_and_oversized_trust_json_respect_lowered_document_ceilings() {
    let policy = policy_value();
    let revocations = revocation_value(&self::policy(&policy));
    for (value, decode) in [
        (policy, decode_policy as Decode),
        (revocations, decode_revocations as Decode),
    ] {
        let bytes = serde_json::to_vec(&value).unwrap();
        let limits = SignatureLimits {
            max_policy_bytes: bytes.len(),
            max_revocation_bytes: bytes.len(),
            ..SignatureLimits::default()
        };
        decode(&bytes, limits).unwrap();
        let mut oversized = bytes;
        oversized.push(b' ');
        assert_eq!(
            decode(&oversized, limits).unwrap_err().reason(),
            SignatureFailure::ResourceLimit
        );
    }
}

#[test]
fn revocation_snapshot_requires_every_field_and_rejects_duplicate_membership() {
    let value = revocation_value(&policy(&policy_value()));
    for field in value.as_object().unwrap().keys() {
        let mut missing = value.clone();
        missing.as_object_mut().unwrap().remove(field);
        assert_eq!(
            decode_revocations(
                &serde_json::to_vec(&missing).unwrap(),
                SignatureLimits::default()
            )
            .unwrap_err()
            .reason(),
            SignatureFailure::InvalidRevocations,
            "required field: {field}"
        );
    }
    for field in ["revokedKeys", "revokedPublishers"] {
        let mut malformed = value.clone();
        malformed[field] = Value::Null;
        assert!(decode_revocations(
            &serde_json::to_vec(&malformed).unwrap(),
            SignatureLimits::default()
        )
        .is_err());
        let entry = if field == "revokedKeys" {
            artifact_blob_digest(b"key").into_string()
        } else {
            "publisher".into()
        };
        malformed[field] = json!([entry, entry]);
        assert_eq!(
            decode_revocations(
                &serde_json::to_vec(&malformed).unwrap(),
                SignatureLimits::default()
            )
            .unwrap_err()
            .reason(),
            SignatureFailure::InvalidRevocations
        );
    }
}

#[test]
fn public_policy_constructors_reject_weak_and_noncanonical_anchors() {
    let mut identity = [0; 32];
    identity[0] = 1;
    // Select a decodable non-weak noncanonical point, so the public-policy test
    // exercises the encoding guard independently of weak-key rejection.
    let noncanonical = (0xed..=0xff)
        .find_map(|low| {
            let mut encoded = [0xff; 32];
            encoded[0] = low;
            encoded[31] = 0x7f;
            VerifyingKey::from_bytes(&encoded)
                .ok()
                .filter(|key| !key.is_weak())
                .map(|_| encoded)
        })
        .unwrap();
    for key in [[0; 32], identity, noncanonical] {
        let mut value = policy_value();
        value["keys"][0]["publicKey"] = STANDARD.encode(key).into();
        assert_eq!(
            decode_policy(
                &serde_json::to_vec(&value).unwrap(),
                SignatureLimits::default()
            )
            .unwrap_err()
            .reason(),
            SignatureFailure::InvalidKey
        );
        let config: PublisherPolicyConfig = serde_json::from_value(value).unwrap();
        assert_eq!(
            PublisherPolicy::new(config, SignatureLimits::default())
                .unwrap_err()
                .reason(),
            SignatureFailure::InvalidKey
        );
    }
}

#[test]
fn independent_snapshots_require_exact_policy_and_scope_binding() {
    for (field, replacement) in [
        ("scope", "different:scope".to_owned()),
        (
            "policyDigest",
            artifact_blob_digest(b"different policy").into_string(),
        ),
    ] {
        let policy = policy(&policy_value());
        let mut value = revocation_value(&policy);
        value[field] = replacement.into();
        // Each input is independently valid; the association must still fail.
        let revocations = RevocationSnapshot::from_json(
            &serde_json::to_vec(&value).unwrap(),
            SignatureLimits::default(),
        )
        .unwrap();
        assert_eq!(
            PublisherTrust::new(policy, revocations)
                .unwrap_err()
                .reason(),
            SignatureFailure::InvalidRevocations
        );
    }
}

#[test]
fn public_configs_reject_invalid_validity_and_lifetime_parameters() {
    for (field, value) in [
        ("validUntil", 900),
        ("validUntil", 899),
        ("generation", 0),
        ("maxSignatureLifetimeSeconds", 0),
        (
            "maxSignatureLifetimeSeconds",
            MAX_SIGNATURE_LIFETIME_SECONDS + 1,
        ),
        ("maxProofAgeSeconds", 0),
        ("maxProofAgeSeconds", MAX_PROOF_AGE_SECONDS + 1),
    ] {
        let mut malformed = policy_value();
        malformed[field] = value.into();
        let typed: PublisherPolicyConfig = serde_json::from_value(malformed.clone()).unwrap();
        assert_eq!(
            PublisherPolicy::new(typed, SignatureLimits::default())
                .unwrap_err()
                .reason(),
            SignatureFailure::InvalidPolicy
        );
        assert_eq!(
            decode_policy(
                &serde_json::to_vec(&malformed).unwrap(),
                SignatureLimits::default()
            )
            .unwrap_err()
            .reason(),
            SignatureFailure::InvalidPolicy
        );
    }
    let baseline = revocation_value(&policy(&policy_value()));
    for (field, value) in [("validUntil", 900), ("validUntil", 899), ("generation", 0)] {
        let mut malformed = baseline.clone();
        malformed[field] = value.into();
        let typed: RevocationSnapshotConfig = serde_json::from_value(malformed.clone()).unwrap();
        assert_eq!(
            RevocationSnapshot::new(typed, SignatureLimits::default())
                .unwrap_err()
                .reason(),
            SignatureFailure::InvalidRevocations
        );
        assert_eq!(
            decode_revocations(
                &serde_json::to_vec(&malformed).unwrap(),
                SignatureLimits::default()
            )
            .unwrap_err()
            .reason(),
            SignatureFailure::InvalidRevocations
        );
    }
}

#[test]
fn lower_key_and_revocation_cardinality_limits_accept_equality_only() {
    let limits = SignatureLimits {
        max_keys: 1,
        max_revoked_keys: 1,
        max_revoked_publishers: 1,
        ..SignatureLimits::default()
    };
    let mut value = policy_value();
    decode_policy(&serde_json::to_vec(&value).unwrap(), limits).unwrap();
    PublisherPolicy::new(serde_json::from_value(value.clone()).unwrap(), limits).unwrap();
    let generated = generate_signing_key().unwrap();
    let mut second = value["keys"][0].clone();
    second["publicKey"] = STANDARD.encode(generated.public_key()).into();
    value["keys"].as_array_mut().unwrap().push(second);
    assert_eq!(
        decode_policy(&serde_json::to_vec(&value).unwrap(), limits)
            .unwrap_err()
            .reason(),
        SignatureFailure::ResourceLimit
    );
    assert_eq!(
        PublisherPolicy::new(serde_json::from_value(value).unwrap(), limits)
            .unwrap_err()
            .reason(),
        SignatureFailure::ResourceLimit
    );

    let baseline = revocation_value(&policy(&policy_value()));
    for (field, entries) in [
        (
            "revokedKeys",
            [
                artifact_blob_digest(b"a").into_string(),
                artifact_blob_digest(b"b").into_string(),
            ],
        ),
        ("revokedPublishers", ["a".to_owned(), "b".to_owned()]),
    ] {
        let mut value = baseline.clone();
        value[field] = json!([entries[0]]);
        decode_revocations(&serde_json::to_vec(&value).unwrap(), limits).unwrap();
        RevocationSnapshot::new(serde_json::from_value(value.clone()).unwrap(), limits).unwrap();
        value[field] = json!(entries);
        assert_eq!(
            decode_revocations(&serde_json::to_vec(&value).unwrap(), limits)
                .unwrap_err()
                .reason(),
            SignatureFailure::ResourceLimit
        );
        assert_eq!(
            RevocationSnapshot::new(serde_json::from_value(value).unwrap(), limits)
                .unwrap_err()
                .reason(),
            SignatureFailure::ResourceLimit
        );
    }
}
