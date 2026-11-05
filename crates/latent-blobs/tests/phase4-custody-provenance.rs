//! Branch-only check of the concrete type identities exposed by the custody facade.
#[test]
fn actual_facade_and_custody_owner_share_one_type_identity() {
    use std::any::{type_name, TypeId};
    type FacadeStore = latent_blobs::local::LocalBlobStore;
    type OwnerStore = latent_local_blobs::local::LocalBlobStore;
    type FacadePayload = latent_blobs::provider::CapturedLocalPayload;
    type OwnerPayload = latent_local_blobs::provider::CapturedLocalPayload;
    type FacadeReference = latent_blobs::BlobReference;
    type OwnerReference = latent_local_blobs::BlobReference;
    assert_eq!(TypeId::of::<FacadeStore>(), TypeId::of::<OwnerStore>());
    assert_eq!(TypeId::of::<FacadePayload>(), TypeId::of::<OwnerPayload>());
    assert_eq!(
        TypeId::of::<FacadeReference>(),
        TypeId::of::<OwnerReference>()
    );
    for name in [
        type_name::<FacadeStore>(),
        type_name::<FacadePayload>(),
        type_name::<FacadeReference>(),
    ] {
        assert!(name.starts_with("latent_local_blobs::"));
        println!("CUSTODY_CONCRETE_TYPE={name}");
    }
}
