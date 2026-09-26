use super::*;
#[tokio::test]
#[ignore = "requires tools/run_nats_event_tests.py owned pinned TLS JetStream"]
async fn real_nats_lost_ack_cancelled_guest_outage_and_fresh_connection_recovery() {
    control("reset-fixture");
    let proxy = proxy::Proxy::new(config()).await;
    let f = Fixture::new(proxy.config.clone(), None, ProviderPoolLimits::default()).await;
    proxy.mode.store(proxy::DROP_ACK, Ordering::Release);
    assert_eq!(invoke(&f, 0).await, 1007);
    assert_eq!(control("info")["messages"], 1);
    assert_eq!(f.provider.snapshot().uncertain_publishes, 1);
    assert_eq!(f.pools.snapshot().unwrap().connections, 0);
    // Only the caller explicitly retries, within the broker's duplicate window.
    proxy.mode.store(proxy::HEALTHY, Ordering::Release);
    assert_eq!(invoke(&f, 0).await, 3);
    control("reset-fixture");
    proxy.mode.store(proxy::HOLD_ACK, Ordering::Release);
    while tokio::time::timeout(Duration::from_millis(1), proxy.seen.notified())
        .await
        .is_ok()
    {}
    let (request, cancellation) = f.request("cancelled-guest", 0);
    let mut pending = Box::pin(f.backend.invoke_contained(request, &cancellation));
    tokio::select! {
        result=&mut pending=>panic!("guest completed before gated broker ack: {:?}",result.outcome),
        ()=proxy.seen.notified()=>(),
        ()=tokio::time::sleep(Duration::from_secs(2))=>panic!("broker acknowledgement not observed"),
    }
    assert_eq!(control("info")["messages"], 1);
    cancellation.probe.0.store(true, Ordering::Release);
    let report = tokio::time::timeout(Duration::from_secs(1), &mut pending)
        .await
        .unwrap();
    drop(pending);
    match report.outcome {
        Ok(GuestOutcome::Returned { output, .. }) => assert_eq!(
            serde_json::from_slice::<Vec<String>>(&output).unwrap(),
            ["1007"]
        ),
        Ok(GuestOutcome::Interrupted { kind, .. }) => {
            assert_eq!(kind, latent_executor::GuestInterruptionKind::Cancelled)
        }
        Err(error) => assert_eq!(error.code, latent_core::PlatformErrorCode::Cancelled),
        other => panic!("unexpected cancellation outcome: {other:?}"),
    }
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    drop(cancellation);
    f.idle();
    assert_eq!(
        f.io.snapshot(),
        latent_capabilities::broker::io::IoSnapshot::default()
    );
    assert_eq!(f.pools.snapshot().unwrap().connections, 0);
    proxy.mode.store(proxy::REFUSE, Ordering::Release);
    let (session, owner) = f.session("outage");
    assert_eq!(
        f.provider
            .publish(&session, event("outage"))
            .unwrap()
            .await
            .err(),
        Some(EventError::Unavailable)
    );
    drop(session);
    drop(owner);
    f.idle();
    assert_eq!(control("info")["messages"], 1);
    proxy.mode.store(proxy::HEALTHY, Ordering::Release);
    tokio::time::sleep(Duration::from_millis(120)).await;
    let (session, owner) = f.session("recovered");
    let reply = f
        .provider
        .publish(&session, event("recovered"))
        .unwrap()
        .await
        .unwrap();
    assert_eq!(reply.receipt.sequence, 2);
    drop(reply);
    drop(session);
    drop(owner);
    f.idle();
    assert_eq!(control("info")["messages"], 2);
    shutdown(&f).await;
    proxy.close().await;
}
