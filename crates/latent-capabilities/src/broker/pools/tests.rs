use super::*;
use crate::broker::{
    io::{IoLimits, IoRuntime},
    tests::fixture::*,
    CapabilityBrokerLimits, CapabilityCallCost, CapabilitySession, ProviderCall,
};
use std::{
    io::Read,
    net::{TcpListener, TcpStream},
    time::Duration,
};
mod fixture;
mod lifecycle;
mod maintenance;
mod protocol;
mod shutdown;
use fixture::*;

#[tokio::test]
async fn idle_socket_is_shared_while_activation_ownership_is_reclaimed() {
    let setup = Setup::new(ProviderPoolLimits::default());
    assert!(Arc::ptr_eq(
        &setup.client,
        &setup.pools.client(&setup.provider, 0).unwrap()
    ));
    let (session, _control) = setup.session("idle-first");
    let observer = session.observer();
    let call = setup.call(&session).await;
    let (mut connection, mut peer) = connect(&setup.client, &call);
    let local = connection.resource().local_addr().unwrap();
    connection.park().unwrap();
    drop(call);
    drop(session);
    assert!(observer.is_quiescent());
    assert_eq!(setup.pools.snapshot().unwrap().idle_connections, 1);
    let (session, _control) = setup.session("idle-second");
    let call = setup.call(&session).await;
    let mut connection = setup.client.checkout(&call).unwrap().unwrap();
    assert_eq!(connection.resource().local_addr().unwrap(), local);
    assert_eq!(setup.pools.snapshot().unwrap().connections, 1);
    assert_eq!(setup.pools.snapshot().unwrap().idle_connections, 0);
    drop(connection);
    assert_eq!(peer.read(&mut [0]).unwrap(), 0);
    drop(call);
    drop(session);
    clean(&setup.pools).await;
}

#[tokio::test]
async fn fixed_limits_reserve_before_dial_and_lowering_preserves_live_owners() {
    let setup = Setup::new(ProviderPoolLimits {
        maximum_connections: 2,
        maximum_connections_per_client: 2,
        maximum_idle_connections: 2,
        ..ProviderPoolLimits::default()
    });
    let (session, _control) = setup.session("limits");
    let call = setup.call(&session).await;
    let (first, _peer) = connect(&setup.client, &call);
    let (second, _peer2) = connect(&setup.client, &call);
    let before = setup.pools.snapshot().unwrap();
    for _ in 0..32 {
        assert!(setup.client.reserve_connection(&call).is_err());
    }
    assert_eq!(setup.pools.snapshot().unwrap(), before);
    let mut next = setup.pools.inner.quotas.limits().unwrap();
    next.maximum_connections_per_client = 1;
    assert!(setup.pools.lower_limits(next).is_err());
    drop(second);
    setup.pools.lower_limits(next).unwrap();
    assert!(setup.client.reserve_connection(&call).is_err());
    assert!(setup
        .pools
        .lower_limits(ProviderPoolLimits::default())
        .is_err());
    drop(first);
    drop(call);
    drop(session);
    clean(&setup.pools).await;
}

#[tokio::test]
async fn cancelled_queue_input_keeps_its_actual_tenant_and_byte_ownership() {
    let setup = Setup::new(single());
    let (session, _control) = setup.session("occupied");
    let occupied = setup.call(&session).await;
    let (other, control) = setup.session("cancel-queue");
    let observer = other.observer();
    let admission = setup.pools.admit(&setup.client, &other).unwrap();
    let input = admission.input(32, 16).unwrap();
    let mut wait = Box::pin(admission.wait());
    pending(wait.as_mut());
    control.probe.0.store(true, Ordering::Release);
    assert!(wait.await.is_err());
    drop(other);
    assert!(!observer.is_quiescent());
    assert_eq!(setup.pools.snapshot().unwrap().pending_requests, 1);
    let usage = setup.fixture.broker.inspect_node_usage().unwrap();
    assert_eq!(usage.pools.unwrap().pending_requests, 1);
    assert!(usage.io.unwrap().staged_bytes >= 32);
    let tenant = setup
        .fixture
        .broker
        .inspect_tenant_usage(&latent_core::TenantId("a".into()))
        .unwrap();
    assert!(tenant.waiting > 0);
    drop(input);
    assert!(observer.is_quiescent());
    assert_eq!(setup.pools.snapshot().unwrap().pending_requests, 0);
    assert_eq!(
        setup
            .fixture
            .broker
            .inspect_node_usage()
            .unwrap()
            .pools
            .unwrap()
            .pending_requests,
        0
    );
    drop(occupied);
    drop(session);
    clean(&setup.pools).await;
}

#[tokio::test]
async fn tenant_round_robin_prevents_a_busy_tenant_from_requeueing_ahead() {
    let setup = Setup::new(single());
    let (first, _first_control) = setup.session("tenant-a-first");
    let running = setup.call(&first).await;
    let (second, _second_control) = setup.session("tenant-a-second");
    let (other, _other_control) = setup.session_for(&setup.provider, "b", "tenant-b-first");
    let mut a = Box::pin(setup.pools.admit(&setup.client, &second).unwrap().wait());
    let mut b = Box::pin(setup.pools.admit(&setup.client, &other).unwrap().wait());
    pending(a.as_mut());
    pending(b.as_mut());
    drop(running);
    pending(a.as_mut());
    let b = b.await.unwrap().start(dispatch(&other)).unwrap();
    pending(a.as_mut());
    drop(b);
    let a = a.await.unwrap().start(dispatch(&second)).unwrap();
    drop(a);
    drop((first, second, other));
    clean(&setup.pools).await;
}

#[tokio::test]
async fn provider_round_robin_and_final_broker_check_follow_the_queue() {
    let setup = Setup::new(single());
    let alternate = install(&setup.pools, "other", 1, 0, b"other-public-test-secret");
    let client = setup.pools.client::<TcpStream>(&alternate, 0).unwrap();
    let (first, _one) = setup.session("provider-first");
    let running = setup.call(&first).await;
    let (second, _two) = setup.session("provider-second");
    let (other, _three) = setup.session_for(&alternate, "a", "provider-other");
    let mut a = Box::pin(setup.pools.admit(&setup.client, &second).unwrap().wait());
    let mut b = Box::pin(setup.pools.admit(&client, &other).unwrap().wait());
    pending(a.as_mut());
    pending(b.as_mut());
    drop(running);
    pending(a.as_mut());
    let ready = b.await.unwrap();
    // A valid call for another installed provider cannot consume this slot.
    assert!(ready.start(dispatch(&second)).is_err());
    let ready = a.await.unwrap();
    setup.fixture.revoke_policy();
    assert!(second.bind(CAP, "read", resource()).is_err());
    drop(ready);
    drop((first, second, other));
    clean(&setup.pools).await;
}
