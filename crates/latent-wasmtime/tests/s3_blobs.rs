//! The actual blob guest and original tenant/session against pinned TLS S3.
#![cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[path = "local_blobs/component.rs"]
mod component;
#[path = "s3_blobs/faults.rs"]
mod faults;
#[path = "local_blobs/fixture.rs"]
#[allow(dead_code)]
mod fixture;
#[path = "local_blobs/packages.rs"]
mod packages;
#[path = "s3_blobs/setup.rs"]
mod setup;
#[path = "generic_backend/support.rs"]
#[allow(dead_code)]
mod support;
use fixture::*;
use latent_blobs::s3::{S3BlobProvider, S3Recovery, S3RecoveryMode};
use latent_capabilities::broker::blob::{BlobError, BlobInvoker};

#[tokio::test]
#[ignore = "requires tools/run_s3_blob_tests.py owned, pinned TLS server"]
async fn real_s3_guest_multipart_ranges_credentials_and_restart() {
    let (config, key) = setup::configured();
    let f = setup::fixture(config.clone(), key.clone()).await;
    for mode in [0, 9, 0] {
        let (request, control) = f.request("s3-guest", mode, 0);
        let report = f.backend.invoke_contained(request, &control).await;
        let GuestOutcome::Returned {
            output,
            consumption,
            ..
        } = report.outcome.unwrap()
        else {
            panic!("S3 guest outcome");
        };
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&output).unwrap(),
            serde_json::json!([if mode == 9 { "0" } else { "4101" }])
        );
        assert!(control
            .budget
            .finalize_at(Some(&consumption), Instant::now())
            .violation()
            .is_none());
        assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
        f.idle();
    }
    let (session, control) = f.session("multipart-cross-part-range");
    let size = 5 * 1024 * 1024 + 17;
    let mut writer = f
        .provider
        .create(&session, "application/octet-stream".into(), Some(size))
        .unwrap()
        .await
        .unwrap();
    let mut written = 0;
    while written < size {
        let length = (size - written).min(32768) as usize;
        let bytes = (written..written + length as u64)
            .map(|n| (n % 251) as u8)
            .collect::<Vec<_>>();
        written = writer
            .write(written, bytes)
            .unwrap()
            .await
            .unwrap_or_else(|error| {
                panic!(
                    "write at {written}: {error:?}; pools {:?}; IO {:?}; broker {:?}; budget {:?}",
                    f.pools.snapshot().unwrap(),
                    f.io.snapshot(),
                    f.broker.snapshot(),
                    control.budget.snapshot_at(Instant::now())
                )
            });
    }
    let sealed = writer.seal().unwrap().await.unwrap();
    let reference = sealed.reference;
    drop(sealed.owner);
    let mut reader = f
        .provider
        .open(&session, reference.clone())
        .unwrap()
        .await
        .unwrap();
    let offset = 5 * 1024 * 1024 - 4;
    let chunk = reader.read(offset, 21).unwrap().await.unwrap();
    assert_eq!(
        chunk.bytes(),
        &(offset..offset + 21)
            .map(|n| (n % 251) as u8)
            .collect::<Vec<_>>()
    );
    assert_eq!(
        control.budget.snapshot_at(Instant::now()).outbound_requests,
        6
    );
    drop((chunk, reader, session));
    // The same shared provider must not resolve another tenant's digest tuple,
    // even when both tenants have explicit credentials for the same bucket.
    let (other, other_control) = setup::other_session(&f).await;
    assert!(matches!(
        f.provider.open(&other, reference.clone()).unwrap().await,
        Err(BlobError::NotFound)
    ));
    assert_eq!(
        other_control
            .budget
            .snapshot_at(Instant::now())
            .outbound_requests,
        0
    );
    let empty = f
        .provider
        .create(&other, "text/plain".into(), Some(0))
        .unwrap()
        .await
        .unwrap()
        .seal()
        .unwrap()
        .await
        .unwrap();
    let empty_reference = empty.reference;
    drop(empty.owner);
    let mut other_reader = f
        .provider
        .open(&other, empty_reference)
        .unwrap()
        .await
        .unwrap();
    assert!(other_reader
        .read(0, 0)
        .unwrap()
        .await
        .unwrap()
        .bytes()
        .is_empty());
    assert_eq!(
        other_control
            .budget
            .snapshot_at(Instant::now())
            .outbound_requests,
        1
    );
    drop((other_reader, other));
    let before = f.provider.inventory().snapshot().unwrap();
    assert_eq!(before.unresolved_uploads, 0);
    assert_eq!(before.stages, 0);
    assert_eq!(before.handles, 0);
    f.dormant_deployments().await;
    assert_eq!(f.provider.inventory().snapshot().unwrap(), before);
    assert!(f
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
    f.idle();
    // The inventory root is independently owned by this fixture and survives
    // dropping the runtime/provider. Reopen under a fresh broker and host.
    drop(f);
    // Simulate a crash after S3 accepted Complete but before the final local
    // receipt became durable. Recovery must verify the existing object, never
    // initiate another upload of the same immutable tuple.
    let inventory_path =
        std::path::PathBuf::from(std::env::var_os("LSF_S3_TEST_INVENTORY").unwrap());
    let mut recovery_id = None;
    for path in std::fs::read_dir(inventory_path.join("records")).unwrap() {
        let path = path.unwrap().path();
        let mut record: serde_json::Value =
            serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
        if record["digest"] == reference.digest {
            record["phase"] = "completing".into();
            record["quiescent"] = false.into();
            record["version"] = serde_json::Value::Null;
            std::fs::write(&path, serde_json::to_vec(&record).unwrap()).unwrap();
            recovery_id = Some(path.file_stem().unwrap().to_str().unwrap().to_owned());
        }
    }
    let restarted = setup::fixture(config, key).await;
    let (session, _) = restarted.session("restart-reference");
    assert!(matches!(
        restarted
            .provider
            .open(&session, reference.clone())
            .unwrap()
            .await,
        Err(BlobError::Uncertain)
    ));
    assert_eq!(
        restarted
            .provider
            .reconcile(
                &recovery_id.unwrap(),
                Instant::now() + Duration::from_secs(5),
                1,
                S3RecoveryMode::Observe
            )
            .await
            .unwrap(),
        S3Recovery::Sealed
    );
    let replacement = std::process::Command::new("python3")
        .arg(std::env::var_os("LSF_S3_TEST_CONTROL").unwrap())
        .arg(std::env::var_os("LSF_S3_TEST_PORT").unwrap())
        .arg(std::env::var_os("LSF_S3_TEST_PEM").unwrap())
        .arg(&inventory_path)
        .arg(&reference.digest)
        .status()
        .unwrap();
    assert!(replacement.success());
    let mut reader = restarted
        .provider
        .open(&session, reference)
        .unwrap()
        .await
        .unwrap();
    assert_eq!(
        reader.read(0, 4).unwrap().await.unwrap().bytes(),
        &[0, 1, 2, 3]
    );
    drop((reader, session));
    assert!(restarted
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
}

#[tokio::test]
#[ignore = "requires tools/run_s3_blob_tests.py owned, pinned TLS server"]
async fn real_s3_wrong_credentials_are_not_retried() {
    let (mut config, _) = setup::configured();
    config.prefix = "bad-auth/".into();
    let root = tempfile::TempDir::new().unwrap();
    let f = setup::fixture_at(
        config,
        "LSFPUBLICS3TEST\nwrong-secret".into(),
        root.path().join("inventory"),
    )
    .await;
    let (session, control) = f.session("wrong-credential");
    let writer = f
        .provider
        .create(&session, "text/plain".into(), Some(0))
        .unwrap()
        .await
        .unwrap();
    assert!(matches!(
        writer.seal().unwrap().await,
        Err(BlobError::PermissionDenied)
    ));
    let snapshot = f.provider.inventory().snapshot().unwrap();
    assert_eq!(snapshot.unresolved_uploads, 0);
    assert_eq!(snapshot.active_uploads, 0);
    let writer = f
        .provider
        .create(&session, "text/plain".into(), Some(0))
        .unwrap()
        .await
        .unwrap();
    assert!(matches!(
        writer.seal().unwrap().await,
        Err(BlobError::PermissionDenied)
    ));
    assert_eq!(
        control.budget.snapshot_at(Instant::now()).outbound_requests,
        2
    );
    drop(session);
    assert!(f
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
}
