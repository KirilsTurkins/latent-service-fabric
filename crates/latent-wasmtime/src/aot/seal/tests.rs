use super::*;
use crate::aot::ownership::{AotResourceLimits, AotResourceSnapshot, Budget};

fn key() -> AotCompatibilityKey {
    let profile = super::super::ValidatedAotProfile::from_config(
        &crate::WasmtimeConfig::default(),
        AotCompilerLimits::default(),
    )
    .unwrap();
    super::super::identity::fixture(&profile)
}

#[test]
fn verification_rejects_tampered_bytes_even_with_a_recomputed_digest() {
    let authority = TrustedAotCompilerAuthority::new(
        "compiler",
        Zeroizing::new([7; 32]),
        AotCompilerLimits::default(),
    )
    .unwrap();
    let key = key();
    let budget = Budget::new(AotResourceLimits::default()).unwrap();
    let (work, permit) = budget.reserve(1, 1, 13).unwrap();
    let mut output = authority
        .seal_completed(CompletedAotJob::fixture(
            key.clone(),
            b"native-output".to_vec(),
            permit,
        ))
        .unwrap();
    drop(work);
    authority.verify(&output, &key).unwrap();
    assert_eq!(budget.snapshot().jobs, 0);
    assert_eq!(budget.snapshot().native_bytes, 13);
    assert_eq!(budget.snapshot().output_owners, 1);

    // A cache writer can replace bytes and all public digest metadata, but
    // cannot forge the host-key authenticator over those new bytes.
    output.output[0] ^= 1;
    assert_eq!(
        authority.verify(&output, &key).unwrap_err().code,
        PlatformErrorCode::CorruptArtifact
    );
    output.output_digest = blob(Sha256::digest(&output.output).into());
    assert_eq!(
        authority.verify(&output, &key).unwrap_err().code,
        PlatformErrorCode::PermissionDenied
    );
    drop(output);
    assert_eq!(budget.snapshot(), AotResourceSnapshot::default());
}

#[test]
fn verification_requires_the_same_host_key_and_expected_engine_profile() {
    let limits = AotCompilerLimits::default();
    let authority =
        TrustedAotCompilerAuthority::new("compiler", Zeroizing::new([7; 32]), limits).unwrap();
    let other =
        TrustedAotCompilerAuthority::new("compiler", Zeroizing::new([8; 32]), limits).unwrap();
    let key = key();
    let changed = super::super::ValidatedAotProfile::from_config(
        &crate::WasmtimeConfig {
            compiler_optimization: crate::CompilerOptimization::SpeedAndSize,
            ..Default::default()
        },
        limits,
    )
    .unwrap();
    let expected = super::super::identity::fixture(&changed);
    assert_ne!(key.engine_compatibility(), expected.engine_compatibility());
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
    authority.verify(&output, &key).unwrap();
    for error in [
        other.verify(&output, &key).unwrap_err(),
        authority.verify(&output, &expected).unwrap_err(),
    ] {
        assert_eq!(error.code, PlatformErrorCode::PermissionDenied);
    }
    drop(output);
    assert_eq!(budget.snapshot(), AotResourceSnapshot::default());
}

#[test]
fn rejected_output_length_and_capacity_refund_the_complete_permit() {
    let authority = TrustedAotCompilerAuthority::new(
        "compiler",
        Zeroizing::new([7; 32]),
        AotCompilerLimits {
            maximum_output_bytes: 8,
            ..Default::default()
        },
    )
    .unwrap();
    let key = key();
    let mut spare_capacity = Vec::with_capacity(16);
    spare_capacity.extend_from_slice(b"tiny");
    for (bytes, reserved) in [(spare_capacity, 8), (vec![0; 9], 16), (Vec::new(), 8)] {
        let budget = Budget::new(AotResourceLimits::default()).unwrap();
        let (work, permit) = budget.reserve(1, 1, reserved).unwrap();
        drop(work);
        assert_eq!(budget.snapshot().native_bytes, reserved);
        assert_eq!(budget.snapshot().output_owners, 1);
        let error = authority
            .seal_completed(CompletedAotJob::fixture(key.clone(), bytes, permit))
            .unwrap_err();
        assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
        assert_eq!(budget.snapshot(), AotResourceSnapshot::default());
    }
}

#[test]
fn exact_output_and_recomputed_digest_remain_bound_to_the_host_key() {
    let limits = AotCompilerLimits::default();
    let authority =
        TrustedAotCompilerAuthority::new("compiler", Zeroizing::new([7; 32]), limits).unwrap();
    let other =
        TrustedAotCompilerAuthority::new("compiler", Zeroizing::new([8; 32]), limits).unwrap();
    let profile =
        super::super::ValidatedAotProfile::from_config(&crate::WasmtimeConfig::default(), limits)
            .unwrap();
    let key = super::super::identity::fixture(&profile);
    let original = blob(Sha256::digest(b"native-output").into());
    let replacement = blob(Sha256::digest(b"forged-output").into());
    let seal = authority.seal_value(&key, &original, 13);
    assert_ne!(seal, authority.seal_value(&key, &replacement, 13));
    assert_ne!(seal, authority.seal_value(&key, &original, 12));
    assert_ne!(seal, other.seal_value(&key, &original, 13));
    assert!(TrustedAotCompilerAuthority::new("compiler", Zeroizing::new([0; 32]), limits).is_err());
}
