use super::*;
use base64::{engine::general_purpose::STANDARD, Engine};
use latent_artifacts::package::artifact_blob_digest;
use serde_json::Value;

fn claims() -> SignatureClaims {
    SignatureClaims {
        format_version: 1,
        publisher_id: PublisherId("publisher:example".to_owned()),
        subject: PackageSubject {
            media_type: OCI_MANIFEST_MEDIA_TYPE.to_owned(),
            digest: format!("sha256:{}", "a".repeat(64)).parse().unwrap(),
            size: 5000,
        },
        issued_at: 100,
        expires_at: 200,
    }
}

fn envelope(payload: &[u8]) -> Vec<u8> {
    encode_signature(
        payload,
        [0; 64],
        &artifact_blob_digest(b"public key selection hint"),
        SignatureLimits::default(),
    )
    .unwrap()
}

#[test]
fn exact_claims_bytes_survive_inspection_and_pae_counts_utf8_bytes() {
    let canonical = encode_claims(&claims(), SignatureLimits::default()).unwrap();
    let mut spaced = b" \n".to_vec();
    spaced.extend_from_slice(&canonical);
    spaced.extend_from_slice(b"\t");
    let inspected = inspect_signature(&envelope(&spaced), SignatureLimits::default()).unwrap();
    assert_eq!(inspected.payload_bytes(), spaced);
    assert_eq!(
        inspected.publisher_id(),
        &PublisherId("publisher:example".into())
    );
    assert_eq!(inspected.subject().size, 5000);
    assert_ne!(
        pae(SIGNATURE_PAYLOAD_TYPE, &canonical).unwrap(),
        pae(SIGNATURE_PAYLOAD_TYPE, &spaced).unwrap()
    );
    assert_eq!(
        pae("http://example.com/HelloWorld", b"hello world").unwrap(),
        b"DSSEv1 29 http://example.com/HelloWorld 11 hello world"
    );
    assert_eq!(
        pae("é", "💡".as_bytes()).unwrap(),
        "DSSEv1 2 é 4 💡".as_bytes()
    );
}

#[test]
fn wire_shapes_reject_duplicate_unknown_fractional_and_unsupported_fields() {
    let limits = SignatureLimits::default();
    let payload = encode_claims(&claims(), limits).unwrap();
    let encoded = String::from_utf8(envelope(&payload)).unwrap();
    for changed in [
        encoded.replacen('{', "{\"unknown\":1,", 1),
        encoded.replace(
            "\"payloadType\":",
            "\"payloadType\":\"ignored\",\"payloadType\":",
        ),
        encoded.replace("\"signatures\":[", "\"certificates\":[],\"signatures\":["),
        encoded.replace("\"keyid\":", "\"algorithm\":\"Ed25519\",\"keyid\":"),
        encoded.replace(SIGNATURE_PAYLOAD_TYPE, "application/json"),
    ] {
        assert!(inspect_signature(changed.as_bytes(), limits).is_err());
    }
    let text = String::from_utf8(payload).unwrap();
    for changed in [
        text.replace("\"formatVersion\":1", "\"formatVersion\":2"),
        text.replace("\"issuedAt\":100", "\"issuedAt\":1e2"),
        text.replace("\"issuedAt\":100", "\"issuedAt\":100.0"),
        text.replace("\"issuedAt\":100", "\"issuedAt\":-0"),
        text.replace("\"issuedAt\":100", "\"issuedAt\":18446744073709551616"),
        text.replace("\"issuedAt\":100", "\"issuedAt\":100,\"issuedAt\":100"),
        text.replace("\"issuedAt\":100", "\"issuedAt\":100,\"unknown\":1"),
        text.replace("\"publisher:example\"", "null"),
    ] {
        let mut value: Value = serde_json::from_str(&encoded).unwrap();
        value["payload"] = STANDARD.encode(changed).into();
        assert!(inspect_signature(&serde_json::to_vec(&value).unwrap(), limits).is_err());
    }
}

#[test]
fn base64_and_collection_limits_are_enforced_before_retained_decoding() {
    let limits = SignatureLimits::default();
    let payload = encode_claims(&claims(), limits).unwrap();
    let good: Value = serde_json::from_slice(&envelope(&payload)).unwrap();
    let mut maximal = payload;
    maximal.resize(limits.max_payload_bytes, b' ');
    let maximal_envelope = envelope(&maximal);
    assert_eq!(
        inspect_signature(&maximal_envelope, limits)
            .unwrap()
            .payload_bytes(),
        maximal
    );
    for changed in [
        "A".repeat(87),                   // Missing canonical padding/length.
        format!("{}B==", "A".repeat(85)), // Nonzero discarded bits.
        format!("_{}==", "A".repeat(85)), // URL-safe alphabet unsupported by this profile.
        STANDARD.encode([0; 65]),
    ] {
        let mut value = good.clone();
        value["signatures"][0]["sig"] = changed.into();
        assert!(inspect_signature(&serde_json::to_vec(&value).unwrap(), limits).is_err());
    }
    for signatures in [
        serde_json::json!([]),
        serde_json::json!([good["signatures"][0], good["signatures"][0]]),
    ] {
        let mut value = good.clone();
        value["signatures"] = signatures;
        assert!(inspect_signature(&serde_json::to_vec(&value).unwrap(), limits).is_err());
    }
    let mut value = good;
    value["payload"] = STANDARD.encode(vec![b' '; 2049]).into();
    assert_eq!(
        inspect_signature(&serde_json::to_vec(&value).unwrap(), limits)
            .unwrap_err()
            .reason(),
        SignatureFailure::ResourceLimit
    );
}

#[test]
fn typed_inputs_and_exact_document_boundaries_match_decoder_limits() {
    let limits = SignatureLimits::default();
    let claims = claims();
    let payload = encode_claims(&claims, limits).unwrap();
    let bytes = envelope(&payload);
    let exact = SignatureLimits {
        max_payload_bytes: payload.len(),
        max_envelope_bytes: bytes.len(),
        ..limits
    };
    assert_eq!(encode_claims(&claims, exact).unwrap(), payload);
    assert_eq!(
        encode_signature(
            &payload,
            [0; 64],
            &artifact_blob_digest(b"public key selection hint"),
            exact,
        )
        .unwrap(),
        bytes
    );
    inspect_signature(&bytes, exact).unwrap();
    for lowered in [
        SignatureLimits {
            max_payload_bytes: payload.len() - 1,
            ..exact
        },
        SignatureLimits {
            max_envelope_bytes: bytes.len() - 1,
            ..exact
        },
    ] {
        assert_eq!(
            encode_signature(
                &payload,
                [0; 64],
                &artifact_blob_digest(b"public key selection hint"),
                lowered
            )
            .unwrap_err()
            .reason(),
            SignatureFailure::ResourceLimit
        );
        assert_eq!(
            inspect_signature(&bytes, lowered).unwrap_err().reason(),
            SignatureFailure::ResourceLimit
        );
    }
    let mut oversized = claims;
    oversized.publisher_id.0 = "a".repeat(129);
    assert_eq!(
        encode_claims(&oversized, limits).unwrap_err().reason(),
        SignatureFailure::ResourceLimit
    );
    oversized.publisher_id.0 = "publisher with spaces".into();
    assert!(encode_claims(&oversized, limits).is_err());
}

#[test]
fn signed_validity_has_positive_bounded_duration_without_integer_overflow() {
    for (issued_at, expires_at) in [
        (0, 0),
        (2, 1),
        (0, MAX_SIGNATURE_LIFETIME_SECONDS + 1),
        (0, u64::MAX),
    ] {
        assert_eq!(
            validate_validity(SignatureValidity {
                issued_at,
                expires_at
            })
            .unwrap_err()
            .reason(),
            SignatureFailure::InvalidValidity
        );
    }
    validate_validity(SignatureValidity {
        issued_at: 0,
        expires_at: MAX_SIGNATURE_LIFETIME_SECONDS,
    })
    .unwrap();
    validate_validity(SignatureValidity {
        issued_at: u64::MAX - 1,
        expires_at: u64::MAX,
    })
    .unwrap();
}
