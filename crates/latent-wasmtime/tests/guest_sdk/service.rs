use super::package;
#[path = "../local_service/component.rs"]
#[allow(dead_code)]
mod component;
#[path = "../local_service/fixture.rs"]
#[allow(dead_code)]
mod fixture;
#[path = "../local_service/packages.rs"]
#[allow(dead_code)]
mod packages;
use latent_activation::ActivationOutcome;
use latent_artifacts::ArtifactRepository;
use latent_core::TenantId;

async fn configured(root: &std::path::Path, permit: bool) -> fixture::Fixture {
    let caller = package::bundle(&package::input("rust-service"));
    let callee = package::bundle(&package::input("rust-callee"));
    let signers = package::Signers::new(latent_signing::RUST_GUEST_BUILD_TYPE);
    let mut uploads = vec![];
    for (name, bundle) in [("rust-service", &caller), ("rust-callee", &callee)] {
        let observation = package::observation(name);
        uploads.push(signers.upload(bundle, &observation));
    }
    let catalog = package::catalog(root, signers.policy);
    for upload in uploads {
        catalog
            .admit_package(&TenantId("tenant-a".into()), upload, &mut |_| Ok(()))
            .await
            .unwrap();
    }
    fixture::Fixture::with_packages(2, false, permit, None, Some((catalog, caller, callee))).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires compiled guest SDK fixtures"]
async fn typed_service_outcomes_use_node_admission_and_reused_cells() {
    for permit in [true, false] {
        let root = tempfile::tempdir().unwrap();
        let f = configured(root.path(), permit).await;
        for (index, (which, expected)) in [(0, 42), (1, 10), (0, 42)].into_iter().enumerate() {
            let mut request = f.request(&format!("sdk-service-{index}"), which);
            request.input = serde_json::to_vec(&serde_json::json!([which, "", "0"])).unwrap();
            let receipt = f.manager.start(request).unwrap().await;
            let ActivationOutcome::Succeeded(success) = receipt.outcome else {
                panic!("{:?}", receipt.outcome)
            };
            let result: Vec<String> = serde_json::from_slice(&success.output).unwrap();
            assert_eq!(result, [if permit { expected } else { 11 }.to_string()]);
            assert_eq!(success.consumption.child_calls, u32::from(permit));
            f.idle().await;
        }
    }
}
