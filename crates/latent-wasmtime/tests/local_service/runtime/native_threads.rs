//! Signed WAT mechanism controls. No Rust standard-library port is inferred.
use super::*;

fn component(root: &std::path::Path, name: &str) -> Vec<u8> {
    assert_eq!(
        std::fs::read(root.join("core.wat")).unwrap(),
        include_bytes!("../../../../../sdk/rust-standard-runtime/owned-child-fixture/core.wat")
    );
    assert_eq!(
        std::fs::read(root.join("world.wit")).unwrap(),
        include_bytes!("../../../../../sdk/rust-standard-runtime/owned-child-fixture/world.wit")
    );
    std::fs::read(root.join(name)).unwrap()
}

async fn configured(bytes: Vec<u8>, grant: bool) -> (tempfile::TempDir, Fixture) {
    let root = tempfile::tempdir().unwrap();
    let caller = packages::owned_native_threads(bytes);
    let callee = packages::callee(42);
    let signers = package::Signers::new(latent_signing::PROVENANCE_BUILD_TYPE);
    let mut uploads = Vec::new();
    for bundle in [&caller, &callee] {
        let mut observation = provenance::observation();
        observation.source.repository =
            "https://github.com/KirilsTurkins/latent-service-fabric".into();
        observation.component_digest = bundle.layout().component_release().unwrap().0;
        observation.component_size = bundle.blob("component.wasm").unwrap().len() as u64;
        let source = [
            include_bytes!("../../../../../sdk/rust-standard-runtime/owned-child-fixture/core.wat")
                .as_slice(),
            include_bytes!(
                "../../../../../sdk/rust-standard-runtime/owned-child-fixture/world.wit"
            )
            .as_slice(),
        ]
        .concat();
        observation.source.snapshot_digest =
            latent_artifacts::package::artifact_blob_digest(&source).into_string();
        let material = observation
            .materials
            .iter_mut()
            .find(|m| m.name == "source-snapshot")
            .unwrap();
        material.digest = observation.source.snapshot_digest.clone();
        material.size = source.len() as u64;
        uploads.push(signers.upload(bundle, &observation));
    }
    let catalog = package::catalog(
        root.path(),
        signers.policy,
        Some(packages::budget().memory_bytes),
    );
    for upload in uploads {
        catalog
            .admit_package(&TenantId("tenant-a".into()), upload, &mut |_| Ok(()))
            .await
            .unwrap();
    }
    let fixture = Fixture::with_owned_native_threads(
        (catalog, caller, callee),
        RuntimeLimits {
            tasks: 3,
            native_owners: 2,
            ..limits()
        },
        grant,
    )
    .await;
    (root, fixture)
}

#[tokio::test]
#[ignore = "requires the authenticated normal-encoder canonical-child WAT mechanism fixture"]
async fn signed_canonical_children_use_distinct_original_tasks_and_physical_stack_retirement() {
    let root = std::path::PathBuf::from(
        std::env::var_os("LSF_OWNED_CHILD_FIXTURE")
            .expect("prepare the explicit canonical-child mechanism fixture"),
    );
    let bytes = component(&root, "owned.wasm");
    let (_root, f) = configured(bytes.clone(), true).await;
    // The second successful call consumes the prepared cache in a fresh Store.
    for (mode, calls) in [
        (0, 5),
        (0, 5),
        (1, 3),
        (2, 3),
        (3, 4),
        (4, 5),
        (5, 3),
        (6, 4),
        (0, 5),
    ] {
        let id = format!(
            "canonical-child-{mode}-{}",
            f.backend.resource_snapshot().stores_created
        );
        let receipt = f.manager.start(f.request(&id, mode)).unwrap().await;
        if mode == 0 {
            let result = success(receipt);
            assert_eq!(
                serde_json::from_slice::<Vec<u32>>(&result.output).unwrap(),
                [42]
            );
            assert!(result.consumption.cpu_fuel > 0);
            assert!(result.consumption.memory_bytes >= 256 * 1024 + 2 * (256 * 1024 + 4096));
        } else {
            let error = failure(receipt);
            if mode == 2 {
                assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
            } else if mode != 6 {
                assert_eq!(error.code, PlatformErrorCode::GuestTrap);
            }
        }
        assert_eq!(
            f.backend
                .take_invocation_timing(&ActivationId(id))
                .unwrap()
                .host_call_count,
            calls
        );
        f.idle().await;
        eprintln!(
            "owned-canonical-child mode={mode} calls={calls} all-original-owners-retired=true"
        );
    }
    let (_denied_root, denied) = configured(bytes, false).await;
    let receipt = denied
        .manager
        .start(denied.request("canonical-child-missing-native-grant", 0))
        .unwrap()
        .await;
    assert_eq!(failure(receipt).code, PlatformErrorCode::PermissionDenied);
    denied.idle().await;
    for name in ["unwrapped.wasm", "modified-shim.wasm"] {
        let (_invalid_root, invalid) = configured(component(&root, name), true).await;
        let receipt = invalid
            .manager
            .start(invalid.request("canonical-child-unverified", 0))
            .unwrap()
            .await;
        assert_eq!(failure(receipt).code, PlatformErrorCode::CorruptArtifact);
        assert_eq!(invalid.backend.resource_snapshot().stores_created, 0);
        invalid.idle().await;
    }
}
