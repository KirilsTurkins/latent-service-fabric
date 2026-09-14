use super::*;

fn request(setup: &Setup, tenant: &str) -> Result<IngressRequest, PlatformError> {
    setup.pools.ingress(
        &setup.client,
        tenant,
        Instant::now() + Duration::from_secs(2),
        2,
        16384,
    )
}

#[tokio::test]
async fn ingress_socket_keeps_capacity_after_waiter_loss_and_idle_reuse_has_no_call_owner() {
    let setup = Setup::new(single());
    let request = request(&setup, "tests").unwrap();
    let wrong = setup.pools.client::<TcpStream>(&setup.provider, 1).unwrap();
    assert!(wrong.reserve_ingress_connection(&request).is_err());
    let reservation = setup.client.reserve_ingress_connection(&request).unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let stream = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
    let (mut peer, _) = listener.accept().unwrap();
    peer.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
    let local = stream.local_addr().unwrap();
    let connection = reservation.connected(stream).unwrap();
    drop(request);
    assert_eq!(setup.pools.snapshot().unwrap().running_requests, 1);
    assert_eq!(setup.pools.snapshot().unwrap().cleanup_jobs, 0);
    connection.park().unwrap();
    assert_eq!(setup.pools.snapshot().unwrap().running_requests, 0);
    let next = self::request(&setup, "tests").unwrap();
    let mut connection = setup.client.checkout_ingress(&next).unwrap().unwrap();
    assert_eq!(connection.resource().local_addr().unwrap(), local);
    assert_eq!(setup.pools.snapshot().unwrap().connections, 1);
    drop((connection, next));
    assert_eq!(peer.read(&mut [0]).unwrap(), 0);
    clean(&setup.pools).await;
}

#[tokio::test]
async fn ingress_uses_shared_tenant_and_provider_limits_without_claiming_cleanup_slots() {
    let setup = Setup::new(ProviderPoolLimits {
        maximum_running_requests: 2,
        maximum_running_per_tenant: 1,
        maximum_running_per_provider: 2,
        ..ProviderPoolLimits::default()
    });
    let first = request(&setup, "first").unwrap();
    assert!(request(&setup, "first").is_err());
    let second = request(&setup, "second").unwrap();
    assert!(request(&setup, "third").is_err());
    assert_eq!(setup.pools.snapshot().unwrap().running_requests, 2);
    assert_eq!(setup.pools.snapshot().unwrap().cleanup_jobs, 0);
    drop(first);
    let first = request(&setup, "first").unwrap();
    drop((first, second));
    clean(&setup.pools).await;
}

#[tokio::test]
async fn cloned_requests_share_finite_operations_and_rotation_fences_network_work() {
    let setup = Setup::new(single());
    let first = request(&setup, "tests").unwrap();
    let clone = first.clone();
    first.begin_operation().unwrap();
    clone.begin_operation().unwrap();
    assert!(first.begin_operation().is_err());
    assert!(clone.begin_operation().is_err());
    let _replacement = install(&setup.pools, "secrets", 2, 1, b"synthetic-replacement");
    assert!(first.checkpoint().is_err());
    assert!(setup.client.reserve_ingress_connection(&clone).is_err());
    drop((first, clone));
    clean(&setup.pools).await;
}

#[tokio::test]
async fn original_deadline_and_shutdown_interrupt_waits_and_preserve_live_owners() {
    let setup = Setup::new(single());
    let pending = setup
        .pools
        .ingress(
            &setup.client,
            "tests",
            Instant::now() + Duration::from_millis(20),
            1,
            4096,
        )
        .unwrap();
    assert!(pending
        .wait_for(std::future::pending::<()>())
        .await
        .is_err());
    assert_eq!(setup.pools.snapshot().unwrap().running_requests, 1);
    drop(pending);
    let pending = request(&setup, "tests").unwrap();
    setup.pools.retire();
    assert!(pending
        .wait_for(std::future::pending::<()>())
        .await
        .is_err());
    drop(pending);
    clean(&setup.pools).await;
}
