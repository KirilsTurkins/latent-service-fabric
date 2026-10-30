//! Journal policy is not a replacement grant for the original whole-node bank.
use super::*;
use std::time::Duration;

#[test]
fn original_node_bank_keeps_its_ceiling_across_derived_journal_policies_and_prebirth_refusal() {
    let directory = super::super::tests::Directory::new();
    for records in [2, 1024, 4096] {
        let limits = AuditLimits {
            maximum_records: records,
            maximum_metadata_bytes: (records * 2048).max(128 * 1024 + records * 1536),
            maximum_queued_operations: 8,
            ..Default::default()
        };
        let owner = NodeMetadataOwner::new(8 * 1024 * 1024).unwrap();
        let base = owner.occupied_bytes();
        let path = directory.0.join(format!("records-{records}"));
        let (handle, mut worker) =
            DirectoryPhase2AuditJournal::open_with_node_bank(&path, limits, owner.clone()).unwrap();
        let snapshot = handle.snapshot();
        assert_eq!(snapshot.node_metadata_maximum_bytes, 8 * 1024 * 1024);
        assert_eq!(
            snapshot.node_metadata_reserved_bytes,
            owner.occupied_bytes()
        );
        assert!(snapshot.node_metadata_fixed_reserved_bytes > base);
        assert_eq!(snapshot.node_metadata_transient_reserved_bytes, 0);
        assert!(owner.occupied_bytes() < owner.maximum_bytes());
        handle.close();
        assert!(worker
            .join_until(Instant::now() + Duration::from_secs(5))
            .unwrap());
        drop(worker);
        drop(handle);
        assert_eq!(owner.occupied_bytes(), base);
    }
    let owner = NodeMetadataOwner::new(8 * 1024 * 1024).unwrap();
    let before = owner.snapshot();
    let path = directory.0.join("oversized-fixed-backing");
    let limits = AuditLimits {
        maximum_records: 16384,
        maximum_metadata_bytes: 32 * 1024 * 1024,
        ..Default::default()
    };
    limits.validate().unwrap(); // Schema validity cannot grant physical readiness.
    assert_eq!(
        DirectoryPhase2AuditJournal::open_with_node_bank(&path, limits, owner.clone())
            .err()
            .unwrap()
            .code,
        latent_core::PlatformErrorCode::ResourceExhausted
    );
    assert!(!path.exists());
    assert_eq!(owner.snapshot(), before);
}
