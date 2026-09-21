use crate::{observation, support};
use latent_capabilities::broker::{pools::ProviderPoolLimits, secrets::SecretInvoker};
use latent_executor::{ExecutionBackend, ExecutionCleanup, GuestInterruptionKind, GuestOutcome};
use serde_json::{json, Value};
use std::{
    sync::atomic::Ordering,
    task::{Context, Poll, Waker},
    time::{Duration, Instant},
};

#[path = "../local_secrets/component.rs"]
mod component;
#[path = "../local_secrets/fixture.rs"]
#[allow(dead_code, unused_imports)]
mod fixture;
#[path = "../local_secrets/packages.rs"]
#[allow(dead_code)]
mod packages;

pub async fn measure(rows: &mut Vec<Value>) {
    for ceiling in [1, 2] {
        let fixture = fixture::Fixture::configured(
            None,
            ProviderPoolLimits {
                maximum_running_requests: ceiling,
                maximum_running_per_provider: ceiling,
                maximum_running_per_tenant: ceiling,
                ..ProviderPoolLimits::default()
            },
        )
        .await;
        let mut fixed = capture(&fixture, "fixed");
        fixed["configuredRunningCeiling"] = json!(ceiling);
        rows.push(fixed);
        for ordinal in 0..2 {
            let mut owners = Vec::new();
            for owner in 0..ceiling {
                let (session, control) =
                    fixture.session(&format!("resource-secret-{ordinal}-{owner}"));
                let value = fixture
                    .provider
                    .read(&session, "allowed".into())
                    .unwrap()
                    .await
                    .unwrap();
                owners.push((session, control, value));
            }
            assert_eq!(
                observation::pool_snapshot(&fixture.pools)
                    .0
                    .running_requests,
                ceiling
            );
            let (queued_session, queued_control) = fixture.session("resource-secret-queued");
            let mut pending = fixture
                .provider
                .read(&queued_session, "allowed".into())
                .unwrap();
            assert!(matches!(
                pending
                    .as_mut()
                    .poll(&mut Context::from_waker(Waker::noop())),
                Poll::Pending
            ));
            assert_eq!(
                observation::pool_snapshot(&fixture.pools)
                    .0
                    .pending_requests,
                1
            );
            rows.push(capture(&fixture, "active"));
            queued_control.probe.0.store(true, Ordering::Release);
            drop(pending);
            drop((queued_session, queued_control));
            assert_eq!(
                observation::pool_snapshot(&fixture.pools)
                    .0
                    .pending_requests,
                0
            );
            assert_eq!(
                observation::pool_snapshot(&fixture.pools)
                    .0
                    .running_requests,
                ceiling
            );
            rows.push(capture(&fixture, "cancel-queued"));
            drop(owners);
            fixture.idle();
            rows.push(capture(&fixture, "recovery"));
        }
        for (mode, expected) in [
            (1, 1001_u64),
            (0, (u64::from(b'A') << 32) | (u64::from(b'1') << 16) | 5),
        ] {
            let (request, control) = fixture.request("resource-secret-guest", mode);
            let report = fixture.backend.invoke_contained(request, &control).await;
            assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
            let GuestOutcome::Returned { output, .. } = report.outcome.unwrap() else {
                panic!("secret guest returns a bounded value");
            };
            assert_eq!(
                serde_json::from_slice::<Vec<String>>(&output).unwrap(),
                [expected.to_string()]
            );
            fixture.idle();
            let mut retired = capture(&fixture, "recovery");
            retired["after"] = json!(if mode == 1 {
                "permission-denied"
            } else {
                "guest-success"
            });
            rows.push(retired);
        }
        cancel_guest(&fixture, rows).await;
        shutdown(&fixture).await;
        rows.push(capture(&fixture, "shutdown"));
    }
}

async fn shutdown(fixture: &fixture::Fixture) {
    fixture.secrets.close();
    assert!(fixture
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
}

async fn cancel_guest(fixture: &fixture::Fixture, rows: &mut Vec<Value>) {
    fixture.gate.armed.store(true, Ordering::Release);
    let (request, control) = fixture.request("resource-secret-cancel", 0);
    let (report, ()) = tokio::time::timeout(Duration::from_secs(3), async {
        tokio::join!(fixture.backend.invoke_contained(request, &control), async {
            fixture.gate.entered.notified().await;
            assert_eq!(fixture.broker.snapshot().calls, 1);
            assert_eq!(fixture.backend.resource_snapshot().live_stores, 1);
            rows.push(capture(fixture, "active"));
            control.probe.0.store(true, Ordering::Release);
            fixture.gate.released.notify_one();
        })
    })
    .await
    .unwrap();
    match report.outcome {
        Ok(GuestOutcome::Returned { output, .. }) => {
            assert_eq!(
                serde_json::from_slice::<Vec<String>>(&output).unwrap(),
                ["1003"]
            );
        }
        Ok(GuestOutcome::Interrupted { kind, .. }) => {
            assert_eq!(kind, GuestInterruptionKind::Cancelled);
        }
        Err(error) => assert_eq!(error.code, latent_core::PlatformErrorCode::Cancelled),
        other => panic!("unexpected secret cancellation: {other:?}"),
    }
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    fixture.idle();
    let mut retired = capture(fixture, "recovery");
    retired["after"] = json!("guest-cancellation");
    rows.push(retired);
}

fn capture(fixture: &fixture::Fixture, phase: &str) -> Value {
    let mut value = observation::snapshot(
        "secret",
        phase,
        &fixture.backend,
        &fixture.broker,
        Some(&fixture.pools),
        Some(&fixture.io),
    );
    let secrets = fixture.secrets.snapshot().unwrap();
    value["secretStore"] = observation::fields!(
        secrets,
        generation,
        references,
        retained_generations,
        reserved_generation_bytes,
        loading,
        closed
    );
    value
}
