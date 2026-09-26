use crate::{observation, support};
use latent_capabilities::broker::pools::ProviderPoolLimits;
use latent_executor::GuestInterruptionKind;
use latent_nats::NatsConfig;
use serde_json::{json, Value};

#[path = "../nats_events/component.rs"]
mod component;
#[path = "../nats_events/config.rs"]
#[allow(dead_code)]
mod configuration;
#[path = "../nats_events/fixture.rs"]
#[allow(dead_code, unused_imports)]
mod fixture;
#[path = "../nats_events/packages.rs"]
#[allow(dead_code)]
mod packages;
#[path = "../nats_events/proxy.rs"]
#[allow(dead_code)]
mod proxy;
#[path = "../nats_events/stub.rs"]
#[allow(dead_code)]
mod stub;
use configuration::config_for;
use fixture::*;

pub async fn measure(rows: &mut Vec<Value>) {
    for ceiling in [1, 2] {
        let limits = ProviderPoolLimits {
            maximum_running_requests: ceiling,
            maximum_running_per_provider: ceiling,
            maximum_running_per_tenant: ceiling,
            ..ProviderPoolLimits::default()
        };
        let peer = stub::Stub::new(stub::Mode::Healthy).await;
        let prepared = Instant::now();
        let fixture = Fixture::new(peer.config.clone(), None, limits.clone()).await;
        let mut fixed = capture(&fixture, "fixed", ceiling);
        fixed["preparationNanos"] = json!(prepared.elapsed().as_nanos().to_string());
        rows.push(fixed);
        for ordinal in 0..4 {
            let (request, control) = fixture.request(&format!("resource-event-{ordinal}"), 0);
            let started = Instant::now();
            let report = fixture.backend.invoke_contained(request, &control).await;
            let elapsed = started.elapsed();
            assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
            let GuestOutcome::Returned { output, .. } = report.outcome.unwrap() else {
                panic!("event guest did not return an acknowledged publication");
            };
            // The maintained controlled peer returns sequence one, nonduplicate.
            assert_eq!(
                serde_json::from_slice::<Vec<String>>(&output).unwrap(),
                ["2"]
            );
            drop(control);
            fixture.idle();
            let mut recovered = capture(&fixture, "recovery", ceiling);
            recovered["ordinal"] = json!(ordinal);
            recovered["connectionTemperature"] = json!(if ordinal == 0 { "cold" } else { "warm" });
            recovered["latencyNanos"] = json!(elapsed.as_nanos().to_string());
            rows.push(recovered);
        }
        assert_eq!(peer.publishes.load(Ordering::Acquire), 4);
        assert_eq!(fixture.provider.snapshot().acknowledged_publishes, 4);
        assert_eq!(fixture.provider.snapshot().connection_attempts, 1);
        assert_eq!(fixture.provider.snapshot().connection_reuses, 3);
        shutdown(&fixture).await;
        peer.close().await;

        let peer = stub::Stub::new(stub::Mode::Hold).await;
        let fixture = Fixture::new(peer.config.clone(), None, limits).await;
        let mut probes = Vec::new();
        let mut work = Vec::new();
        for ordinal in 0..ceiling {
            let (request, control) = fixture.request(&format!("resource-event-held-{ordinal}"), 0);
            probes.push(control.probe.clone());
            let backend = &fixture.backend;
            work.push(async move { backend.invoke_contained(request, &control).await });
        }
        let received = peer.publishes.clone();
        let completed = async move {
            let first = work.pop().unwrap();
            if let Some(second) = work.pop() {
                assert!(work.is_empty());
                // Establish the first cold connection before starting another.
                // The pool separately bounds simultaneous connection creation;
                // this population measures active publications, not dial races.
                let (first, second) = tokio::join!(first, async {
                    while received.load(Ordering::Acquire) == 0 {
                        tokio::time::sleep(Duration::from_millis(1)).await;
                    }
                    second.await
                });
                vec![first, second]
            } else {
                vec![first.await]
            }
        };
        let outcome = tokio::time::timeout(Duration::from_secs(3), async {
            tokio::join!(completed, async {
                while peer.publishes.load(Ordering::Acquire) < ceiling {
                    peer.observed.notified().await;
                }
                assert_eq!(fixture.provider.snapshot().active_publishes, ceiling);
                assert_eq!(
                    observation::pool_snapshot(&fixture.pools)
                        .0
                        .running_requests,
                    ceiling
                );
                let mut active = capture(&fixture, "active", ceiling);
                active["receivedUnacknowledgedPublications"] = json!(ceiling);
                rows.push(active);
                for probe in probes {
                    probe.0.store(true, Ordering::Release);
                }
            })
        })
        .await;
        let (reports, ()) = outcome.unwrap_or_else(|_| {
            panic!("held publications must reach the peer before cancellation: ceiling={ceiling}, received={}, snapshot={}",
                peer.publishes.load(Ordering::Acquire), capture(&fixture, "timeout", ceiling));
        });
        for report in reports {
            assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
            match report.outcome {
                Ok(GuestOutcome::Returned { output, .. }) => {
                    assert_eq!(
                        serde_json::from_slice::<Vec<String>>(&output).unwrap(),
                        ["1007"]
                    );
                }
                Ok(GuestOutcome::Interrupted { kind, .. }) => {
                    assert_eq!(kind, GuestInterruptionKind::Cancelled);
                }
                Err(error) => assert_eq!(error.code, latent_core::PlatformErrorCode::Cancelled),
                other => panic!("unexpected event cancellation: {other:?}"),
            }
        }
        fixture.idle();
        assert_eq!(
            fixture.io.snapshot(),
            latent_capabilities::broker::io::IoSnapshot::default()
        );
        assert_eq!(observation::pool_snapshot(&fixture.pools).0.connections, 0);
        assert_eq!(fixture.provider.snapshot().active_publishes, 0);
        let mut recovered = capture(&fixture, "recovery", ceiling);
        recovered["after"] = json!("guest-cancellation-after-peer-received-publication");
        recovered["receivedUnacknowledgedPublications"] =
            json!(peer.publishes.load(Ordering::Acquire));
        rows.push(recovered);
        shutdown(&fixture).await;
        peer.close().await;
    }
}

fn capture(fixture: &Fixture, phase: &str, ceiling: usize) -> Value {
    let mut value = observation::snapshot(
        "event",
        phase,
        &fixture.backend,
        &fixture.broker,
        Some(&fixture.pools),
        Some(&fixture.io),
    );
    value["configuredRunningCeiling"] = json!(ceiling);
    let nats = fixture.provider.snapshot();
    value["nats"] = observation::fields!(
        nats,
        configuration_epoch,
        topics,
        active_publishes,
        connection_attempts,
        connection_reuses,
        acknowledged_publishes,
        uncertain_publishes
    );
    value
}

async fn shutdown(fixture: &Fixture) {
    fixture.secrets.close();
    assert!(fixture
        .pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap()
        .is_clean());
}
