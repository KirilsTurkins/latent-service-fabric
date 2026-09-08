use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use latent_core::{ContractId, Metadata, ReleaseDigest};

use super::*;
use crate::{PreparationKey, PreparedUse};

#[derive(Debug)]
struct Owner(Arc<AtomicUsize>);
impl Drop for Owner {
    fn drop(&mut self) {
        self.0.fetch_add(1, Ordering::Relaxed);
    }
}

fn descriptor() -> PreparedComponent {
    PreparedComponent {
        key: PreparationKey {
            release: ReleaseDigest("release".into()),
            engine_version: "fixture".into(),
            engine_configuration_digest: "fixture".into(),
            target_triple: "fixture".into(),
            cpu_feature_set: "fixture".into(),
        },
        backend: "fixture".into(),
        opaque_handle: "fixture".into(),
        metadata: Metadata::new(),
    }
}

#[test]
fn failed_downcast_preserves_readiness_and_drops_exactly_once() {
    let drops = Arc::new(AtomicUsize::new(0));
    let imports = vec![ContractId("optional".into())];
    let ready = PreparedReadiness::new(descriptor(), imports.clone(), Owner(drops.clone()));
    let ready = ready.into_parts::<()>().expect_err("foreign type");
    assert_eq!(ready.descriptor(), &descriptor());
    assert_eq!(ready.imports(), imports);
    assert_eq!(drops.load(Ordering::Relaxed), 0);
    let (actual, actual_imports, owner) = ready.into_parts::<Owner>().expect("same owner");
    assert_eq!(actual, descriptor());
    assert_eq!(actual_imports, imports);
    drop(owner);
    assert_eq!(drops.load(Ordering::Relaxed), 1);
}

#[test]
fn legacy_fallback_moves_original_owner_and_import_allocation() {
    let drops = Arc::new(AtomicUsize::new(0));
    let activation = PreparedActivation {
        prepared: PreparedUse::new(descriptor(), Owner(drops.clone())),
        imports: vec![ContractId("optional".into())],
    };
    let descriptor_address = activation.prepared.descriptor() as *const PreparedComponent;
    let imports_address = activation.imports.as_ptr();
    let ready = PreparedReadiness::from_activation(activation);
    assert_eq!(
        ready.descriptor() as *const PreparedComponent,
        descriptor_address
    );
    assert_eq!(ready.imports().as_ptr(), imports_address);
    let ready = ready
        .into_parts::<Owner>()
        .expect_err("legacy owner stays wrapped");
    let activation = ready.into_activation().expect("original activation");
    assert_eq!(
        activation.prepared.descriptor() as *const PreparedComponent,
        descriptor_address
    );
    assert_eq!(activation.imports.as_ptr(), imports_address);
    assert_eq!(drops.load(Ordering::Relaxed), 0);
    drop(activation);
    assert_eq!(drops.load(Ordering::Relaxed), 1);
}

#[test]
fn foreign_readiness_and_unpolled_future_reclaim_their_pins() {
    let drops = Arc::new(AtomicUsize::new(0));
    let ready = PreparedReadiness::new(descriptor(), vec![], Owner(drops.clone()));
    drop(ready.into_activation().expect_err("foreign owner"));
    assert_eq!(drops.load(Ordering::Relaxed), 1);
    let ready = PreparedReadiness::new(descriptor(), vec![], Owner(drops.clone()));
    let future = async move {
        std::future::pending::<()>().await;
        drop(ready);
    };
    drop(future);
    assert_eq!(drops.load(Ordering::Relaxed), 2);
}
