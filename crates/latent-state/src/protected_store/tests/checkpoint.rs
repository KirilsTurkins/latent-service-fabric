use super::*;
use crate::store_identity::{ExternalCheckpoint, StoreIdentity};
use latent_core::native_capacity::{
    NativeAdmissionClass, NativeCapacityLimits, NativeCapacityOwner, NativeReservationRequest,
};
use std::os::unix::fs::{FileExt, MetadataExt, OpenOptionsExt};

mod retirement;

const CHECKPOINT_NAME: &str = "transaction-checkpoint.v1";
const OWNER_KEY: &[u8] = b"checkpoint-test-owner";

fn identity() -> StoreIdentity {
    StoreIdentity::new("production-A".into()).unwrap()
}

fn bound(config: ProtectedStoreConfig) -> ProtectedStoreOwner {
    bound_with_clock(config, TestClock::new(1000, Instant::now(), 1))
}

fn bound_with_clock(config: ProtectedStoreConfig, clock: TestClock) -> ProtectedStoreOwner {
    let owner = wait(
        ProtectedStoreOwner::start_bound_validated_view_with_clock(
            config,
            identity(),
            4096,
            |view| {
                super::super::physical::validate_records(view, &mut |key, value| {
                    if key == &StoreIdentity::row_key() {
                        StoreIdentity::validate_row(key, value)
                    } else if key.family == Family::Maintenance && key.key == OWNER_KEY {
                        decode_owner(value).map(|_| ())
                    } else {
                        Err(StoreError::UnsupportedFormat)
                    }
                })
            },
            Arc::new(clock.clone()),
        )
        .unwrap(),
    )
    .unwrap();
    let native =
        NativeCapacityOwner::with_clock(NativeCapacityLimits::default(), Arc::new(clock)).unwrap();
    owner.bind_native_capacity(&native).unwrap();
    owner
}

fn keeper(owner: &ProtectedStoreOwner) -> Arc<latent_core::native_capacity::NativeReservation> {
    Arc::new(
        owner
            .native_capacity()
            .unwrap()
            .reserve(
                NativeAdmissionClass::Recovery,
                NativeReservationRequest {
                    work_bytes: 64 * 1024,
                    ..NativeReservationRequest::default()
                },
                Instant::now() + WATCHDOG,
            )
            .unwrap(),
    )
}

fn witness(owner: &ProtectedStoreOwner) -> Option<StoreInitializationWitness> {
    wait(owner.take_initialization_witness().unwrap())
        .unwrap()
        .unwrap()
}

fn decode_owner(value: &[u8]) -> Result<(u64, u64), StoreError> {
    if value.len() != 16 {
        return Err(StoreError::Corrupt);
    }
    let epoch = u64::from_be_bytes(value[..8].try_into().unwrap());
    let floor = u64::from_be_bytes(value[8..].try_into().unwrap());
    if epoch == 0 || floor == 0 {
        return Err(StoreError::Corrupt);
    }
    Ok((epoch, floor))
}

fn observed(view: &crate::embedded::ReadView) -> Result<Option<(u64, u64)>, StoreError> {
    view.get(&RowKey {
        family: Family::Maintenance,
        key: OWNER_KEY.to_vec(),
    })?
    .as_deref()
    .map(decode_owner)
    .transpose()
}

fn seed_owner(owner: &ProtectedStoreOwner, epoch: u64, floor: u64) {
    let value = [epoch.to_be_bytes(), floor.to_be_bytes()].concat();
    wait(
        owner
            .with_store(StoreIoKind::RecoveryWrite, 4096, move |store| {
                store.apply(AtomicBatch {
                    expectations: vec![],
                    mutations: vec![RowMutation {
                        key: RowKey {
                            family: Family::Maintenance,
                            key: OWNER_KEY.to_vec(),
                        },
                        value: Some(value),
                    }],
                })
            })
            .unwrap(),
    )
    .unwrap()
    .unwrap();
}

fn external() -> tempfile::TempDir {
    let (root, _config) = fixture();
    root
}

fn open(
    owner: &ProtectedStoreOwner,
    root: &tempfile::TempDir,
    fresh: Option<StoreInitializationWitness>,
) -> ProtectedCheckpoint {
    let (checkpoint, initialized) = wait(
        owner
            .open_checkpoint(
                ProtectedCheckpointConfig {
                    root: root.path().to_path_buf(),
                },
                identity(),
                fresh,
                keeper(owner),
                observed,
            )
            .unwrap(),
    )
    .unwrap();
    initialized.unwrap();
    checkpoint
}

#[test]
fn actual_identity_initialization_yields_one_witness_and_matching_reopen_yields_none() {
    let (_business, config) = fixture();
    let owner = bound(config.clone());
    let fresh = witness(&owner).unwrap();
    assert_eq!(fresh.identity(), &identity());
    assert!(witness(&owner).is_none());
    let stored = wait(
        owner
            .with_store(StoreIoKind::RecoveryRead, 4096, |store| {
                StoreIdentity::inspect(&store.snapshot()?)
            })
            .unwrap(),
    )
    .unwrap()
    .unwrap();
    assert_eq!(stored, Some(identity()));
    drop(fresh); // Loss never regenerates Fresh from the stored identity.
    assert!(finish(&owner).clean);

    let reopened = bound(config);
    assert!(witness(&reopened).is_none());
    assert!(finish(&reopened).clean);
}

#[test]
fn checkpoint_initialization_binds_real_floors_and_reopens_without_fresh_permission() {
    let (_business, config) = fixture();
    let external = external();
    let owner = bound(config.clone());
    let fresh = witness(&owner).unwrap();
    let checkpoint = open(&owner, &external, Some(fresh));
    let (checkpoint, inspection) =
        wait(owner.inspect_checkpoint(checkpoint, observed).unwrap()).unwrap();
    assert_eq!(
        inspection.unwrap(),
        CheckpointInspection {
            checkpoint: None,
            dispatch_owner: None
        }
    );
    seed_owner(&owner, 3, 4000);
    let (checkpoint, record) = wait(
        owner
            .advance_checkpoint(checkpoint, None, 2, observed)
            .unwrap(),
    )
    .unwrap();
    let record = record.unwrap();
    assert_eq!(
        record,
        ExternalCheckpoint::initial(identity(), 2, 3, 4000).unwrap()
    );
    assert_eq!(
        ExternalCheckpoint::decode(&fs::read(external.path().join(CHECKPOINT_NAME)).unwrap())
            .unwrap(),
        record
    );
    wait(checkpoint.retire());
    assert!(finish(&owner).clean);

    let reopened = bound(config);
    assert!(witness(&reopened).is_none());
    let checkpoint = open(&reopened, &external, None);
    let (checkpoint, inspected) =
        wait(reopened.inspect_checkpoint(checkpoint, observed).unwrap()).unwrap();
    assert_eq!(inspected.unwrap().checkpoint, Some(record));
    wait(checkpoint.retire());
    assert!(finish(&reopened).clean);
}

#[test]
fn missing_checkpoint_after_identity_write_restart_is_refused_without_creation() {
    let (_business, config) = fixture();
    let external = external();
    let owner = bound(config.clone());
    drop(witness(&owner).unwrap());
    assert!(finish(&owner).clean);

    let reopened = bound(config);
    assert!(witness(&reopened).is_none());
    let (checkpoint, result) = wait(
        reopened
            .open_checkpoint(
                ProtectedCheckpointConfig {
                    root: external.path().to_path_buf(),
                },
                identity(),
                None,
                keeper(&reopened),
                observed,
            )
            .unwrap(),
    )
    .unwrap();
    assert_eq!(
        result,
        Err(ProtectedStoreError::Store(StoreError::Unavailable))
    );
    assert!(!external.path().join(CHECKPOINT_NAME).exists());
    wait(checkpoint.retire());
    let report = finish(&reopened);
    assert!(!report.clean);
    assert!(report.snapshot.physically_retired());
}

#[test]
fn checkpoint_exact_comparison_rejects_stale_updates_and_each_older_persisted_floor() {
    let (_business, config) = fixture();
    let external = external();
    let owner = bound(config);
    let checkpoint = open(&owner, &external, witness(&owner));
    seed_owner(&owner, 3, 4000);
    let (checkpoint, original) = wait(
        owner
            .advance_checkpoint(checkpoint, None, 2, observed)
            .unwrap(),
    )
    .unwrap();
    let original = original.unwrap();
    seed_owner(&owner, 4, 5000);
    let (checkpoint, old_observation) =
        wait(owner.inspect_checkpoint(checkpoint, observed).unwrap()).unwrap();
    assert_eq!(
        old_observation,
        Err(ProtectedStoreError::Store(StoreError::Conflict))
    );
    let (checkpoint, current) = wait(
        owner
            .advance_checkpoint(checkpoint, Some(original.clone()), 3, observed)
            .unwrap(),
    )
    .unwrap();
    let current = current.unwrap();
    let saved = fs::read(external.path().join(CHECKPOINT_NAME)).unwrap();
    let (checkpoint, stale) = wait(
        owner
            .advance_checkpoint(checkpoint, Some(original), 3, observed)
            .unwrap(),
    )
    .unwrap();
    assert_eq!(stale, Err(ProtectedStoreError::Store(StoreError::Conflict)));
    let (checkpoint, old_clock) = wait(
        owner
            .advance_checkpoint(checkpoint, Some(current.clone()), 2, observed)
            .unwrap(),
    )
    .unwrap();
    assert_eq!(
        old_clock,
        Err(ProtectedStoreError::Store(StoreError::Conflict))
    );
    seed_owner(&owner, 3, 5000);
    let (checkpoint, old_epoch) = wait(
        owner
            .advance_checkpoint(checkpoint, Some(current.clone()), 3, observed)
            .unwrap(),
    )
    .unwrap();
    assert_eq!(
        old_epoch,
        Err(ProtectedStoreError::Store(StoreError::Conflict))
    );
    seed_owner(&owner, 4, 4999);
    let (checkpoint, old_floor) = wait(
        owner
            .advance_checkpoint(checkpoint, Some(current), 3, observed)
            .unwrap(),
    )
    .unwrap();
    assert_eq!(
        old_floor,
        Err(ProtectedStoreError::Store(StoreError::Conflict))
    );
    assert_eq!(
        fs::read(external.path().join(CHECKPOINT_NAME)).unwrap(),
        saved
    );
    assert!(owner.failure().is_none());
    wait(checkpoint.retire());
    assert!(finish(&owner).clean);
}

#[test]
fn existing_empty_malformed_and_foreign_checkpoint_bytes_are_never_overwritten() {
    for value in [
        Vec::new(),
        b"LTC\0\x01".to_vec(),
        ExternalCheckpoint::initial(
            StoreIdentity::new("production-B".into()).unwrap(),
            2,
            3,
            4000,
        )
        .unwrap()
        .encode(),
    ] {
        let (_business, config) = fixture();
        let external = external();
        let path = external.path().join(CHECKPOINT_NAME);
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&path)
            .unwrap();
        file.write_all_at(&value, 0).unwrap();
        let inode = file.metadata().unwrap().ino();
        drop(file);
        let owner = bound(config);
        let (checkpoint, result) = wait(
            owner
                .open_checkpoint(
                    ProtectedCheckpointConfig {
                        root: external.path().to_path_buf(),
                    },
                    identity(),
                    witness(&owner),
                    keeper(&owner),
                    observed,
                )
                .unwrap(),
        )
        .unwrap();
        assert_eq!(result, Err(ProtectedStoreError::Store(StoreError::Corrupt)));
        assert_eq!(fs::read(&path).unwrap(), value);
        assert_eq!(fs::metadata(&path).unwrap().ino(), inode);
        wait(checkpoint.retire());
        let report = finish(&owner);
        assert!(!report.clean);
        assert!(report.snapshot.physically_retired());
    }
}

#[test]
fn checkpoint_rejects_foreign_fresh_witness_and_same_actual_business_root() {
    let (_business, config) = fixture();
    let owner = bound(config);
    let (other_business, other_config) = fixture();
    let other = bound(other_config);
    let external = external();
    assert!(matches!(
        other.open_checkpoint(
            ProtectedCheckpointConfig {
                root: external.path().to_path_buf()
            },
            identity(),
            witness(&owner),
            keeper(&other),
            observed,
        ),
        Err(ProtectedStoreError::InvalidConfiguration)
    ));
    assert!(!external.path().join(CHECKPOINT_NAME).exists());
    let (checkpoint, same_root) = wait(
        other
            .open_checkpoint(
                ProtectedCheckpointConfig {
                    root: other_business.path().to_path_buf(),
                },
                identity(),
                witness(&other),
                keeper(&other),
                observed,
            )
            .unwrap(),
    )
    .unwrap();
    assert_eq!(
        same_root,
        Err(ProtectedStoreError::Store(StoreError::Invalid))
    );
    assert!(!other_business.path().join(CHECKPOINT_NAME).exists());
    wait(checkpoint.retire());
    assert!(finish(&owner).clean);
    assert!(finish(&other).clean);
}

#[test]
fn checkpoint_rejects_substituted_global_owner_ordinary_partition_and_unfunded_buffers() {
    let (_business, config) = fixture();
    let owner = bound(config);
    let external = external();
    let foreign = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
    let ordinary = owner
        .native_capacity()
        .unwrap()
        .reserve(
            NativeAdmissionClass::Ordinary,
            NativeReservationRequest {
                work_bytes: 64 * 1024,
                ..NativeReservationRequest::default()
            },
            Instant::now() + WATCHDOG,
        )
        .unwrap();
    let other = foreign
        .reserve(
            NativeAdmissionClass::Recovery,
            NativeReservationRequest {
                work_bytes: 64 * 1024,
                ..NativeReservationRequest::default()
            },
            Instant::now() + WATCHDOG,
        )
        .unwrap();
    let unfunded = owner
        .native_capacity()
        .unwrap()
        .reserve(
            NativeAdmissionClass::Recovery,
            NativeReservationRequest {
                work_bytes: 32 * 1024,
                ..NativeReservationRequest::default()
            },
            Instant::now() + WATCHDOG,
        )
        .unwrap();
    for keeper in [ordinary, other, unfunded] {
        assert!(matches!(
            owner.open_checkpoint(
                ProtectedCheckpointConfig {
                    root: external.path().to_path_buf()
                },
                identity(),
                None,
                Arc::new(keeper),
                |_| panic!("invalid original capacity cannot open native files"),
            ),
            Err(ProtectedStoreError::InvalidConfiguration)
        ));
    }
    assert!(!external.path().join(CHECKPOINT_NAME).exists());
    assert_eq!(owner.snapshot().unwrap().physical_owners, 0);
    assert!(finish(&owner).clean);
}

#[test]
fn checkpoint_refuses_actual_descendant_and_ancestor_roots_before_creating_any_leaf() {
    for external_below in [true, false] {
        let outer = external();
        let nested = outer.path().join("nested");
        fs::create_dir(&nested).unwrap();
        fs::set_permissions(&nested, fs::Permissions::from_mode(0o700)).unwrap();
        let (business_path, external_path) = if external_below {
            (outer.path().to_path_buf(), nested)
        } else {
            (nested, outer.path().to_path_buf())
        };
        let mut config = ProtectedStoreConfig::bounded_linux(business_path);
        config.create_if_missing = true;
        let owner = bound(config);
        let (checkpoint, refused) = wait(
            owner
                .open_checkpoint(
                    ProtectedCheckpointConfig {
                        root: external_path.clone(),
                    },
                    identity(),
                    witness(&owner),
                    keeper(&owner),
                    observed,
                )
                .unwrap(),
        )
        .unwrap();
        assert_eq!(
            refused,
            Err(ProtectedStoreError::Store(StoreError::Invalid))
        );
        assert!(!external_path.join(CHECKPOINT_NAME).exists());
        assert!(!external_path
            .join("transaction-checkpoint-owner.lock")
            .exists());
        wait(checkpoint.retire());
        assert!(finish(&owner).clean);
    }
}
