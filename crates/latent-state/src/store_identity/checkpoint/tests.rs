use super::*;

fn checkpoint() -> ExternalCheckpoint {
    ExternalCheckpoint::initial(
        StoreIdentity::new("production-A".into()).unwrap(),
        2,
        3,
        4000,
    )
    .unwrap()
}

fn resign(bytes: &mut [u8]) {
    let end = bytes.len() - CHECKSUM_BYTES;
    let checksum = Sha256::digest(&bytes[..end]);
    bytes[end..].copy_from_slice(&checksum);
}

#[test]
fn closed_checkpoint_roundtrip_preserves_identity_and_all_monotonic_floors() {
    let original = checkpoint();
    assert_eq!(
        ExternalCheckpoint::decode(&original.encode()).unwrap(),
        original
    );
    let next = original.advance(3, 4, 5000).unwrap();
    assert_eq!(next.generation(), 2);
    assert_eq!(next.protected_clock_epoch(), 3);
    assert_eq!(next.dispatch_owner_epoch(), 4);
    assert_eq!(next.clock_floor_millis(), 5000);
    assert_eq!(next.identity(), original.identity());
    assert_eq!(ExternalCheckpoint::decode(&next.encode()).unwrap(), next);
    assert!(original.check_store(original.identity(), 3, 4000).is_ok());
    assert!(original.check_store(original.identity(), 3, 4500).is_ok());
    assert_eq!(
        original.check_store(original.identity(), 2, 4000),
        Err(StoreError::Conflict)
    );
    assert_eq!(
        original.check_store(original.identity(), 4, 4000),
        Err(StoreError::Conflict)
    );
    assert_eq!(
        original.check_store(original.identity(), 3, 3999),
        Err(StoreError::Conflict)
    );
    assert_eq!(
        original.check_store(&StoreIdentity::new("production-B".into()).unwrap(), 3, 4000),
        Err(StoreError::Corrupt)
    );
}

#[test]
fn closed_checkpoint_truncation_checksum_changes_and_trailing_bytes_never_decode() {
    let encoded = checkpoint().encode();
    for length in 0..encoded.len() {
        assert!(ExternalCheckpoint::decode(&encoded[..length]).is_err());
    }
    for index in 5..encoded.len() {
        let mut changed = encoded.clone();
        changed[index] ^= 1;
        assert_eq!(
            ExternalCheckpoint::decode(&changed),
            Err(StoreError::Corrupt)
        );
    }
    let mut trailing = encoded;
    trailing.push(0);
    assert_eq!(
        ExternalCheckpoint::decode(&trailing),
        Err(StoreError::Corrupt)
    );
    assert_eq!(
        ExternalCheckpoint::decode(&vec![0; ExternalCheckpoint::MAXIMUM_ENCODED_BYTES + 1]),
        Err(StoreError::Corrupt)
    );
}

#[test]
fn closed_checkpoint_rejects_unknown_formats_and_checksummed_invalid_fields() {
    let encoded = checkpoint().encode();
    let mut unknown = encoded.clone();
    unknown[4] = 2;
    resign(&mut unknown);
    assert_eq!(
        ExternalCheckpoint::decode(&unknown),
        Err(StoreError::UnsupportedFormat)
    );
    for index in 0..4 {
        let mut zero = encoded.clone();
        zero[7 + index * 8..7 + (index + 1) * 8].fill(0);
        resign(&mut zero);
        assert_eq!(ExternalCheckpoint::decode(&zero), Err(StoreError::Corrupt));
    }
    let mut invalid_identity = encoded.clone();
    invalid_identity[HEADER_BYTES] = b'/';
    resign(&mut invalid_identity);
    assert_eq!(
        ExternalCheckpoint::decode(&invalid_identity),
        Err(StoreError::Corrupt)
    );
    let mut oversized_identity = encoded;
    oversized_identity[5..7].copy_from_slice(&129_u16.to_be_bytes());
    resign(&mut oversized_identity);
    assert_eq!(
        ExternalCheckpoint::decode(&oversized_identity),
        Err(StoreError::Corrupt)
    );
}

#[test]
fn closed_checkpoint_cannot_regress_any_floor_or_wrap_its_generation() {
    let original = checkpoint();
    for fields in [(1, 3, 4000), (2, 2, 4000), (2, 3, 3999)] {
        assert_eq!(
            original.advance(fields.0, fields.1, fields.2),
            Err(StoreError::Conflict)
        );
    }
    let mut encoded = original.encode();
    encoded[7..15].copy_from_slice(&u64::MAX.to_be_bytes());
    resign(&mut encoded);
    let exhausted = ExternalCheckpoint::decode(&encoded).unwrap();
    assert_eq!(exhausted.advance(2, 3, 4000), Err(StoreError::Capacity));
    for fields in [(0, 3, 4000), (2, 0, 4000), (2, 3, 0)] {
        assert_eq!(
            ExternalCheckpoint::initial(original.identity().clone(), fields.0, fields.1, fields.2),
            Err(StoreError::Invalid)
        );
    }
}
