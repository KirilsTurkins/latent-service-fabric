use super::*;

#[tokio::test]
async fn trusted_configuration_waits_for_registry_bookkeeping_without_reinstalling() {
    use std::sync::mpsc::{channel, RecvTimeoutError};

    let setup = Setup::new(ProviderPoolLimits::default());
    for install_epoch in [true, false] {
        let registry = setup.pools.inner.state.lock().unwrap();
        let (started, entered) = channel();
        let (completed, result) = channel();
        std::thread::scope(|scope| {
            let worker = scope.spawn(|| {
                started.send(()).unwrap();
                if install_epoch {
                    let installed = install(&setup.pools, "configuration-contention", 1, 0, b"");
                    assert_eq!(installed.reference().configuration_epoch(), 1);
                } else {
                    let client = setup.pools.client::<TcpStream>(&setup.provider, 1).unwrap();
                    assert!(Arc::ptr_eq(
                        &client,
                        &setup.pools.client::<TcpStream>(&setup.provider, 1).unwrap()
                    ));
                }
                completed.send(()).unwrap();
            });
            entered.recv_timeout(Duration::from_secs(1)).unwrap();
            let waiting = matches!(
                result.recv_timeout(Duration::from_millis(50)),
                Err(RecvTimeoutError::Timeout)
            );
            drop(registry);
            result.recv_timeout(Duration::from_secs(1)).unwrap();
            worker.join().unwrap();
            assert!(
                waiting,
                "configuration must wait for finite registry bookkeeping"
            );
        });
    }
    assert_eq!(
        setup
            .pools
            .provider("configuration-contention")
            .unwrap()
            .reference()
            .configuration_epoch(),
        1
    );
    clean(&setup.pools).await;
}

#[tokio::test]
async fn replacement_epoch_cannot_bypass_logical_provider_running_limits() {
    let setup = Setup::new(ProviderPoolLimits {
        maximum_running_requests: 2,
        maximum_running_per_tenant: 2,
        maximum_running_per_provider: 1,
        maximum_clients_per_provider: 2,
        ..ProviderPoolLimits::default()
    });
    let (old_session, _old_control) = setup.session("before-rotation");
    let old_call = setup.call(&old_session).await;
    let replacement = install(&setup.pools, "secrets", 2, 1, b"replacement-test-secret");
    let next_client = setup.pools.client::<TcpStream>(&replacement, 0).unwrap();
    assert!(setup.pools.client::<TcpStream>(&replacement, 1).is_err());
    let document = serde_json::to_vec(&serde_json::json!({
        "formatVersion":1,"tenant":"a","capability":CAP,"providerProfile":"local-secrets-v1",
        "configurationDigest":format!("sha256:{}","2".repeat(64)),"configurationEpoch":2,"restriction":{"operations":[]}
    })).unwrap();
    let revision = setup
        .fixture
        .policies
        .get(
            "a",
            latent_policy::capability::RecordKind::ProviderBinding,
            "binding",
            65536,
            Instant::now() + Duration::from_secs(1),
        )
        .unwrap()
        .value()
        .as_ref()
        .unwrap()
        .revision;
    setup
        .fixture
        .policies
        .mutate(
            latent_policy::capability::MutationRequest {
                tenant: "a",
                actor: "operator",
                id: "binding",
                kind: latent_policy::capability::RecordKind::ProviderBinding,
                operation_id: "rotate-binding",
                expected_revision: revision,
                document: Some(&document),
            },
            Instant::now() + Duration::from_secs(1),
            |_| Ok(()),
        )
        .unwrap();
    let (new_session, _new_control) = setup.session_for(&replacement, "a", "after-rotation");
    let mut waiting = Box::pin(
        setup
            .pools
            .admit(&next_client, &new_session)
            .unwrap()
            .wait(),
    );
    pending(waiting.as_mut());
    assert_eq!(setup.pools.snapshot().unwrap().running_requests, 1);
    drop(old_call);
    let call = waiting
        .await
        .unwrap()
        .start(dispatch(&new_session))
        .unwrap();
    drop(call);
    drop((old_session, new_session));
    clean(&setup.pools).await;
}

#[tokio::test]
async fn provider_request_ceiling_preserves_admission_space_for_other_providers() {
    let setup = Setup::new(ProviderPoolLimits {
        maximum_requests_per_provider: 1,
        maximum_running_per_provider: 1,
        ..ProviderPoolLimits::default()
    });
    let (session, _control) = setup.session("quota-provider");
    let call = setup.call(&session).await;
    let (second, _second_control) = setup.session("quota-provider-next");
    assert!(setup.pools.admit(&setup.client, &second).is_err());
    let other = install(&setup.pools, "other-provider", 1, 0, b"test-other");
    let client = setup.pools.client::<TcpStream>(&other, 0).unwrap();
    let (other_session, _other_control) = setup.session_for(&other, "a", "quota-other");
    let other_call = start(&setup.pools, &client, &other_session).await;
    assert_eq!(setup.pools.snapshot().unwrap().running_requests, 2);
    drop((call, other_call));
    drop((session, second, other_session));
    clean(&setup.pools).await;
}

#[tokio::test]
async fn rotation_closes_later_admissions_and_retains_old_credentials_and_connections() {
    let setup = Setup::new(single());
    let (session, _control) = setup.session("old-epoch");
    let call = setup.call(&session).await;
    let (first, mut peer) = connect(&setup.client, &call);
    let (second, _peer2) = connect(&setup.client, &call);
    let (queued, _queued_control) = setup.session("queued-old-epoch");
    let waiting = setup.pools.admit(&setup.client, &queued).unwrap();
    let mut waiting = Box::pin(waiting.wait());
    pending(waiting.as_mut());
    let replacement = install(&setup.pools, "secrets", 2, 1, b"test-secret-new");
    assert!(waiting.await.is_err());
    assert!(setup.pools.admit(&setup.client, &session).is_err());
    assert!(setup.pools.client::<TcpStream>(&setup.provider, 1).is_err());
    assert_eq!(
        setup.provider.with_credentials(<[u8]>::to_vec),
        b"test-secret-old"
    );
    assert_eq!(
        replacement.with_credentials(<[u8]>::to_vec),
        b"test-secret-new"
    );
    assert_eq!(
        setup.provider.reference().entry.digest,
        replacement.reference().entry.digest
    );
    call.io().checkpoint().unwrap();
    let report = setup.pools.snapshot().unwrap();
    assert_eq!(report.configurations, 1);
    assert_eq!(report.retained_configurations, 2);
    assert_eq!(report.connections, 2);
    let mut lower = setup.pools.inner.quotas.limits().unwrap();
    lower.maximum_connections_per_client = 1;
    assert!(setup.pools.lower_limits(lower).is_err());
    assert!(!format!("{report:?}").contains("test-secret"));
    drop(second);
    setup.pools.lower_limits(lower).unwrap();
    // An accepted old call may finish, but cannot refill an old idle pool.
    assert!(first.park().is_err());
    assert_eq!(peer.read(&mut [0]).unwrap(), 0);
    drop(call);
    drop((session, queued));
    clean(&setup.pools).await;
}

#[tokio::test]
async fn rejected_rotation_and_duplicate_registry_leave_installed_owner_unchanged() {
    let setup = Setup::new(ProviderPoolLimits {
        maximum_configurations: 1,
        ..ProviderPoolLimits::default()
    });
    assert!(ProviderPools::new(
        setup.fixture.broker.clone(),
        Arc::new(IoRuntime::new(IoLimits::default()).unwrap()),
        tokio::runtime::Handle::current(),
        ProviderPoolLimits::default()
    )
    .is_err());
    let new = ProviderSetup {
        logical_id: "secrets",
        credentials: b"replacement",
        authority: crate::broker::ProviderConfiguration {
            capability: CAP,
            profile: "local-secrets-v1",
            configuration_digest: &format!("sha256:{}", "2".repeat(64)),
            configuration_epoch: 2,
            restriction_json: br#"{"operations":[]}"#,
            minimum_call_charges: &[],
        },
    };
    assert!(setup.pools.install(new, 1).is_err());
    let current = setup.pools.provider("secrets").unwrap();
    assert!(Arc::ptr_eq(&current.epoch, &setup.provider.epoch));
    let (session, _control) = setup.session("still-installed");
    drop(setup.call(&session).await);
    drop(session);
    clean(&setup.pools).await;
}

#[tokio::test]
async fn queue_age_and_idle_age_are_enforced_at_use() {
    let setup = Setup::new(ProviderPoolLimits {
        maximum_queue_age: Duration::from_millis(20),
        maximum_idle_age: Duration::from_millis(20),
        ..single()
    });
    let (session, _control) = setup.session("expiry-active");
    let call = setup.call(&session).await;
    let (connection, mut peer) = connect(&setup.client, &call);
    connection.park().unwrap();
    let (other, _other_control) = setup.session("expiry-waiting");
    let waiting = setup.pools.admit(&setup.client, &other).unwrap();
    assert!(waiting.wait().await.is_err());
    assert!(setup.client.checkout(&call).unwrap().is_none());
    assert_eq!(peer.read(&mut [0]).unwrap(), 0);
    drop(call);
    drop((session, other));
    clean(&setup.pools).await;
}

#[tokio::test]
async fn cancelled_dial_and_reconnect_storm_do_not_create_connections_or_tasks() {
    let setup = Setup::new(ProviderPoolLimits {
        initial_backoff: Duration::from_millis(20),
        maximum_backoff: Duration::from_millis(40),
        ..ProviderPoolLimits::default()
    });
    let (session, _control) = setup.session("dial");
    let call = setup.call(&session).await;
    let reserved = setup.client.reserve_connection(&call).unwrap();
    assert!(setup.client.reserve_connection(&call).is_err());
    assert_eq!(setup.pools.snapshot().unwrap().connections, 1);
    drop(reserved);
    assert!(setup.client.retry_after().unwrap().unwrap() <= Duration::from_millis(20));
    let before = setup.pools.snapshot().unwrap();
    for _ in 0..64 {
        assert!(setup.client.reserve_connection(&call).is_err());
    }
    assert_eq!(setup.pools.snapshot().unwrap(), before);
    tokio::time::sleep(Duration::from_millis(25)).await;
    drop(setup.client.reserve_connection(&call).unwrap());
    assert!(setup.client.retry_after().unwrap().unwrap() <= Duration::from_millis(40));
    assert_eq!(setup.pools.snapshot().unwrap().workers, 0);
    assert_eq!(setup.pools.snapshot().unwrap().connections, 0);
    drop(call);
    drop(session);
    clean(&setup.pools).await;
}
