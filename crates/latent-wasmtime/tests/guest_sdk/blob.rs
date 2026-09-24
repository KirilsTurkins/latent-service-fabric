use super::{input, package, run, support};
#[path = "../local_blobs/component.rs"]
#[allow(dead_code, unused_imports)]
mod component;
#[path = "../local_blobs/fixture.rs"]
#[allow(dead_code, unused_imports)]
mod fixture;
#[path = "../local_blobs/packages.rs"]
#[allow(dead_code, unused_imports)]
mod packages;
use fixture::*;

#[tokio::test]
#[ignore = "Requires compiled guest SDK fixtures"]
async fn rust_and_c_owned_chunks_closed_handles_abandonment_and_reuse() {
    for language in super::languages() {
        let (_root, f) = configured(&format!("{language}-blob"), Default::default()).await;
        for (which, expected) in [(0, 4), (1, 1), (2, 10), (3, 3), (0, 4)] {
            let (mut request, control) = f.request("sdk-blob", 0, 0);
            input(&mut request, which, "", 0);
            assert_eq!(
                run(&f.backend, request, &control).await,
                expected,
                "{language} case {which}"
            );
            f.idle();
            assert_eq!(
                f.io.snapshot(),
                latent_capabilities::broker::io::IoSnapshot::default()
            );
        }
        let (mut request, control) = f.request("sdk-old-handle", 0, 0);
        input(&mut request, 5, "", 0);
        let previous_handle = run(&f.backend, request, &control).await;
        f.idle();
        let (mut request, control) = f.request("sdk-new-activation", 0, 0);
        input(&mut request, 4, "", previous_handle);
        assert_eq!(run(&f.backend, request, &control).await, 10);
        f.idle();
        if language == "c" {
            let (mut request, control) = f.request("sdk-one-materialization", 0, 0);
            input(&mut request, 6, "", 0);
            assert_eq!(run(&f.backend, request, &control).await, 10);
            f.idle();
        }
        assert!(f
            .pools
            .shutdown(Instant::now() + Duration::from_secs(2))
            .await
            .unwrap()
            .is_clean());
    }
}

async fn configured(
    name: &str,
    limits: latent_capabilities::broker::pools::ProviderPoolLimits,
) -> (tempfile::TempDir, Fixture) {
    let root = tempfile::tempdir().unwrap();
    let publication = package::publish(root.path(), name).await;
    let mut ceiling = support::budget();
    ceiling.cpu_fuel = 10_000_000_000;
    ceiling.outbound_requests = 8;
    ceiling.blob_read_bytes = 65536;
    ceiling.blob_write_bytes = 65536;
    ceiling.wall_time_limit_millis = Some(5000);
    let f = Fixture::with_publication(
        ceiling,
        limits,
        "linux-immutable-blobs-v1",
        |path, pools| async move {
            let store = latent_blobs::local::LocalBlobStore::open(
                &path.join("blobs"),
                "private",
                latent_blobs::local::LocalBlobLimits {
                    maximum_chunk_bytes: 4,
                    ..Default::default()
                },
            )
            .unwrap();
            let provider =
                latent_blobs::provider::LocalBlobProvider::install(pools, "blobs", 1, 0, store)
                    .unwrap();
            let reference = provider.reference();
            (provider, reference)
        },
        Some(publication),
    )
    .await;
    (root, f)
}

#[tokio::test]
#[ignore = "Requires compiled guest SDK fixtures"]
async fn rust_and_c_cancel_pending_import_without_refunding_another_owner() {
    use latent_capabilities::broker::{blob::BlobInvoker, pools::ProviderPoolLimits};
    for language in super::languages() {
        let (_root, f) = configured(
            &format!("{language}-blob"),
            ProviderPoolLimits {
                maximum_running_requests: 1,
                maximum_running_per_provider: 1,
                maximum_running_per_tenant: 1,
                ..Default::default()
            },
        )
        .await;
        let (session, _held_control) = f.session("holds-pool-slot");
        let mut writer = f
            .provider
            .create(&session, "text/plain".into(), Some(4))
            .unwrap()
            .await
            .unwrap();
        writer.write(0, b"data".to_vec()).unwrap().await.unwrap();
        let sealed = writer.seal().unwrap().await.unwrap();
        let reference = sealed.reference;
        drop(sealed.owner);
        let mut reader = f.provider.open(&session, reference).unwrap().await.unwrap();
        let held = reader.read(0, 4).unwrap().await.unwrap();
        drop(reader);
        assert_eq!(f.pools.snapshot().unwrap().running_requests, 1);
        let (mut request, control) = f.request("sdk-pending-cancel", 0, 0);
        input(&mut request, 1, "", 0);
        let (report, ()) = tokio::join!(f.backend.invoke_contained(request, &control), async {
            tokio::time::timeout(Duration::from_secs(2), async {
                while f.pools.snapshot().unwrap().pending_requests == 0 {
                    tokio::task::yield_now().await;
                }
            })
            .await
            .unwrap();
            control.probe.0.store(true, Ordering::Release);
        });
        super::assert_cancelled(report);
        assert_eq!(f.pools.snapshot().unwrap().running_requests, 1);
        drop((held, session));
        f.idle();
        let (mut request, control) = f.request("sdk-after-cancel", 0, 0);
        input(&mut request, 1, "", 0);
        assert_eq!(run(&f.backend, request, &control).await, 1);
        f.idle();
        assert!(f
            .pools
            .shutdown(Instant::now() + Duration::from_secs(2))
            .await
            .unwrap()
            .is_clean());
    }
}
