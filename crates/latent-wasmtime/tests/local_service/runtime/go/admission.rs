//! One original node/cell shared by real signed Go tenants.
use super::*;
use latent_artifacts::{LifecycleScope, PublicationRef};

fn observed(case: &str, tenant: &str, outcome: &str) {
    println!(
        "GO_ADMISSION_CASE {}",
        serde_json::json!({"case": case, "tenant": tenant, "outcome": outcome})
    );
}

async fn fixture(root: &std::path::Path) -> Fixture {
    let (caller, source) =
        checkpoint_component("LSF_GO_MANAGED_IDLE_FIXTURE", "go-component-activation-v5");
    let callee = packages::callee(42);
    let signers = package::Signers::for_tenant(
        latent_signing::PROVENANCE_BUILD_TYPE,
        &TenantId("tenant-b".into()),
    );
    let mut uploads = vec![];
    for (tenant, bundle, maintained_go) in [
        ("tenant-b", &caller, true),
        ("tenant-b", &callee, false),
        ("tenant-a", &caller, true),
    ] {
        let mut observation = provenance::observation();
        observation.source.repository =
            "https://github.com/KirilsTurkins/latent-service-fabric".into();
        observation.component_digest = bundle.layout().component_release().unwrap().0;
        observation.component_size = bundle.blob("component.wasm").unwrap().len() as u64;
        let bound = if maintained_go {
            let mut bound = source.clone();
            bound.extend_from_slice(include_bytes!(
                "../../../../../../wit/platform/activation-runtime/package.wit"
            ));
            bound
        } else {
            // Auxiliary topology fixture, never a Go compilation claim. Its
            // bytes come from the checked handwritten wasm-encoder builder.
            let mut bound = b"synthetic-local-service-callee:packages::callee(42)\n".to_vec();
            bound.extend_from_slice(include_bytes!("../../packages.rs"));
            bound.extend_from_slice(include_bytes!("../../component.rs"));
            bound.extend_from_slice(crate::component::CALLEE_WIT.as_bytes());
            bound
        };
        observation.source.snapshot_digest =
            latent_artifacts::package::artifact_blob_digest(&bound).into_string();
        let material = observation
            .materials
            .iter_mut()
            .find(|material| material.name == "source-snapshot")
            .unwrap();
        material.digest = observation.source.snapshot_digest.clone();
        material.size = bound.len() as u64;
        let tenant = TenantId(tenant.into());
        uploads.push((
            tenant.clone(),
            signers.upload_for_tenant(bundle, &observation, &tenant),
        ));
    }
    let catalog = package::catalog(root, signers.policy, Some(packages::budget().memory_bytes));
    for (tenant, upload) in uploads {
        catalog
            .admit_package(&tenant, upload, &mut |_| Ok(()))
            .await
            .unwrap();
    }
    let release = packages::release(&caller);
    let package_digest = caller.layout().digest().clone();
    let f = Fixture::with_two_tenant_activation_runtime(
        (catalog, caller, callee),
        RuntimeLimits {
            tasks: 16,
            waits: 4,
            ..limits()
        },
        120_000,
    )
    .await;
    for tenant in ["tenant-a", "tenant-b"] {
        let publication = PublicationRef::package(
            LifecycleScope::Tenant(TenantId(tenant.into())),
            &package_digest,
        )
        .unwrap();
        let mut key = f.backend.preparation_key(&release).unwrap();
        key.publication = Some(publication.id);
        let ready = tokio::time::timeout(
            Duration::from_secs(600),
            f.backend
                .prepare_ready_from_repository(f.catalog.clone(), key),
        )
        .await
        .unwrap()
        .unwrap();
        drop(f.backend.materialize_ready(ready).unwrap());
    }
    f.idle().await;
    assert_eq!(f.backend.resource_snapshot().stores_created, 0);
    f
}

fn request(f: &Fixture, tenant: &str, id: &str, mode: u32) -> latent_activation::ActivationRequest {
    let mut request = f.request(id, mode);
    request.target.tenant = TenantId(tenant.into());
    request.principal.tenant = Some(TenantId(tenant.into()));
    request
}

async fn refuse_full_cell(f: &Fixture, tenant: &str) {
    let before = f.backend.resource_snapshot();
    let failed = match f
        .manager
        .start(request(f, tenant, &format!("go-full-{tenant}"), 0))
    {
        Ok(handle) => failure(
            tokio::time::timeout(Duration::from_secs(2), handle)
                .await
                .expect("saturation must refuse rather than silently queue or retry"),
        ),
        Err(error) => error,
    };
    assert_eq!(failed.code, PlatformErrorCode::ResourceExhausted);
    assert!(
        failed.retryable,
        "retryability is advice, never a hidden retry"
    );
    assert!(failed.details.iter().any(|detail| {
        detail.kind == "admission.limit"
            && detail.fields
                == std::collections::BTreeMap::from([
                    ("scope".into(), "node".into()),
                    ("dimension".into(), "concurrency".into()),
                    ("reason".into(), "capacity-exhausted".into()),
                ])
    }));
    assert_eq!(
        f.backend.resource_snapshot().stores_created,
        before.stores_created
    );
    f.assert_single_cell_occupied_without_queue();
    observed("saturated", tenant, "resource-exhausted");
}

#[tokio::test]
#[ignore = "requires the exact maintained Go v5 component and signed tenant publications"]
async fn signed_cross_tenant_cell_saturation_keeps_original_owners_until_cancel_and_trap_retire() {
    assert_eq!(std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(), Ok("go"));
    let root = tempfile::tempdir().unwrap();
    let f = fixture(root.path()).await;
    for tenant in ["tenant-a", "tenant-b"] {
        assert_eq!(
            value(
                f.manager
                    .start(request(&f, tenant, &format!("go-warm-{tenant}"), 0))
                    .unwrap()
                    .await
            ),
            42
        );
        f.idle().await;
        observed("warm", tenant, "success");
    }
    for (tenant, other, mode) in [("tenant-a", "tenant-b", 3), ("tenant-b", "tenant-a", 4)] {
        let id = ActivationId(format!("go-original-{tenant}"));
        let mut original = Box::pin(f.manager.start(request(&f, tenant, &id.0, mode)).unwrap());
        // This is a real parked initialization/runtime wait. Holding its
        // unpolled future preserves the actual Store/cell while denial runs.
        pending_timer(original.as_mut(), &f).await;
        f.assert_single_cell_occupied_without_queue();
        refuse_full_cell(&f, other).await;
        let disposition = f
            .manager
            .cancel_for(&TenantId(other.into()), &id, "foreign-go-cancel")
            .unwrap();
        assert_eq!(disposition, latent_core::CancelDisposition::NotFound);
        f.assert_single_cell_occupied_without_queue();
        observed("foreign-cancel", other, "not-found");
        let expected = if mode == 3 {
            assert_eq!(
                f.manager
                    .cancel_for(&TenantId(tenant.into()), &id, "owned-go-cancel")
                    .unwrap(),
                latent_core::CancelDisposition::Accepted
            );
            PlatformErrorCode::Cancelled
        } else {
            PlatformErrorCode::GuestTrap
        };
        assert_eq!(failure(original.await).code, expected);
        f.idle().await;
        assert_eq!(f.read_wait.active.load(Ordering::Acquire), 0);
        observed(
            "original",
            tenant,
            if mode == 3 { "cancelled" } else { "guest-trap" },
        );
        assert_eq!(
            value(
                f.manager
                    .start(request(&f, other, &format!("go-fresh-{other}"), 0))
                    .unwrap()
                    .await
            ),
            42
        );
        f.idle().await;
        observed("fresh-after-retirement", other, "success");
    }
    for tenant in ["tenant-a", "tenant-b"] {
        assert_eq!(
            value(
                f.manager
                    .start(request(&f, tenant, &format!("go-final-{tenant}"), 0))
                    .unwrap()
                    .await
            ),
            42
        );
        f.idle().await;
        observed("final-fresh", tenant, "success");
    }
}
