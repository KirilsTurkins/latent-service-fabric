//! Explicit pool quarantine doubles; these do not certify a native kernel owner.
use super::*;
use crate::tests::{config, fixture::Fixture};
use latent_capabilities::broker::network::OutboundStreamInvoker;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

struct Retained(Arc<AtomicBool>);

fn quarantine(fixture: &Fixture, provider: &StreamProvider) -> Arc<AtomicBool> {
    let retired = Arc::new(AtomicBool::new(false));
    let client = fixture
        .pools
        .client::<Retained>(&provider.inner.installed, 1)
        .unwrap();
    let owner = fixture
        .pools
        .maintenance(&client, Instant::now() + Duration::from_secs(30), 1)
        .unwrap();
    let request = owner.begin_request().unwrap();
    let reservation = client.reserve_maintenance_connection(&request).unwrap();
    reservation.quarantine_stream(Retained(retired.clone()), |value| {
        value.0.load(Ordering::Acquire)
    });
    retired
}

#[tokio::test]
async fn quarantine_is_observed_once_across_current_and_retired_generations() {
    let configuration = config();
    let fixture = Fixture::new(configuration.clone());
    let lifecycle = Arc::new(
        StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
            .unwrap(),
    );
    let runtime = fixture.runtime();
    runtime.install_outbound_streams(lifecycle.clone()).unwrap();
    let old = fixture.provider.clone();
    let old_retired = quarantine(&fixture, &old);
    let before = lifecycle.status().unwrap();
    assert_eq!(before.quarantined_connections, 1);
    assert_eq!(before.usage.owners, 1);
    assert_eq!(before.usage.connections, 1);

    lifecycle.rotate(1, 2, configuration).unwrap();
    let current = lifecycle.state.lock().unwrap().current.clone();
    let current_retired = quarantine(&fixture, &current);
    let combined = lifecycle.status().unwrap();
    assert_eq!(combined.retired_generations, 1);
    assert_eq!(combined.quarantined_connections, 2);
    assert_eq!(combined.usage.owners, 2);
    assert_eq!(combined.usage.connections, 2);
    let observed = lifecycle.inspect_node_usage().unwrap().unwrap();
    assert_eq!(observed.quarantined_connections, Some(2));
    assert_eq!(observed.owners, 2);
    assert_eq!(observed.connections, 2);
    assert_eq!(
        fixture
            .broker
            .inspect_node_usage()
            .unwrap()
            .streams
            .unwrap(),
        observed
    );

    let guard = lifecycle.state.lock().unwrap();
    assert!(lifecycle.inspect_node_usage().is_err());
    drop(guard);
    old_retired.store(true, Ordering::Release);
    fixture
        .pools
        .maintain_stream_quarantine(&old.inner.installed, Instant::now());
    assert_eq!(lifecycle.status().unwrap().quarantined_connections, 1);
    current_retired.store(true, Ordering::Release);
    fixture
        .pools
        .maintain_stream_quarantine(&current.inner.installed, Instant::now());
    let drained = lifecycle
        .drain(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap();
    assert_eq!(drained.quarantined_connections, 0);
    assert_eq!(drained.usage.owners, 0);
    assert_eq!(drained.usage.connections, 0);
    drop(runtime);
    drop(lifecycle);
    drop(current);
    drop(old);
    fixture.clean().await;
}

#[test]
fn quarantine_sum_refuses_overflow() {
    assert_eq!(sum_quarantined(4, 3).unwrap(), 7);
    assert_eq!(
        sum_quarantined(usize::MAX, 1).unwrap_err().code,
        StreamErrorCode::Exhausted
    );
}
