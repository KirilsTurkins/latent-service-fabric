use super::*;
use serde_json::{json, Value};

fn config_value() -> Value {
    json!({
        "formatVersion":1,"scope":"node/builders","generation":1,
        "validFrom":0,"validUntil":1000,"maxSignatureLifetimeSeconds":100,
        "maxProofAgeSeconds":10,
        "keys":[{"builderId":"builder-a","publicKey":include_str!("../../tests/fixtures/openssl-public-key.txt").trim(),
            "validFrom":0,"validUntil":1000}],
        "requirements":[{"builderId":"builder-a","buildType":crate::PROVENANCE_BUILD_TYPE,
            "sourceRepository":"https://example.com/source","requireReproducible":false}]
    })
}

fn parse(value: &Value) -> SignatureResult<BuilderPolicy> {
    BuilderPolicy::from_json(
        &serde_json::to_vec(value).unwrap(),
        ProvenanceLimits::default(),
    )
}

#[test]
fn requirements_are_canonical_and_bound_into_policy_identity() {
    let mut value = config_value();
    let mut other = value["requirements"][0].clone();
    other["sourceRevision"] = "a".repeat(40).into();
    value["requirements"].as_array_mut().unwrap().push(other);
    let first = parse(&value).unwrap();
    value["requirements"].as_array_mut().unwrap().reverse();
    let reordered = parse(&value).unwrap();
    assert_eq!(first.digest(), reordered.digest());
    assert_eq!(first.canonical_bytes(), reordered.canonical_bytes());
    value["requirements"][0]["requireReproducible"] = true.into();
    assert_ne!(first.digest(), parse(&value).unwrap().digest());
    let canonical: Value = serde_json::from_slice(first.canonical_bytes()).unwrap();
    assert!(canonical["requirements"][0]
        .get("sourceSnapshotDigest")
        .is_none());
}

#[test]
fn unknown_duplicate_null_and_noninteger_policy_fields_fail_closed() {
    let bytes = serde_json::to_string(&config_value()).unwrap();
    let duplicate = bytes.replacen('{', "{\"generation\":1,", 1);
    assert_eq!(
        BuilderPolicy::from_json(duplicate.as_bytes(), ProvenanceLimits::default())
            .unwrap_err()
            .reason(),
        SignatureFailure::InvalidPolicy
    );
    for (field, wrong) in [
        ("unknown", json!(true)),
        ("generation", json!(1.5)),
        ("generation", Value::Null),
    ] {
        let mut value = config_value();
        value[field] = wrong;
        assert_eq!(
            parse(&value).unwrap_err().reason(),
            SignatureFailure::InvalidPolicy
        );
    }
    let mut value = config_value();
    value["requirements"][0]["sourceRevision"] = Value::Null;
    assert_eq!(
        parse(&value).unwrap_err().reason(),
        SignatureFailure::InvalidPolicy
    );
}

#[test]
fn duplicate_keys_rules_weak_keys_and_invalid_sources_are_rejected() {
    for field in ["keys", "requirements"] {
        let mut value = config_value();
        let duplicate = value[field][0].clone();
        value[field].as_array_mut().unwrap().push(duplicate);
        assert_eq!(
            parse(&value).unwrap_err().reason(),
            SignatureFailure::InvalidPolicy
        );
    }
    let mut value = config_value();
    value["keys"][0]["publicKey"] = STANDARD.encode([0; 32]).into();
    assert_eq!(
        parse(&value).unwrap_err().reason(),
        SignatureFailure::InvalidKey
    );
    for (field, invalid) in [
        ("sourceRepository", "https://user:secret@example.com/source"),
        (
            "sourceRepository",
            "https://example.com/source?token=hidden",
        ),
        ("sourceRevision", "main"),
        ("sourceSnapshotDigest", "sha256:bad"),
        ("buildType", "https://example.com/arbitrary-build"),
    ] {
        let mut value = config_value();
        value["requirements"][0][field] = invalid.into();
        assert_eq!(
            parse(&value).unwrap_err().reason(),
            SignatureFailure::InvalidPolicy
        );
    }
}

#[test]
fn lower_rule_bounds_and_typed_spare_capacity_apply_at_adoption() {
    let value = config_value();
    let mut config: BuilderPolicyConfig = serde_json::from_value(value.clone()).unwrap();
    config.scope.reserve(16_384);
    config.keys.reserve(1024);
    config.requirements.reserve(1024);
    config.requirements[0].source_repository.reserve(16_384);
    let one = ProvenanceLimits {
        max_keys: 1,
        max_requirements: 1,
        ..ProvenanceLimits::default()
    };
    let policy = BuilderPolicy::new(config, one).unwrap();
    assert!(policy.config.scope.capacity() < 512);
    assert!(policy.config.keys.capacity() < 32);
    assert!(policy.config.requirements.capacity() < 32);
    assert!(policy.config.requirements[0].source_repository.capacity() < 512);
    let mut two = value;
    let mut other = two["requirements"][0].clone();
    other["requireReproducible"] = true.into();
    two["requirements"].as_array_mut().unwrap().push(other);
    let wider = parse(&two).unwrap();
    assert_eq!(
        wider.fits(one).unwrap_err().reason(),
        SignatureFailure::ResourceLimit
    );
    assert_eq!(
        BuilderPolicy::from_json(&serde_json::to_vec(&two).unwrap(), one)
            .unwrap_err()
            .reason(),
        SignatureFailure::ResourceLimit
    );
}

fn revocation_value(policy: &BuilderPolicy) -> Value {
    json!({"formatVersion":1,"scope":"node/builders","policyDigest":policy.digest().as_str(),
        "generation":1,"validFrom":0,"validUntil":1000,"revokedKeys":[],"revokedBuilders":[]})
}

fn revocations(value: &Value) -> SignatureResult<BuilderRevocationSnapshot> {
    BuilderRevocationSnapshot::from_json(
        &serde_json::to_vec(value).unwrap(),
        ProvenanceLimits::default(),
    )
}

#[test]
fn explicit_revocation_snapshot_binds_scope_and_full_policy() {
    for field in ["scope", "policyDigest"] {
        let policy = parse(&config_value()).unwrap();
        let mut value = revocation_value(&policy);
        value[field] = if field == "scope" {
            "other/builders".into()
        } else {
            format!("sha256:{}", "b".repeat(64)).into()
        };
        assert_eq!(
            BuilderTrust::new(policy, revocations(&value).unwrap())
                .unwrap_err()
                .reason(),
            SignatureFailure::InvalidRevocations
        );
    }
    let policy = parse(&config_value()).unwrap();
    for field in [
        "formatVersion",
        "scope",
        "policyDigest",
        "generation",
        "validFrom",
        "validUntil",
        "revokedKeys",
        "revokedBuilders",
    ] {
        let mut value = revocation_value(&policy);
        value.as_object_mut().unwrap().remove(field);
        assert_eq!(
            revocations(&value).unwrap_err().reason(),
            SignatureFailure::InvalidRevocations
        );
    }
}

#[test]
fn revocation_cardinality_duplicates_and_spare_capacity_are_bounded() {
    let policy = parse(&config_value()).unwrap();
    let mut value = revocation_value(&policy);
    value["revokedBuilders"] = json!(["builder-b", "builder-a"]);
    let mut config: BuilderRevocationSnapshotConfig =
        serde_json::from_value(value.clone()).unwrap();
    config.scope.reserve(16_384);
    config.revoked_builders.reserve(1024);
    config.revoked_builders[0].reserve(16_384);
    let snapshot = BuilderRevocationSnapshot::new(config, ProvenanceLimits::default()).unwrap();
    assert_eq!(snapshot.config.revoked_builders, ["builder-a", "builder-b"]);
    assert!(snapshot.config.scope.capacity() < 512);
    assert!(snapshot.config.revoked_builders.capacity() < 32);
    assert!(snapshot.config.revoked_builders[0].capacity() < 512);
    let one = ProvenanceLimits {
        max_revoked_builders: 1,
        ..ProvenanceLimits::default()
    };
    assert_eq!(
        snapshot.fits(one).unwrap_err().reason(),
        SignatureFailure::ResourceLimit
    );
    value["revokedBuilders"] = json!(["builder-a", "builder-a"]);
    assert_eq!(
        revocations(&value).unwrap_err().reason(),
        SignatureFailure::InvalidRevocations
    );
}

#[test]
fn invalid_validity_and_document_budgets_cannot_enter_builder_trust() {
    for (field, value) in [
        ("validUntil", 0),
        ("generation", 0),
        ("maxSignatureLifetimeSeconds", 0),
        (
            "maxSignatureLifetimeSeconds",
            MAX_SIGNATURE_LIFETIME_SECONDS + 1,
        ),
        ("maxProofAgeSeconds", 0),
        ("maxProofAgeSeconds", MAX_PROOF_AGE_SECONDS + 1),
    ] {
        let mut config = config_value();
        config[field] = value.into();
        assert_eq!(
            parse(&config).unwrap_err().reason(),
            SignatureFailure::InvalidPolicy
        );
    }
    let bytes = serde_json::to_vec(&config_value()).unwrap();
    let limits = ProvenanceLimits {
        max_policy_bytes: bytes.len() - 1,
        ..ProvenanceLimits::default()
    };
    assert_eq!(
        BuilderPolicy::from_json(&bytes, limits)
            .unwrap_err()
            .reason(),
        SignatureFailure::ResourceLimit
    );
    let deep = format!("{}0{}", "[".repeat(18), "]".repeat(18));
    assert_eq!(
        BuilderPolicy::from_json(deep.as_bytes(), ProvenanceLimits::default())
            .unwrap_err()
            .reason(),
        SignatureFailure::ResourceLimit
    );
}
