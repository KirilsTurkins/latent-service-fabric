//! Explicit pool quarantine doubles; these do not certify a native kernel owner.
use super::*;
use crate::connection_registry::RetirementCustody;
use crate::tests::{config, fixture::Fixture};
use latent_capabilities::broker::network::OutboundStreamInvoker;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

struct Retained(Arc<AtomicBool>);
struct Custodied {
    retired: Arc<AtomicBool>,
    _opening: RetirementCustody,
}
struct FailingDrop(RetirementCustody);
impl Drop for FailingDrop {
    fn drop(&mut self) {
        self.0.begin_drop();
        panic!("simulated owner destructor failure");
    }
}

#[tokio::test]
async fn failed_drop_keeps_a_bounded_row_without_leaking_the_marker() {
    let fixture = Fixture::new(config());
    let lifecycle =
        StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
            .unwrap();
    let opening = fixture
        .provider
        .inner
        .connections
        .reserve_opening()
        .unwrap();
    let marker = opening.marker_weak_for_test();
    let owner = FailingDrop(opening.try_clone_custody().unwrap());
    drop(opening);
    assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(owner))).is_err());
    assert_eq!(lifecycle.status().unwrap().usage.owners, 1);
    drop(lifecycle);
    fixture.clean().await;
    drop(fixture);
    assert!(marker.upgrade().is_none());
}

#[tokio::test]
async fn setup_custody_keeps_row_when_preceding_destructor_starts_unwind() {
    struct PanicFirst;
    impl Drop for PanicFirst {
        fn drop(&mut self) {
            panic!("simulated intervening destructor failure");
        }
    }
    struct SetupOwners {
        _first: PanicFirst,
        _custody: RetirementCustody,
    }

    let fixture = Fixture::new(config());
    let lifecycle =
        StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
            .unwrap();
    let opening = fixture
        .provider
        .inner
        .connections
        .reserve_opening()
        .unwrap();
    let marker = opening.marker_weak_for_test();
    let owners = SetupOwners {
        _first: PanicFirst,
        _custody: opening.try_clone_custody().unwrap(),
    };
    drop(opening);
    assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(owners))).is_err());
    assert_eq!(lifecycle.status().unwrap().usage.owners, 1);
    drop(lifecycle);
    fixture.clean().await;
    drop(fixture);
    assert!(marker.upgrade().is_none());
}

#[tokio::test]
async fn prepaid_openings_are_bounded_and_keep_the_original_pool_charge() {
    let fixture = Fixture::new(config());
    let registry = Arc::clone(&fixture.provider.inner.connections);
    let weak = Arc::downgrade(&registry);
    let mut openings = Vec::new();
    for _ in 0..crate::connection_registry::CAPACITY {
        openings.push(registry.reserve_opening().unwrap());
    }
    assert!(registry.reserve_opening().is_err());
    drop(openings.pop());
    openings.push(registry.reserve_opening().unwrap());
    let held = openings.pop().unwrap();
    drop(openings);
    drop(registry);
    let pools = fixture.pools.clone();
    fixture.clean().await;
    drop(fixture);
    assert!(weak.upgrade().is_none());
    let retained_metadata = pools.snapshot().unwrap().metadata_bytes;
    drop(held);
    assert!(pools.snapshot().unwrap().metadata_bytes < retained_metadata);
}

#[tokio::test]
async fn opening_stays_visible_while_dial_is_quarantined() {
    let fixture = Fixture::new(config());
    let lifecycle =
        StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
            .unwrap();
    let opening = fixture
        .provider
        .inner
        .connections
        .reserve_opening()
        .unwrap();
    let retired = Arc::new(AtomicBool::new(false));
    let client = fixture
        .pools
        .client::<Custodied>(&fixture.provider.inner.installed, 1)
        .unwrap();
    let owner = fixture
        .pools
        .maintenance(&client, Instant::now() + Duration::from_secs(30), 1)
        .unwrap();
    let request = owner.begin_request().unwrap();
    let reservation = client.reserve_maintenance_connection(&request).unwrap();
    reservation.quarantine_stream(
        Custodied {
            retired: retired.clone(),
            _opening: opening.try_clone_custody().unwrap(),
        },
        |value| value.retired.load(Ordering::Acquire),
    );
    drop(opening);
    let retained = lifecycle.status().unwrap();
    assert!(retained.usage.owners > 0);
    assert_eq!(retained.quarantined_connections, 1);
    assert_eq!(retained.usage.pending_operations, 0);
    retired.store(true, Ordering::Release);
    fixture
        .pools
        .maintain_stream_quarantine(&fixture.provider.inner.installed, Instant::now());
    let released = lifecycle.status().unwrap();
    assert_eq!(released.usage.owners, 0);
    assert_eq!(released.quarantined_connections, 0);
    drop(request);
    drop(owner);
    drop(client);
    drop(lifecycle);
    fixture.clean().await;
}

#[tokio::test]
async fn opening_stays_visible_while_connected_pool_is_quarantined() {
    let fixture = Fixture::new(config());
    let lifecycle =
        StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
            .unwrap();
    let opening = fixture
        .provider
        .inner
        .connections
        .reserve_opening()
        .unwrap();
    let retired = Arc::new(AtomicBool::new(false));
    let client = fixture
        .pools
        .client::<Custodied>(&fixture.provider.inner.installed, 1)
        .unwrap();
    let owner = fixture
        .pools
        .maintenance(&client, Instant::now() + Duration::from_secs(30), 1)
        .unwrap();
    let request = owner.begin_request().unwrap();
    let reservation = client.reserve_maintenance_connection(&request).unwrap();
    let connection = match reservation.connected(Custodied {
        retired: retired.clone(),
        _opening: opening.try_clone_custody().unwrap(),
    }) {
        Ok(connection) => connection,
        Err(error) => panic!("same original connection refused: {error:?}"),
    };
    connection.quarantine_stream(|value| value.retired.load(Ordering::Acquire));
    drop(opening);
    let retained = lifecycle.status().unwrap();
    assert!(retained.usage.owners > 0);
    assert_eq!(retained.quarantined_connections, 1);
    assert_eq!(retained.usage.pending_operations, 0);
    retired.store(true, Ordering::Release);
    fixture
        .pools
        .maintain_stream_quarantine(&fixture.provider.inner.installed, Instant::now());
    let released = lifecycle.status().unwrap();
    assert_eq!(released.usage.owners, 0);
    assert_eq!(released.quarantined_connections, 0);
    drop(request);
    drop(owner);
    drop(client);
    drop(lifecycle);
    fixture.clean().await;
}

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
