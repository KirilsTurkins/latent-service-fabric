use super::*;
use latent_core::native_capacity::{NativeCapacityLimits, NativeCapacityOwner};

#[test]
fn original_global_capacity_binding_is_same_owner_only_and_survives_native_admission() {
    let (_root, config) = fixture();
    let store = start(config);
    let original = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
    let foreign = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
    assert!(!store.uses_native_capacity(&original));
    assert!(store.native_capacity().is_err());
    store.bind_native_capacity(&original).unwrap();
    let alias = store.clone();
    assert!(alias.native_capacity().unwrap().is_same_owner(&original));
    assert!(!alias.uses_native_capacity(&foreign));
    assert_eq!(
        alias.bind_native_capacity(&foreign),
        Err(ProtectedStoreError::InvalidConfiguration)
    );
    wait(
        store
            .with_store(StoreIoKind::RecoveryRead, 0, |_| Ok(()))
            .unwrap(),
    )
    .unwrap()
    .unwrap();
    alias.bind_native_capacity(&original.clone()).unwrap();
    assert!(store.uses_native_capacity(&original));
    assert!(original.snapshot().unwrap().physically_retired());
    assert!(finish(&store).clean);
}

#[test]
fn first_native_admission_seals_unbound_store_and_closed_store_cannot_bind() {
    let (_root, config) = fixture();
    let store = start(config);
    let original = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
    wait(
        store
            .with_store(StoreIoKind::RecoveryRead, 0, |_| Ok(()))
            .unwrap(),
    )
    .unwrap()
    .unwrap();
    assert_eq!(
        store.bind_native_capacity(&original),
        Err(ProtectedStoreError::InvalidConfiguration)
    );
    assert!(store.native_capacity().is_err());
    assert!(finish(&store).clean);
    let (_root, config) = fixture();
    let store = start(config);
    store.close();
    assert_eq!(
        store.bind_native_capacity(&original),
        Err(ProtectedStoreError::InvalidConfiguration)
    );
    assert!(finish(&store).clean);
}
