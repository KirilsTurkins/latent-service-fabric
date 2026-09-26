use crate::{observation, support};
use latent_capabilities::broker::blob::BlobInvoker;
use latent_executor::{ExecutionBackend, ExecutionCleanup, GuestOutcome};
use serde_json::{json, Value};
use std::{
    sync::atomic::Ordering,
    time::{Duration, Instant},
};

#[path = "../local_blobs/component.rs"]
mod component;
#[path = "../local_blobs/fixture.rs"]
#[allow(dead_code, unused_imports)]
#[allow(
    clippy::unreadable_literal,
    clippy::used_underscore_binding,
    clippy::assigning_clones,
    reason = "reuse the maintained fixture without editing its unrelated lint baseline"
)]
mod fixture;
#[path = "../local_blobs/packages.rs"]
#[allow(dead_code)]
mod packages;

pub async fn measure(rows: &mut Vec<Value>) {
    let fixture = fixture::Fixture::new().await;
    rows.push(capture(&fixture, "fixed"));
    for ordinal in 0..2 {
        let (session, control) = fixture.session(&format!("resource-blob-owner-{ordinal}"));
        let mut writer = fixture
            .provider
            .create(&session, "text/plain".into(), Some(4))
            .unwrap()
            .await
            .unwrap();
        assert_eq!(fixture.provider.store().snapshot().unwrap().handles, 1);
        rows.push(capture(&fixture, "active"));
        writer.write(0, b"data".to_vec()).unwrap().await.unwrap();
        let sealed = writer.seal().unwrap().await.unwrap();
        let reference = sealed.reference;
        drop(sealed.owner);
        let mut reader = fixture
            .provider
            .open(&session, reference)
            .unwrap()
            .await
            .unwrap();
        let chunk = reader.read(0, 4).unwrap().await.unwrap();
        assert_eq!(chunk.bytes(), b"data");
        assert_eq!(fixture.io.snapshot().result_bytes, 4);
        rows.push(capture(&fixture, "active"));
        control.probe.0.store(true, Ordering::Release);
        drop(session);
        drop(reader);
        assert_eq!(
            observation::pool_snapshot(&fixture.pools)
                .0
                .running_requests,
            1
        );
        rows.push(capture(&fixture, "cancel-retained-result"));
        drop(chunk);
        fixture.idle();
        assert_eq!(fixture.provider.store().snapshot().unwrap().handles, 0);
        rows.push(capture(&fixture, "recovery"));
        for (mode, expected) in [(2, None), (0, Some("4101"))] {
            let (request, control) =
                fixture.request(&format!("resource-blob-{ordinal}-{mode}"), mode, 0);
            let began = Instant::now();
            let report = fixture.backend.invoke_contained(request, &control).await;
            assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
            match (report.outcome.unwrap(), expected) {
                (GuestOutcome::Trapped { .. }, None) => (),
                (GuestOutcome::Returned { output, .. }, Some(expected)) => {
                    assert_eq!(
                        serde_json::from_slice::<Value>(&output).unwrap(),
                        json!([expected])
                    );
                }
                other => panic!("unexpected resource blob result: {other:?}"),
            }
            fixture.idle();
            fixture.provider.store().reclaim(64, &|| Ok(())).unwrap();
            let mut retired = capture(&fixture, "recovery");
            retired["after"] = json!(if expected.is_some() {
                "guest-success"
            } else {
                "guest-failure"
            });
            retired["invocationNanos"] = json!(began.elapsed().as_nanos().to_string());
            rows.push(retired);
        }
    }
    assert!(fixture
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
    rows.push(capture(&fixture, "shutdown"));
}

fn capture(fixture: &fixture::Fixture, phase: &str) -> Value {
    let mut value = observation::snapshot(
        "blob",
        phase,
        &fixture.backend,
        &fixture.broker,
        Some(&fixture.pools),
        Some(&fixture.io),
    );
    let store = fixture.provider.store().snapshot().unwrap();
    value["blobStore"] = observation::fields!(
        store,
        objects,
        referenced_objects,
        resident_disk_bytes,
        accounted_disk_bytes,
        stages,
        reserved_stage_bytes,
        handles,
        active_work,
        metadata_bytes,
        poisoned,
        closed
    );
    let storage = fixture.catalog.publication_storage_snapshot().unwrap();
    value["publicationStorage"] = observation::fields!(
        storage,
        shared_blobs,
        shared_blob_bytes,
        retained_publications,
        publication_file_bytes,
        incomplete_file_bytes,
        web_control_bytes,
        accounted_metadata_bytes
    );
    value
}
