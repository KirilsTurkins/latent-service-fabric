use super::*;

#[tokio::test]
async fn bounded_lookup_progresses_under_running_pressure_and_keeps_memory_with_actual_socket() {
    let setup = Setup::new(single());
    let initial = setup.pools.snapshot().unwrap().metadata_bytes;
    let deadline = Instant::now() + Duration::from_secs(2);
    let ordinary = setup
        .pools
        .ingress(&setup.client, "tests", deadline, 1, 4096)
        .unwrap();
    assert!(setup
        .pools
        .ingress(&setup.client, "tests", deadline, 1, 4096)
        .is_err());
    let baseline = setup.pools.snapshot().unwrap().metadata_bytes;
    let maintenance = setup.pools.maintenance(&setup.client, deadline, 1).unwrap();
    let request = maintenance.begin_deferred_request(2, 16384).unwrap();
    request.begin_operation().unwrap();
    request.clone().begin_operation().unwrap();
    assert!(request.begin_operation().is_err());
    let before = setup.pools.snapshot().unwrap();
    assert_eq!(before.running_requests, 1);
    assert_eq!(before.cleanup_jobs, 1);
    assert_eq!(before.metadata_bytes, baseline + 4096 + 16384);
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let reservation = setup
        .client
        .reserve_maintenance_connection(&request)
        .unwrap();
    let stream = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
    let (mut peer, _) = listener.accept().unwrap();
    peer.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
    let connection = reservation.connected(stream).unwrap();
    drop((request, maintenance, ordinary));
    let retained = setup.pools.snapshot().unwrap();
    assert_eq!(retained.running_requests, 0);
    assert_eq!(retained.cleanup_jobs, 1);
    assert_eq!(retained.connections, 1);
    assert_eq!(retained.metadata_bytes, initial + 4096 + 16384 + 4096);
    assert!(connection.park().is_err());
    assert_eq!(peer.read(&mut [0]).unwrap(), 0);
    let retired = setup.pools.snapshot().unwrap();
    assert_eq!(retired.cleanup_jobs, 0);
    assert_eq!(retired.connections, 0);
    assert_eq!(retired.metadata_bytes, initial);
    clean(&setup.pools).await;
}

#[tokio::test]
async fn bounded_lookup_cannot_steal_a_live_connection_or_refresh_its_original_deadline() {
    let setup = Setup::new(ProviderPoolLimits {
        maximum_connections: 1,
        maximum_connections_per_client: 1,
        maximum_idle_connections: 1,
        ..single()
    });
    let deadline = Instant::now() + Duration::from_secs(2);
    let ordinary = setup
        .pools
        .ingress(&setup.client, "tests", deadline, 1, 4096)
        .unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let reservation = setup.client.reserve_ingress_connection(&ordinary).unwrap();
    let stream = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
    let (mut peer, _) = listener.accept().unwrap();
    peer.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
    let connection = reservation.connected(stream).unwrap();
    let deadline = Instant::now() + Duration::from_millis(10);
    let maintenance = setup.pools.maintenance(&setup.client, deadline, 1).unwrap();
    assert!(maintenance.begin_deferred_request(17, 16384).is_err());
    assert!(maintenance
        .begin_deferred_request(1, 1024 * 1024 + 1)
        .is_err());
    let request = maintenance.begin_deferred_request(1, 16384).unwrap();
    let before = setup.pools.snapshot().unwrap();
    assert!(setup
        .client
        .reserve_maintenance_connection(&request)
        .is_err());
    assert_eq!(setup.pools.snapshot().unwrap(), before);
    assert!(request
        .wait_for(std::future::pending::<()>())
        .await
        .is_err());
    assert_eq!(request.deadline(), deadline);
    assert_eq!(setup.pools.snapshot().unwrap().cleanup_jobs, 1);
    assert_eq!(setup.pools.snapshot().unwrap().connections, 1);
    drop((request, maintenance));
    assert_eq!(setup.pools.snapshot().unwrap().cleanup_jobs, 0);
    drop((ordinary, connection));
    assert_eq!(peer.read(&mut [0]).unwrap(), 0);
    clean(&setup.pools).await;
}

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
