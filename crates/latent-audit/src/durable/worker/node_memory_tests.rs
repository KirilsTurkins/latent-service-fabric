use super::*;

#[test]
fn audit_default_fixed_backing_fits_the_original_eight_mib_node_ceiling() {
    let limits = AuditLimits::default();
    assert_eq!(limits.maximum_metadata_bytes, 8 * 1024 * 1024);
    let owner = NodeMetadataOwner::new(limits.maximum_metadata_bytes).unwrap();
    let base = owner.occupied_bytes();
    let outer = SharedOwner::<Mutex<Option<AuditWorker>>>::prepare_fixed(&owner, 0).unwrap();
    let journal =
        SharedOwner::<Shared>::prepare_fixed(&owner, StoreMemory::bytes(limits).unwrap()).unwrap();
    let pages = SharedOwner::<PageBudget>::prepare_fixed(&owner, 0).unwrap();
    assert!(owner.occupied_bytes() < limits.maximum_metadata_bytes);
    let expected = base
        + SharedOwner::<Mutex<Option<AuditWorker>>>::allocation_bytes(0).unwrap()
        + SharedOwner::<Shared>::allocation_bytes(StoreMemory::bytes(limits).unwrap()).unwrap()
        + SharedOwner::<PageBudget>::allocation_bytes(0).unwrap();
    assert_eq!(owner.occupied_bytes(), expected);
    assert_eq!(owner.snapshot().fixed_reserved_bytes, expected);
    assert_eq!(owner.snapshot().transient_reserved_bytes, 0);
    // Preparations themselves allocate only their admitted billing headers.
    drop(pages);
    drop(journal);
    drop(outer);
    assert_eq!(owner.occupied_bytes(), base);
    assert_eq!(limits.maximum_record_bytes, 16384);
    assert_eq!(limits.maximum_disk_bytes, 64 * 1024 * 1024);
}

#[test]
fn audit_funded_birth_refuses_before_filesystem_on_capacity_or_ceiling_mismatch() {
    let limits = AuditLimits::default();
    let path = std::env::temp_dir().join(format!("lsf-audit-no-birth-{}", std::process::id()));
    assert!(!path.exists());
    let mismatched = NodeMetadataOwner::new(limits.maximum_metadata_bytes - 1).unwrap();
    let before = mismatched.occupied_bytes();
    assert_eq!(
        DirectoryPhase2AuditJournal::open_with_node_metadata(&path, limits, mismatched.clone())
            .err()
            .unwrap()
            .code,
        latent_core::PlatformErrorCode::InvalidArgument
    );
    assert_eq!(mismatched.occupied_bytes(), before);
    assert!(!path.exists());
    let owner = NodeMetadataOwner::new(limits.maximum_metadata_bytes).unwrap();
    let occupied = owner
        .reserve(limits.maximum_metadata_bytes - owner.occupied_bytes())
        .unwrap();
    assert_eq!(
        DirectoryPhase2AuditJournal::open_with_node_metadata(&path, limits, owner.clone())
            .err()
            .unwrap()
            .code,
        latent_core::PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(owner.occupied_bytes(), limits.maximum_metadata_bytes);
    assert!(!path.exists());
    drop(occupied);
    assert_eq!(
        owner.occupied_bytes(),
        NodeMetadataOwner::bootstrap_bytes().unwrap()
    );
}

#[cfg(unix)]
mod live;

#[test]
fn page_record_preflight_accounts_actual_original_graph_before_decode_and_rolls_back_refusal() {
    let owner = NodeMetadataOwner::new(8 * 1024 * 1024).unwrap();
    let budget = SharedOwner::unaccounted(PageBudget {
        state: Mutex::new((1, 32768 * 4)),
        owners: 1,
        bytes: 32768 * 4,
    });
    let charge = PageCharge {
        budget,
        bytes: 32768 * 4,
        records: Mutex::new(Vec::with_capacity(2)),
        metadata: Some(owner.clone()),
    };
    let raw = codec::encode(&super::super::tests::attempt(), 16384).unwrap();
    let expected = 3
        * (codec::owned_graph_bound(&raw, 16384).unwrap()
            + std::mem::size_of::<AuditStoredRecord>()
            + 4096);
    let before = owner.occupied_bytes();
    charge.prepare_record(&raw, 16384).unwrap();
    assert_eq!(owner.occupied_bytes(), before + expected);
    let occupied = owner
        .reserve(owner.maximum_bytes() - owner.occupied_bytes())
        .unwrap();
    let full = owner.snapshot();
    assert!(charge.prepare_record(&raw, 16384).is_err());
    assert_eq!(owner.snapshot(), full);
    assert_eq!(charge.records.lock().unwrap().len(), 1);
    drop(occupied);
    drop(charge);
    assert_eq!(owner.occupied_bytes(), before);
}
