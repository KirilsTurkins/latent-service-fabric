use ed25519::pkcs8::{
    BitStringRef, ObjectIdentifier, OctetStringRef, PrivateKeyInfoRef, SecretDocument,
};
use ed25519_dalek::Signer;
use latent_core::PublisherId;
use zeroize::Zeroizing;

use super::{generate_signing_key, import_key};
use crate::{crypto::verify_signature, LocalSigner, SignatureFailure};

fn encode(info: &PrivateKeyInfoRef<'_>) -> Zeroizing<Vec<u8>> {
    let document = SecretDocument::encode_msg(info).unwrap();
    Zeroizing::new(document.as_bytes().to_vec())
}

#[test]
fn generated_v2_key_reimports_and_signs_without_private_fixtures() {
    let generated = generate_signing_key().unwrap();
    assert_eq!(
        format!("{generated:?}"),
        "GeneratedSigningKey { private_key: [REDACTED] }"
    );
    let public = *generated.public_key();
    let bytes = generated.into_pkcs8();
    let info = PrivateKeyInfoRef::try_from(bytes.as_slice()).unwrap();
    assert_eq!(info.public_key.unwrap().as_bytes(), Some(public.as_slice()));
    // The library DER parser enforces that this public field is present iff the
    // encoded version is V2, so this is also a version regression assertion.
    let key = import_key(bytes, &public).unwrap();
    let message = b"ephemeral host-key round trip";
    verify_signature(&public, message, &key.sign(message).to_bytes()).unwrap();
}

#[test]
fn approved_identity_and_embedded_seed_association_are_checked() {
    let generated = generate_signing_key().unwrap();
    let public = *generated.public_key();
    let bytes = generated.into_pkcs8();
    let other = generate_signing_key().unwrap();
    assert_eq!(
        import_key(bytes.clone(), other.public_key())
            .unwrap_err()
            .reason(),
        SignatureFailure::UnapprovedKey
    );
    let mut info = PrivateKeyInfoRef::try_from(bytes.as_slice()).unwrap();
    let mut changed_seed = Zeroizing::new(info.private_key.as_bytes().to_vec());
    changed_seed[2] ^= 1;
    info.private_key = OctetStringRef::new(&changed_seed).unwrap();
    assert_eq!(
        import_key(encode(&info), &public).unwrap_err().reason(),
        SignatureFailure::InvalidKey
    );
}

#[test]
fn absent_or_non_aligned_public_field_and_wrong_algorithm_are_rejected() {
    let generated = generate_signing_key().unwrap();
    let public = *generated.public_key();
    let bytes = generated.into_pkcs8();
    let mut info = PrivateKeyInfoRef::try_from(bytes.as_slice()).unwrap();
    info.public_key = None;
    assert_eq!(
        import_key(encode(&info), &public).unwrap_err().reason(),
        SignatureFailure::InvalidKey
    );

    let mut unaligned = public;
    unaligned[31] &= 0xfe;
    info.public_key = Some(BitStringRef::new(1, &unaligned).unwrap());
    assert_eq!(
        import_key(encode(&info), &public).unwrap_err().reason(),
        SignatureFailure::InvalidKey
    );

    info.public_key = Some(BitStringRef::new(0, &public).unwrap());
    info.algorithm.oid = ObjectIdentifier::new_unwrap("1.3.101.110");
    assert_eq!(
        import_key(encode(&info), &public).unwrap_err().reason(),
        SignatureFailure::InvalidKey
    );
}

#[test]
fn malformed_trailing_and_oversized_inputs_are_bounded_rejections() {
    let generated = generate_signing_key().unwrap();
    let public = *generated.public_key();
    let mut trailing = generated.into_pkcs8();
    trailing.push(0);
    for invalid in [
        trailing,
        Zeroizing::new(Vec::new()),
        Zeroizing::new(b"-----BEGIN PRIVATE KEY-----".to_vec()),
    ] {
        assert_eq!(
            import_key(invalid, &public).unwrap_err().reason(),
            SignatureFailure::InvalidKey
        );
    }
    assert_eq!(
        import_key(Zeroizing::new(vec![0; 4097]), &public)
            .unwrap_err()
            .reason(),
        SignatureFailure::ResourceLimit
    );
}

#[test]
fn signer_has_redacted_diagnostics_and_rejects_invalid_publisher() {
    let generated = generate_signing_key().unwrap();
    let public = *generated.public_key();
    let bytes = generated.into_pkcs8();
    assert!(LocalSigner::from_pkcs8(bytes.clone(), PublisherId("bad id".into()), public).is_err());
    let signer =
        LocalSigner::from_pkcs8(bytes, PublisherId("publisher:test".into()), public).unwrap();
    assert_eq!(
        format!("{signer:?}"),
        "LocalSigner { private_key: [REDACTED] }"
    );
}
