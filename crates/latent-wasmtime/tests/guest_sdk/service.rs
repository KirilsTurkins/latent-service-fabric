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

async fn configured(root: &std::path::Path, permit: bool, language: &str) -> fixture::Fixture {
    let caller_name = format!("{language}-service");
    let callee_name = format!("{language}-callee");
    let caller = package::bundle(&package::input(&caller_name));
    let callee = package::bundle(&package::input(&callee_name));
    let signers = package::Signers::new(&package::observation(&caller_name).build_type);
    let mut uploads = vec![];
    for (name, bundle) in [
        (caller_name.as_str(), &caller),
        (callee_name.as_str(), &callee),
    ] {
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
    for language in super::languages() {
        for permit in [true, false] {
            let root = tempfile::tempdir().unwrap();
            let f = configured(root.path(), permit, language).await;
            for (index, (which, expected)) in [(0, 42), (1, 10), (0, 42)].into_iter().enumerate() {
                let mut request = f.request(&format!("sdk-service-{index}"), which);
                request.input = serde_json::to_vec(&serde_json::json!([which, "", "0"])).unwrap();
                let started = std::time::Instant::now();
                let receipt = f.manager.start(request).unwrap().await;
                let terminals = f.observations.terminals.lock().unwrap().clone();
                let starts = f.observations.starts.lock().unwrap().clone();
                eprintln!(
                    "service timing language={language} permit={permit} case={index} elapsed={:?}; caller/child starts: {starts:?}; terminals: {terminals:?}",
                    started.elapsed()
                );
                let ActivationOutcome::Succeeded(success) = receipt.outcome else {
                    panic!(
                        "{:?}; caller/child starts: {starts:?}; terminals: {terminals:?}",
                        receipt.outcome
                    )
                };
                let result: Vec<String> = serde_json::from_slice(&success.output).unwrap();
                assert_eq!(
                    result,
                    [if permit { expected } else { 11 }.to_string()],
                    "caller/child terminals: {terminals:?}"
                );
                assert_eq!(success.consumption.child_calls, u32::from(permit));
                f.idle().await;
            }
        }
    }
}
