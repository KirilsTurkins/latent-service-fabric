use super::*;
use crate::embedded::{AtomicBatch, Family, RowKey, RowMutation, StoreError};

#[test]
fn legacy_selection_refuses_protected_accounting_and_progress_without_rewriting_rows() {
    for prefix in [
        crate::tenant::guard_key().key,
        super::super::migration::PROGRESS_PREFIX.to_vec(),
        super::super::resume::RECEIPT_PREFIX.to_vec(),
    ] {
        let fixture = snapshot::tests::fixture();
        assert_eq!(require_profile(&fixture.store.snapshot().unwrap()), Ok(()));
        let key = RowKey {
            family: Family::Maintenance,
            key: prefix,
        };
        let original = b"unsupported-profile-original".to_vec();
        fixture
            .store
            .apply(AtomicBatch {
                expectations: vec![],
                mutations: vec![RowMutation {
                    key: key.clone(),
                    value: Some(original.clone()),
                }],
            })
            .unwrap();
        let view = fixture.store.snapshot().unwrap();
        assert_eq!(require_profile(&view), Err(StoreError::UnsupportedFormat));
        assert_eq!(view.get(&key).unwrap(), Some(original));
    }
}
