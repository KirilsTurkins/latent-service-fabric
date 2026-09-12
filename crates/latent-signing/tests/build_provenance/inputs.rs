use super::support::*;
use base64::{engine::general_purpose::STANDARD, Engine};
use latent_signing::*;
use serde_json::{json, Value};

#[test]
fn malformed_observation_numbers_duplicates_null_and_receipts_fail_closed() {
    let bytes = serde_json::to_string(&observation()).unwrap();
    for number in ["1.0", "1e0", "-0", "18446744073709551616"] {
        let malformed = bytes.replace("\"startedAt\":900", &format!("\"startedAt\":{number}"));
        assert_eq!(
            decode_build_observation(malformed.as_bytes(), ProvenanceLimits::default())
                .unwrap_err()
                .reason(),
            SignatureFailure::MalformedProvenance
        );
    }
    for malformed in [
        bytes.replacen('{', "{\"formatVersion\":1,", 1),
        bytes.replace("\"hermetic\":false", "\"hermetic\":null"),
    ] {
        assert_eq!(
            decode_build_observation(malformed.as_bytes(), ProvenanceLimits::default())
                .unwrap_err()
                .reason(),
            SignatureFailure::MalformedProvenance
        );
    }
    for receipt in [
        json!({"schemaVersion":1,"artifact":"echo-capsule.wasm","trust":{"kind":"local-clean-build","signed":false}}),
        json!({"formatVersion":1,"operation":"package-supplied-artifacts","packager":"latent-packaging", "packagerVersion":"test","inputs":[]}),
    ] {
        assert_eq!(
            decode_build_observation(
                &serde_json::to_vec(&receipt).unwrap(),
                ProvenanceLimits::default()
            )
            .unwrap_err()
            .reason(),
            SignatureFailure::MalformedProvenance
        );
    }
}

#[test]
fn oversized_base64_arrays_nesting_and_lowered_limits_are_rejected() {
    let (signer, _, _) = signer(BUILDER);
    let evidence = signed(&signer, &observation());
    let mut envelope: Value = serde_json::from_slice(evidence.payload_bytes()).unwrap();
    envelope["payload"] = STANDARD.encode(vec![b' '; 32_769]).into();
    assert_eq!(
        inspect_provenance(
            &serde_json::to_vec(&envelope).unwrap(),
            ProvenanceLimits::default()
        )
        .unwrap_err()
        .reason(),
        SignatureFailure::ResourceLimit
    );
    let bytes = serde_json::to_vec(&observation()).unwrap();
    let limits = ProvenanceLimits {
        max_materials: 6,
        ..ProvenanceLimits::default()
    };
    assert_eq!(
        decode_build_observation(&bytes, limits)
            .unwrap_err()
            .reason(),
        SignatureFailure::ResourceLimit
    );
    let deep = format!("{}0{}", "[".repeat(18), "]".repeat(18));
    assert_eq!(
        decode_build_observation(deep.as_bytes(), ProvenanceLimits::default())
            .unwrap_err()
            .reason(),
        SignatureFailure::ResourceLimit
    );
    let limits = ProvenanceLimits {
        max_payload_bytes: 64,
        ..ProvenanceLimits::default()
    };
    assert_eq!(
        inspect_provenance(evidence.payload_bytes(), limits)
            .unwrap_err()
            .reason(),
        SignatureFailure::ResourceLimit
    );
}

#[test]
fn required_materials_and_snapshot_associations_are_not_self_certifying_receipts() {
    let mut value = observation();
    value
        .materials
        .retain(|material| material.name != "dependency-lock");
    assert_eq!(
        decode_build_observation(
            &serde_json::to_vec(&value).unwrap(),
            ProvenanceLimits::default()
        )
        .unwrap_err()
        .reason(),
        SignatureFailure::MalformedProvenance
    );
    let mut value = observation();
    value.source.snapshot_digest = format!("sha256:{}", "c".repeat(64));
    assert_eq!(
        decode_build_observation(
            &serde_json::to_vec(&value).unwrap(),
            ProvenanceLimits::default()
        )
        .unwrap_err()
        .reason(),
        SignatureFailure::IntegrityMismatch
    );
    let mut value = observation();
    value.materials[0].name = "../private-path".into();
    assert_eq!(
        decode_build_observation(
            &serde_json::to_vec(&value).unwrap(),
            ProvenanceLimits::default()
        )
        .unwrap_err()
        .reason(),
        SignatureFailure::MalformedProvenance
    );
}
