use super::*;
use crate::aot::{
    ownership::{AotResourceLimits, Budget},
    supervisor::CompletedAotJob,
    AotCompilerLimits, ValidatedAotProfile,
};
use serde_json::{json, Value};
use zeroize::Zeroizing;

fn fixture() -> (
    TrustedAotCompilerAuthority,
    AotCompatibilityKey,
    TrustedAotOutput,
) {
    static PROFILE: std::sync::OnceLock<ValidatedAotProfile> = std::sync::OnceLock::new();
    let profile = PROFILE.get_or_init(|| {
        ValidatedAotProfile::from_config(
            &crate::WasmtimeConfig::default(),
            AotCompilerLimits::default(),
        )
        .unwrap()
    });
    let key = crate::aot::identity::fixture(profile);
    let authority = TrustedAotCompilerAuthority::new(
        "compiler",
        Zeroizing::new([7; 32]),
        AotCompilerLimits::default(),
    )
    .unwrap();
    let budget = Budget::new(AotResourceLimits::default()).unwrap();
    let (work, permit) = budget.reserve(1, 1, 13).unwrap();
    let output = authority
        .seal_completed(CompletedAotJob::fixture(
            key.clone(),
            b"native-output".to_vec(),
            permit,
        ))
        .unwrap();
    drop(work);
    (authority, key, output)
}
fn checked(
    authority: &TrustedAotCompilerAuthority,
    key: &AotCompatibilityKey,
    value: &Value,
) -> Result<VerifiedReceipt, PlatformError> {
    authority.verify_receipt(key, &serde_json::to_vec(value).unwrap(), 1024)
}
fn rejected(result: Result<VerifiedReceipt, PlatformError>, code: PlatformErrorCode) {
    match result {
        Err(error) => assert_eq!(error.code, code),
        Ok(_) => panic!("untrusted receipt accepted"),
    }
}

#[test]
fn receipt_read_buffer_can_drop_before_exact_byte_verification() {
    let (authority, key, output) = fixture();
    let receipt = output.receipt().to_vec();
    let verified = authority.verify_receipt(&key, &receipt, 1024).unwrap();
    drop(receipt);
    assert_eq!(verified.output_digest, *output.output_digest());
    assert_eq!(verified.output_size, output.output().len());
    verified.check_bytes(output.output()).unwrap();
    assert!(verified.check_bytes(b"native-output!").is_err());
    assert!(verified.check_bytes(b"forged-output").is_err());
}

#[test]
fn every_compatibility_field_is_checked_before_claims_are_exposed() {
    let (authority, key, output) = fixture();
    let original: Value = serde_json::from_slice(output.receipt()).unwrap();
    let replacements = [
        ("scope", json!({"kind":"tenant","tenant":"other"})),
        ("package", json!(blob([8; 32]).as_str())),
        ("component", json!(blob([8; 32]).as_str())),
        ("componentBytes", json!(9)),
        ("metadataDigest", json!([8; 32].to_vec())),
        ("engineProfileDigest", json!(blob([8; 32]).as_str())),
        ("engineCompatibility", json!([8; 32].to_vec())),
        ("capabilityContractDigest", json!(blob([8; 32]).as_str())),
        ("securityPolicyDigest", json!(blob([8; 32]).as_str())),
        ("compilerDigest", json!([8; 32].to_vec())),
        ("sandboxDigest", json!([8; 32].to_vec())),
    ];
    for (field, replacement) in replacements {
        let mut value = original.clone();
        value["compatibility"][field] = replacement;
        rejected(
            checked(&authority, &key, &value),
            PlatformErrorCode::PermissionDenied,
        );
    }
}

#[test]
fn forged_output_claims_and_other_host_key_fail_mac_before_any_raw_read() {
    let (authority, key, output) = fixture();
    let original: Value = serde_json::from_slice(output.receipt()).unwrap();
    for (field, replacement) in [
        (
            "outputDigest",
            json!(blob(Sha256::digest(b"forged-output").into()).as_str()),
        ),
        ("outputSize", json!(12)),
        ("compilerIdentity", json!("other-compiler")),
        ("seal", json!([0; 32].to_vec())),
    ] {
        let mut value = original.clone();
        value[field] = replacement;
        rejected(
            checked(&authority, &key, &value),
            PlatformErrorCode::PermissionDenied,
        );
    }
    let other = TrustedAotCompilerAuthority::new(
        "compiler",
        Zeroizing::new([9; 32]),
        AotCompilerLimits::default(),
    )
    .unwrap();
    rejected(
        other.verify_receipt(&key, output.receipt(), 1024),
        PlatformErrorCode::PermissionDenied,
    );
}

#[test]
fn closed_receipt_rejects_duplicate_null_unknown_and_invalid_numeric_shapes() {
    let (authority, key, output) = fixture();
    let original: Value = serde_json::from_slice(output.receipt()).unwrap();
    for (field, replacement) in [
        ("formatVersion", json!(2)),
        ("outputSize", json!(0)),
        ("outputSize", json!(-1)),
        ("outputSize", json!(1.0)),
        ("outputSize", json!(u64::MAX)),
        ("outputSize", json!(null)),
        ("seal", json!([0; 31].to_vec())),
        ("seal", json!([256; 32].to_vec())),
        ("unknown", json!(true)),
        ("outputDigest", json!("sha256:bad")),
    ] {
        let mut value = original.clone();
        value[field] = replacement;
        rejected(
            checked(&authority, &key, &value),
            PlatformErrorCode::CorruptArtifact,
        );
    }
    for replacement in [json!(null), json!({}), json!(7)] {
        let mut value = original.clone();
        value["compatibility"]["package"] = replacement;
        rejected(
            checked(&authority, &key, &value),
            PlatformErrorCode::CorruptArtifact,
        );
    }
    let duplicate = String::from_utf8(output.receipt().to_vec())
        .unwrap()
        .replacen(
            "\"formatVersion\":1",
            "\"formatVersion\":1,\"formatVersion\":1",
            1,
        );
    rejected(
        authority.verify_receipt(&key, duplicate.as_bytes(), 1024),
        PlatformErrorCode::CorruptArtifact,
    );
    let mut trailing = output.receipt().to_vec();
    trailing.extend_from_slice(b" {}");
    rejected(
        authority.verify_receipt(&key, &trailing, 1024),
        PlatformErrorCode::CorruptArtifact,
    );
}

#[test]
fn structural_and_byte_bounds_fail_before_typed_retention() {
    let (authority, key, output) = fixture();
    let mut padded = output.receipt().to_vec();
    padded.resize(MAX_RECEIPT_BYTES, b' ');
    authority.verify_receipt(&key, &padded, 1024).unwrap();
    padded.push(b' ');
    rejected(
        authority.verify_receipt(&key, &padded, 1024),
        PlatformErrorCode::CorruptArtifact,
    );
    for bytes in [
        format!("{}0{}", "[".repeat(8), "]".repeat(8)),
        format!("[{}]", vec!["0"; 1024].join(",")),
        format!("\"{}\"", "x".repeat(1025)),
    ] {
        assert!(json::preflight(bytes.as_bytes()).is_err());
    }
    assert!(json::preflight(format!("\"{}\"", "x".repeat(1024)).as_bytes()).is_ok());
    rejected(
        authority.verify_receipt(&key, output.receipt(), 12),
        PlatformErrorCode::CorruptArtifact,
    );
}
