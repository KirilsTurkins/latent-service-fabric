use super::*;
#[tokio::test]
async fn malformed_foreign_oversized_and_unavailable_receipts_keep_explicit_semantics() {
    for (mode, error, sent) in [
        (stub::Mode::WrongStream, 1007, 1),
        (stub::Mode::Malformed, 1007, 1),
        (stub::Mode::Oversized, 1007, 1),
        (stub::Mode::NoResponders, 1006, 1),
        (stub::Mode::Flood, 1006, 0),
    ] {
        let stub = stub::Stub::new(mode).await;
        let f = Fixture::new(stub.config.clone(), None, ProviderPoolLimits::default()).await;
        assert_eq!(invoke(&f, 0).await, error);
        assert_eq!(stub.publishes.load(Ordering::Acquire), sent);
        assert_eq!(f.pools.snapshot().unwrap().connections, 0);
        shutdown(&f).await;
        stub.close().await;
    }
}
#[tokio::test]
async fn original_timeout_covers_multiple_protocol_waits_before_publication() {
    let stub = stub::Stub::new(stub::Mode::Slow).await;
    let mut config = stub.config.clone();
    config.timeout_millis = 40;
    let f = Fixture::new(config, None, ProviderPoolLimits::default()).await;
    assert_eq!(invoke(&f, 0).await, 1004);
    assert_eq!(stub.publishes.load(Ordering::Acquire), 0);
    shutdown(&f).await;
    stub.close().await;
}
#[tokio::test]
async fn malformed_inputs_are_rejected_before_network_or_budget_dispatch() {
    let stub = stub::Stub::new(stub::Mode::Healthy).await;
    let f = Fixture::new(stub.config.clone(), None, ProviderPoolLimits::default()).await;
    let (session, owner) = f.session("invalid");
    for which in 0..6 {
        let mut e = event("valid");
        match which {
            0 => e.topic = "$SYS.>".into(),
            1 => e.payload = vec![0; 32769],
            2 => e.idempotency_key.clear(),
            3 => e.attributes = vec![("name".into(), "injected\r\nvalue".into())],
            4 => e.attributes = vec![("same".into(), "a".into()), ("SAME".into(), "b".into())],
            _ => {
                e.payload = Vec::with_capacity(65536);
                e.payload.push(1);
            }
        }
        assert_eq!(
            f.provider.publish(&session, e).err(),
            Some(if which == 0 {
                EventError::InvalidTopic
            } else {
                EventError::InvalidEvent
            })
        );
    }
    assert_eq!(f.provider.snapshot().connection_attempts, 0);
    assert_eq!(stub.publishes.load(Ordering::Acquire), 0);
    drop(session);
    drop(owner);
    f.idle();
    shutdown(&f).await;
    stub.close().await;
}
#[tokio::test]
async fn queued_cancellation_and_dropped_publish_keep_physical_owners_bounded() {
    let stub = stub::Stub::new(stub::Mode::Hold).await;
    let limits = ProviderPoolLimits {
        maximum_running_requests: 1,
        maximum_running_per_provider: 1,
        maximum_running_per_tenant: 1,
        ..Default::default()
    };
    let f = Fixture::new(stub.config.clone(), None, limits).await;
    let (session, owner) = f.session("pending");
    let mut pending = f.provider.publish(&session, event("pending")).unwrap();
    tokio::select! {_=&mut pending=>panic!("publish unexpectedly completed"),()=stub.observed.notified()=>(),()=tokio::time::sleep(Duration::from_secs(1))=>panic!("publish not observed")}
    let (queued_session, queued_owner) = f.session("queued");
    let queued = f
        .provider
        .publish(&queued_session, event("queued"))
        .unwrap();
    queued_owner.probe.0.store(true, Ordering::Release);
    assert_eq!(queued.await.err(), Some(EventError::Cancelled));
    assert_eq!(stub.publishes.load(Ordering::Acquire), 1);
    assert_eq!(f.pools.snapshot().unwrap().connections, 1);
    drop(queued_session);
    drop(queued_owner);
    drop(pending);
    drop(session);
    drop(owner);
    f.idle();
    assert_eq!(
        f.io.snapshot(),
        latent_capabilities::broker::io::IoSnapshot::default()
    );
    assert_eq!(f.pools.snapshot().unwrap().connections, 0);
    shutdown(&f).await;
    stub.close().await;
}
