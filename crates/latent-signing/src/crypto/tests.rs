use ed25519_dalek::VerifyingKey;

use super::{validate_public_key, verify_signature};
use crate::SignatureFailure;

// Independent RFC 8032 section 7.1 vectors. Only public keys, messages and
// signatures are retained; the RFC's private test seeds are deliberately absent.
// https://www.rfc-editor.org/rfc/rfc8032.html#section-7.1
const FIRST_PUBLIC: &str = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a";
const FIRST_SIGNATURE: &str = concat!(
    "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155",
    "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
);

fn hex<const N: usize>(text: &str) -> [u8; N] {
    assert_eq!(text.len(), N * 2);
    let mut bytes = [0; N];
    for (index, byte) in bytes.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&text[index * 2..index * 2 + 2], 16).unwrap();
    }
    bytes
}

#[test]
fn independent_rfc8032_public_vectors_verify() {
    verify_signature(&hex(FIRST_PUBLIC), b"", &hex(FIRST_SIGNATURE)).unwrap();
    verify_signature(
        &hex("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c"),
        &[0x72],
        &hex(concat!(
            "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da",
            "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"
        )),
    )
    .unwrap();
}

#[test]
fn modified_message_signature_and_public_identity_fail() {
    let public = hex(FIRST_PUBLIC);
    let signature = hex(FIRST_SIGNATURE);
    assert_eq!(
        verify_signature(&public, b"changed", &signature)
            .unwrap_err()
            .reason(),
        SignatureFailure::InvalidSignature
    );
    let mut modified = signature;
    modified[0] ^= 1;
    assert!(verify_signature(&public, b"", &modified).is_err());
    let different = hex("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c");
    assert!(verify_signature(&different, b"", &signature).is_err());
}

#[test]
fn scalar_malleability_is_rejected_even_with_legacy_feature_unification() {
    let mut signature = hex::<64>(FIRST_SIGNATURE);
    let order = hex::<32>("edd3f55c1a631258d69cf7a2def9de1400000000000000000000000000000010");
    // S + group order has the same scalar action but a forbidden encoding. This
    // public test mutation verifies our upstream canonical-parser guard remains
    // effective if another dependency enables Dalek's legacy compatibility.
    let mut carry = 0u16;
    for (byte, addend) in signature[32..].iter_mut().zip(order) {
        let sum = u16::from(*byte) + u16::from(addend) + carry;
        let [low, high] = sum.to_le_bytes();
        *byte = low;
        carry = u16::from(high);
    }
    assert_eq!(carry, 0);
    assert_eq!(
        verify_signature(&hex(FIRST_PUBLIC), b"", &signature)
            .unwrap_err()
            .reason(),
        SignatureFailure::InvalidSignature
    );
}

#[test]
fn weak_and_noncanonical_public_keys_cannot_be_anchors() {
    let mut identity = [0; 32];
    identity[0] = 1;
    for weak in [[0; 32], identity] {
        assert!(VerifyingKey::from_bytes(&weak).unwrap().is_weak());
        assert_eq!(
            validate_public_key(&weak).unwrap_err().reason(),
            SignatureFailure::InvalidKey
        );
    }

    // The 19 encodings at/above the field modulus exercise ZIP215 decoding.
    // Require a non-weak decoded point so this specifically tests canonical
    // encoding, independently from the preceding small-order rejection.
    let mut found_nonweak = false;
    for low in 0xed..=0xff {
        let mut encoded = [0xff; 32];
        encoded[0] = low;
        encoded[31] = 0x7f;
        if let Ok(key) = VerifyingKey::from_bytes(&encoded) {
            if !key.is_weak() {
                assert_ne!(key.to_edwards().compress().to_bytes(), encoded);
                assert!(validate_public_key(&encoded).is_err());
                found_nonweak = true;
            }
        }
    }
    assert!(found_nonweak);
}

#[test]
fn weak_or_noncanonical_signature_r_is_rejected() {
    let mut signature = hex::<64>(FIRST_SIGNATURE);
    signature[..32].fill(0);
    assert!(verify_signature(&hex(FIRST_PUBLIC), b"", &signature).is_err());
    signature[..32].fill(0xff);
    signature[0] = 0xee;
    signature[31] = 0x7f;
    assert!(verify_signature(&hex(FIRST_PUBLIC), b"", &signature).is_err());
}
