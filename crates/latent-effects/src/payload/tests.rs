use crate::authority::{
    CommitLink, DispatchCeiling, DispatchProfile, EffectAuthorityOwner, EffectRule, EffectScope,
    EffectTime,
};

use super::*;

pub(crate) fn value() -> Value {
    Value {
        bytes: b"retained payload".to_vec(),
        media_type: "application/octet-stream".into(),
        metadata: vec![("z".into(), "last".into()), ("a".into(), "first".into())],
    }
}

pub(crate) fn authority(value: &Value, effect: &str) -> DurableEffectAuthority {
    let owner = EffectAuthorityOwner::new(1, 1, 100).unwrap();
    let rule = EffectRule {
        scope: EffectScope {
            tenant: "tenant-a".into(),
            namespace: "orders".into(),
            incarnation: 7,
            publication: "publication-old".into(),
            binding: "events".into(),
            operation: "publish".into(),
        },
        profile: DispatchProfile {
            provider: "provider-a".into(),
            destination: "orders.events".into(),
            adapter: "test-adapter.v1".into(),
            intent_format: 1,
            payload_format: "value.v1".into(),
            idempotency_profile: "none.v1".into(),
        },
        policy_revision: 1,
        credential_epoch: 1,
        protected_credential_reference: "provider-a-secret".into(),
        ceiling: DispatchCeiling {
            maximum_payload_bytes: VALUE_BYTES as u64,
            maximum_response_bytes: 1024,
            maximum_attempts: 3,
            maximum_age_millis: 1000,
            attempt_timeout_millis: 100,
        },
        enabled: true,
    };
    owner.publish(rule.clone()).unwrap();
    owner
        .capture(
            &rule.scope,
            CommitLink {
                command: "command-a".into(),
                caller_scope: "caller-a".into(),
                attempt: 1,
                commit: "commit-a".into(),
                effect: effect.into(),
                sequence: 0,
            },
            value.bytes.len() as u64,
            payload_digest(value).unwrap(),
            EffectTime {
                unix_millis: 100,
                continuity_proven: true,
            },
        )
        .unwrap()
}

#[test]
fn canonical_payload_identity_sorts_metadata_and_binds_media_and_binary_bytes() {
    let original = value();
    let digest = payload_digest(&original).unwrap();
    let mut reordered = original.clone();
    reordered.metadata.reverse();
    assert_eq!(payload_digest(&reordered).unwrap(), digest);
    let authority = authority(&original, &"a".repeat(64));
    let record = PayloadRecord::new(&authority, original.clone()).unwrap();
    assert_eq!(record.value().metadata[0].0, "a");
    assert_eq!(record.effect(), "a".repeat(64));
    let decoded = PayloadRecord::decode(&record.encode().unwrap()).unwrap();
    assert_eq!(decoded, record);
    decoded.verify(&authority).unwrap();

    let mut changed = original.clone();
    changed.media_type = "text/plain".into();
    assert_ne!(payload_digest(&changed).unwrap(), digest);
    assert_eq!(
        PayloadRecord::new(&authority, changed),
        Err(AuthorityError::Invalid)
    );
    let mut changed = original.clone();
    changed.bytes[0] ^= 1;
    assert_ne!(payload_digest(&changed).unwrap(), digest);
    assert_eq!(
        PayloadRecord::new(&authority, changed),
        Err(AuthorityError::Invalid)
    );
    let mut changed = original;
    changed.metadata[0].1 = "replacement".into();
    assert_ne!(payload_digest(&changed).unwrap(), digest);
}

#[test]
fn payload_decoder_checks_all_lengths_counts_utf8_formats_and_trailing_bytes() {
    let value = value();
    let authority = authority(&value, &"1".repeat(64));
    let encoded = PayloadRecord::new(&authority, value)
        .unwrap()
        .encode()
        .unwrap();
    for cut in 0..encoded.len() {
        assert!(PayloadRecord::decode(&encoded[..cut]).is_err(), "cut {cut}");
    }
    let mut unknown = encoded.clone();
    unknown[4] = 2;
    assert_eq!(
        PayloadRecord::decode(&unknown),
        Err(AuthorityError::UnsupportedFormat)
    );
    let mut unknown_value = encoded.clone();
    unknown_value[45] = 2;
    assert_eq!(
        PayloadRecord::decode(&unknown_value),
        Err(AuthorityError::UnsupportedFormat)
    );
    let mut oversized = encoded.clone();
    oversized[37..41].copy_from_slice(&u32::MAX.to_le_bytes());
    assert_eq!(
        PayloadRecord::decode(&oversized),
        Err(AuthorityError::Capacity)
    );
    let mut oversized_payload = encoded.clone();
    oversized_payload[46..50].copy_from_slice(&u32::MAX.to_le_bytes());
    assert_eq!(
        PayloadRecord::decode(&oversized_payload),
        Err(AuthorityError::Capacity)
    );
    let mut trailing = encoded.clone();
    trailing.push(0);
    assert_eq!(
        PayloadRecord::decode(&trailing),
        Err(AuthorityError::Invalid)
    );

    let empty = Value {
        bytes: vec![],
        media_type: "x".into(),
        metadata: vec![],
    };
    let captured = self::authority(&empty, &"f".repeat(64));
    let mut malformed = PayloadRecord::new(&captured, empty)
        .unwrap()
        .encode()
        .unwrap();
    malformed[52] = 0xff;
    assert_eq!(
        PayloadRecord::decode(&malformed),
        Err(AuthorityError::Invalid)
    );
    let mut excessive_count = malformed;
    excessive_count[52] = b'x';
    excessive_count[53..55].copy_from_slice(&u16::MAX.to_le_bytes());
    assert_eq!(
        PayloadRecord::decode(&excessive_count),
        Err(AuthorityError::Capacity)
    );
}

#[test]
fn payload_byte_and_metadata_caps_preserve_empty_presence_and_exact_authority_link() {
    let mut value = Value {
        bytes: vec![0; VALUE_BYTES],
        media_type: "application/octet-stream".into(),
        metadata: (0..8)
            .map(|index| (format!("k{index}"), "x".repeat(1020)))
            .collect(),
    };
    let authority = authority(&value, &"e".repeat(64));
    let record = PayloadRecord::new(&authority, value.clone()).unwrap();
    assert!(record.encode().unwrap().len() <= MAXIMUM_PAYLOAD_RECORD_BYTES);
    assert_eq!(
        PayloadRecord::decode(&record.encode().unwrap()).unwrap(),
        record
    );
    value.bytes.push(0);
    assert_eq!(payload_digest(&value), Err(AuthorityError::Capacity));
    value.bytes.clear();
    value.metadata.push(("overflow".into(), "x".repeat(1024)));
    assert_eq!(payload_digest(&value), Err(AuthorityError::Capacity));
    value.metadata = vec![
        ("duplicate".into(), String::new()),
        ("duplicate".into(), "x".into()),
    ];
    assert_eq!(payload_digest(&value), Err(AuthorityError::Invalid));
    value.metadata.clear();
    let different = self::authority(&value, &"d".repeat(64));
    assert_eq!(record.verify(&different), Err(AuthorityError::Invalid));
    let empty = PayloadRecord::new(&different, value).unwrap();
    assert!(empty.value().bytes.is_empty());
    assert_eq!(
        PayloadRecord::decode(&empty.encode().unwrap()).unwrap(),
        empty
    );
}

#[test]
fn tampered_retained_payload_cannot_dispatch_with_the_original_authority() {
    let value = value();
    let authority = authority(&value, &"9".repeat(64));
    let record = PayloadRecord::new(&authority, value).unwrap();
    let mut encoded = record.encode().unwrap();
    encoded[50] ^= 1;
    let decoded = PayloadRecord::decode(&encoded).unwrap();
    assert_eq!(decoded.verify(&authority), Err(AuthorityError::Invalid));
    let mut changed_effect = record.encode().unwrap();
    changed_effect[5] ^= 1;
    let decoded = PayloadRecord::decode(&changed_effect).unwrap();
    assert_eq!(decoded.verify(&authority), Err(AuthorityError::Invalid));
}
