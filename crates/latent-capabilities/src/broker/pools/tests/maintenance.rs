use super::*;

#[tokio::test]
async fn operator_recovery_retains_its_slot_until_the_actual_socket_retires() {
    let setup = Setup::new(ProviderPoolLimits {
        maximum_cleanup_jobs: 1,
        ..ProviderPoolLimits::default()
    });
    let deadline = Instant::now() + Duration::from_secs(2);
    let permit = setup.pools.maintenance(&setup.client, deadline, 2).unwrap();
    assert!(setup.pools.maintenance(&setup.client, deadline, 1).is_err());
    let request = permit.begin_request().unwrap();
    assert!(permit.begin_request().is_err());
    let other = setup.pools.client::<TcpStream>(&setup.provider, 1).unwrap();
    assert!(other.reserve_maintenance_connection(&request).is_err());
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let reservation = setup
        .client
        .reserve_maintenance_connection(&request)
        .unwrap();
    let stream = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
    let (mut peer, _) = listener.accept().unwrap();
    peer.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
    let connection = reservation.connected(stream).unwrap();
    drop(request);
    drop(permit);
    assert_eq!(setup.pools.snapshot().unwrap().cleanup_jobs, 1);
    assert_eq!(setup.pools.snapshot().unwrap().connections, 1);
    assert!(connection.park().is_err());
    assert_eq!(peer.read(&mut [0]).unwrap(), 0);
    assert_eq!(setup.pools.snapshot().unwrap().cleanup_jobs, 0);
    assert_eq!(setup.pools.snapshot().unwrap().connections, 0);
    assert!(setup
        .pools
        .shutdown(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap()
        .is_clean());
}

#[tokio::test]
async fn maintenance_is_finite_and_fenced_by_deadline_and_provider_rotation() {
    let setup = Setup::new(ProviderPoolLimits::default());
    assert!(setup
        .pools
        .maintenance(&setup.client, Instant::now() + Duration::from_secs(121), 1)
        .is_err());
    assert!(setup
        .pools
        .maintenance(&setup.client, Instant::now() + Duration::from_secs(1), 65)
        .is_err());
    let permit = setup
        .pools
        .maintenance(&setup.client, Instant::now() + Duration::from_secs(1), 1)
        .unwrap();
    let request = permit.begin_request().unwrap();
    drop(request);
    assert!(permit.begin_request().is_err());
    drop(permit);
    let permit = setup
        .pools
        .maintenance(&setup.client, Instant::now() + Duration::from_millis(5), 1)
        .unwrap();
    let request = permit.begin_request().unwrap();
    tokio::time::sleep(Duration::from_millis(10)).await;
    assert!(request.checkpoint().is_err());
    drop(request);
    drop(permit);
    let permit = setup
        .pools
        .maintenance(&setup.client, Instant::now() + Duration::from_secs(1), 1)
        .unwrap();
    let request = permit.begin_request().unwrap();
    let _replacement = install(&setup.pools, "secrets", 2, 1, b"synthetic-replacement");
    assert!(request.checkpoint().is_err());
    assert!(permit.begin_request().is_err());
    drop(request);
    drop(permit);
    assert!(setup
        .pools
        .shutdown(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap()
        .is_clean());
}
