use super::{input, package, run, support};
#[path = "../local_secrets/component.rs"]
#[allow(dead_code, unused_imports)]
mod component;
#[path = "../local_secrets/fixture.rs"]
#[allow(dead_code, unused_imports)]
mod fixture;
#[path = "../local_secrets/packages.rs"]
#[allow(dead_code, unused_imports)]
mod packages;
use fixture::*;

#[tokio::test]
#[ignore = "Requires compiled guest SDK fixtures"]
async fn secret_owner_typed_denial_cancellation_and_cell_recovery() {
    for language in ["rust", "c"] {
        let root = tempfile::tempdir().unwrap();
        let publication = package::publish(root.path(), &format!("{language}-secrets")).await;
        let f = Fixture::with_publication(
            None,
            Default::default(),
            latent_secrets::LOCAL_SECRETS_PROFILE,
            |_, _, secrets, _| async move {
                let provider =
                    latent_secrets::LocalSecretProvider::install("secrets", 1, 0, &secrets)
                        .unwrap();
                let reference = provider.reference();
                (provider, reference)
            },
            Some(publication),
        )
        .await;
        for (name, expected) in [
            ("allowed", 5),
            ("opaque", 10),
            ("tenant-only", 11),
            ("expired", 12),
        ] {
            let (mut request, control) = f.request("sdk-secret", 0);
            input(&mut request, 0, name, 0);
            assert_eq!(run(&f.backend, request, &control).await, expected, "{name}");
            f.idle();
        }
        f.gate.armed.store(true, Ordering::Release);
        let (mut request, control) = f.request("sdk-secret-cancel", 0);
        input(&mut request, 0, "allowed", 0);
        let (report, ()) = tokio::join!(f.backend.invoke_contained(request, &control), async {
            tokio::time::timeout(Duration::from_secs(2), f.gate.entered.notified())
                .await
                .unwrap();
            assert_eq!(f.broker.snapshot().calls, 1);
            control.probe.0.store(true, Ordering::Release);
            f.gate.released.notify_one();
        });
        // The v0.1 secret WIT has no cancellation variant: if the guest resumes
        // before the backend interruption wins, preserve its exact Unavailable
        // error. Neither outcome may return secret bytes or retry the read.
        assert_eq!(report.cleanup, latent_executor::ExecutionCleanup::Reusable);
        if let Ok(latent_executor::GuestOutcome::Returned { output, .. }) = report.outcome {
            assert_eq!(
                serde_json::from_slice::<Vec<String>>(&output).unwrap(),
                ["13"]
            );
        } else {
            super::assert_cancelled(report);
        }
        f.idle();
        let (mut request, control) = f.request("sdk-secret-recovered", 0);
        input(&mut request, 0, "allowed", 0);
        assert_eq!(run(&f.backend, request, &control).await, 5);
        f.idle();
        assert!(f
            .pools
            .shutdown(Instant::now() + Duration::from_secs(2))
            .await
            .unwrap()
            .is_clean());
    }
}
