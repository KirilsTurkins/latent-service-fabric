use crate::observation;
use latent_activation::ActivationOutcome;
use latent_core::{ActivationId, CancelDisposition, PlatformErrorCode, TenantId};
use serde_json::{json, Value};
use std::time::{Duration, Instant};

#[path = "../local_service/component.rs"]
mod component;
#[path = "../local_service/fixture.rs"]
#[allow(dead_code, unused_imports)]
mod fixture;
#[path = "../local_service/packages.rs"]
#[allow(dead_code)]
mod packages;

pub async fn measure(rows: &mut Vec<Value>) {
    for cells in [1, 2] {
        let fixture = fixture::Fixture::new(cells, false, true).await;
        let mut fixed = capture(&fixture, "fixed");
        fixed["configuredCells"] = json!(cells);
        rows.push(fixed);
        for ordinal in 0..2 {
            for mode in if cells == 1 { vec![0] } else { vec![0, 1] } {
                let began = Instant::now();
                let result = tokio::time::timeout(
                    Duration::from_secs(3),
                    fixture
                        .manager
                        .start(fixture.request(&format!("resource-child-{ordinal}-{mode}"), mode))
                        .unwrap(),
                )
                .await
                .unwrap();
                let actual = value(result);
                assert_eq!(
                    actual,
                    if cells == 1 {
                        2003
                    } else if mode == 1 {
                        1000
                    } else {
                        u32::from_le_bytes(*b"[42]")
                    }
                );
                fixture.idle().await;
                let mut retired = capture(&fixture, "recovery");
                retired["after"] = json!(if cells == 1 {
                    "one-cell-overload"
                } else if mode == 1 {
                    "declared-failure"
                } else {
                    "success"
                });
                retired["invocationNanos"] = json!(began.elapsed().as_nanos().to_string());
                rows.push(retired);
            }
            if cells == 2 {
                cancel(&fixture, ordinal, rows).await;
                let result = fixture
                    .manager
                    .start(fixture.request(&format!("resource-child-recover-{ordinal}"), 0))
                    .unwrap()
                    .await;
                assert_eq!(value(result), u32::from_le_bytes(*b"[42]"));
                fixture.idle().await;
                rows.push(capture(&fixture, "recovery"));
            }
        }
    }
}

async fn cancel(fixture: &fixture::Fixture, ordinal: u32, rows: &mut Vec<Value>) {
    let activation = format!("resource-child-cancel-{ordinal}");
    let mut parent = tokio::spawn(
        fixture
            .manager
            .start(fixture.request(&activation, 2))
            .unwrap(),
    );
    let control = async {
        fixture.observations.child_running.notified().await;
        while fixture.backend.resource_snapshot().live_stores < 2 {
            tokio::task::yield_now().await;
        }
        let active = capture(fixture, "active");
        assert_eq!(active["runtime"]["live_stores"], 2);
        assert_eq!(fixture.quotas.usage().unwrap().active_activations, 2);
        rows.push(active);
        assert_eq!(
            fixture
                .manager
                .cancel_for(
                    &TenantId("tenant-a".into()),
                    &ActivationId(activation),
                    "resource-checkpoint"
                )
                .unwrap(),
            CancelDisposition::Accepted
        );
    };
    let joined = tokio::time::timeout(Duration::from_secs(3), async {
        tokio::join!(&mut parent, control)
    })
    .await;
    if joined.is_err() {
        parent.abort();
        let _retired = parent.await;
        panic!("bounded child cancellation observation timed out");
    }
    let (result, ()) = joined.unwrap();
    let result = result.unwrap();
    assert!(
        matches!(result.outcome, ActivationOutcome::Failed { error, .. } if error.code == PlatformErrorCode::Cancelled)
    );
    fixture.idle().await;
    rows.push(capture(fixture, "recovery"));
}

fn capture(fixture: &fixture::Fixture, phase: &str) -> Value {
    let mut value = observation::snapshot(
        "child",
        phase,
        &fixture.backend,
        &fixture.broker,
        None,
        None,
    );
    let quotas = fixture.quotas.usage().unwrap();
    value["quotas"] = observation::fields!(
        quotas,
        active_activations,
        queued_activations,
        reserved_cpu_fuel,
        reserved_memory_bytes
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

fn value(receipt: latent_node::ActivationReceipt) -> u32 {
    match receipt.outcome {
        ActivationOutcome::Succeeded(success) => {
            serde_json::from_slice::<Vec<u32>>(&success.output).unwrap()[0]
        }
        other => panic!("unexpected child result: {other:?}"),
    }
}
