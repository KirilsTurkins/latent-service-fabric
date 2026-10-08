use super::*;

fn ledger(accounted: bool) -> Vec<u8> {
    let mut bytes = if accounted {
        super::super::QUOTA_MAGIC
    } else {
        LEGACY_MAGIC
    }
    .to_vec();
    for value in [1u64, 1024, 1, 2048, 128, 256, 128] {
        bytes.extend_from_slice(&value.to_le_bytes());
    }
    if accounted {
        bytes.resize(super::super::QUOTA_BYTES, 0);
    }
    bytes
}

#[test]
fn supported_namespace_ledgers_preserve_exact_legacy_and_accounted_formats() {
    for (accounted, version) in [(false, 1), (true, 2)] {
        let original = ledger(accounted);
        let decoded = NamespaceLedger::decode(&original).unwrap();
        assert_eq!(decoded.is_accounted(), accounted);
        assert_eq!(
            decoded.durable_format(),
            ("latent.command-usage.v1", version)
        );
        assert_eq!(decoded.encode(), original);
    }
}

#[test]
fn metadata_delta_changes_only_its_original_effect_counter_without_renewing_clock() {
    let mut original = ledger(true);
    let mut clock = CLOCK_MAGIC.to_vec();
    clock.extend_from_slice(&[7; 32]);
    for value in [1u64, 1000, 20, 900, 0, 5, 3, 40] {
        clock.extend_from_slice(&value.to_le_bytes());
    }
    clock.extend_from_slice(&0u16.to_le_bytes());
    original[61..63].copy_from_slice(&(CLOCK_BYTES as u16).to_le_bytes());
    original[63..63 + CLOCK_BYTES].copy_from_slice(&clock);
    let mut decoded = NamespaceLedger::decode(&original).unwrap();
    decoded.adjust_effect_bytes(48, 120).unwrap();
    let encoded = decoded.encode();
    assert_eq!(&encoded[..29], &original[..29]);
    assert_eq!(&encoded[37..], &original[37..]);
    assert_eq!(
        u64::from_le_bytes(encoded[29..37].try_into().unwrap()),
        2120
    );
}

#[test]
fn malformed_clock_padding_unknown_formats_and_counter_relations_fail_closed() {
    let original = ledger(true);
    for end in 0..original.len() {
        assert!(NamespaceLedger::decode(&original[..end]).is_err());
    }
    let mut unknown = original.clone();
    unknown[4] = 3;
    assert!(matches!(
        NamespaceLedger::decode(&unknown),
        Err(StoreError::UnsupportedFormat)
    ));
    let mut padding = original.clone();
    padding[255] = 1;
    assert!(matches!(
        NamespaceLedger::decode(&padding),
        Err(StoreError::Corrupt)
    ));
    let mut length = original.clone();
    length[61..63].copy_from_slice(&146u16.to_le_bytes());
    assert!(matches!(
        NamespaceLedger::decode(&length),
        Err(StoreError::Corrupt)
    ));
    let mut uncovered = original;
    uncovered[53..61].copy_from_slice(&257u64.to_le_bytes());
    assert!(matches!(
        NamespaceLedger::decode(&uncovered),
        Err(StoreError::Corrupt)
    ));
}

#[test]
fn quota_and_arithmetic_refusal_preserve_original_ledger_and_legacy_never_auto_migrates() {
    let original = ledger(true);
    let mut decoded = NamespaceLedger::decode(&original).unwrap();
    assert_eq!(
        decoded.adjust_effect_bytes(2049, 0),
        Err(StoreError::Corrupt)
    );
    assert_eq!(decoded.encode(), original);
    assert_eq!(
        decoded.adjust_effect_bytes(0, u64::MAX),
        Err(StoreError::Capacity)
    );
    assert_eq!(decoded.encode(), original);
    let mut quota = crate::namespace::NamespaceQuota::default();
    quota.effect_bytes = 2047;
    let namespace = NamespaceRecord::create(
        TenantId("tenant".into()),
        StateNamespaceId("state".into()),
        format!("sha256:{}", "1".repeat(64)),
        quota,
    )
    .unwrap();
    assert_eq!(decoded.check(&namespace), Err(StoreError::Capacity));
    assert_eq!(decoded.encode(), original);
    let original = ledger(false);
    let mut legacy = NamespaceLedger::decode(&original).unwrap();
    assert_eq!(
        legacy.adjust_effect_bytes(0, 1),
        Err(StoreError::UnsupportedFormat)
    );
    assert_eq!(legacy.encode(), original);
}
