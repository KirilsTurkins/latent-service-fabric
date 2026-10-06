use super::*;
use proxy::{Loss, Proxy};

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn qualified_tls_delivery_and_equal_key_replay_mutate_remote_durable_counter_once() {
    let clock = Arc::new(Clock(AtomicU64::new(100)));
    let endpoint = Endpoint::new(clock, Fault::Normal).await;
    let fixture = Fixture::new(endpoint.port, endpoint.root_certificate.clone(), 2000).await;
    let first = fixture.run(1, b"exact immutable body\0").await;
    let replay = fixture.run(1, b"exact immutable body\0").await;
    assert_eq!(first.receipt.disposition, Disposition::ProviderAcknowledged);
    assert_eq!(
        first.receipt.provider_receipt,
        replay.receipt.provider_receipt
    );
    assert_eq!(endpoint.attempts(), (2, 0));
    assert_eq!(endpoint.counter(), 1);
    endpoint.assert_applied(
        1,
        b"exact immutable body\0",
        first.receipt.provider_receipt.as_deref().unwrap(),
        10_100,
    );
    let changed = fixture.run(1, b"changed immutable body").await;
    assert_eq!(changed.receipt.disposition, Disposition::KnownFailed);
    assert!(changed.retry.is_none());
    assert_eq!(endpoint.attempts(), (3, 0));
    assert_eq!(fixture.snapshot().await.connections, 0);
    fixture.finish().await;
    endpoint.finish(1).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn lost_response_after_remote_flush_recovers_by_one_lookup_without_resending_mutation() {
    let endpoint = Endpoint::new(Arc::new(Clock(AtomicU64::new(100))), Fault::Normal).await;
    let proxy = Proxy::new(&endpoint, Loss::AfterApply).await;
    let fixture = Fixture::new(proxy.port, proxy.root_certificate.clone(), 2000).await;
    let result = fixture
        .run(2, b"durably applied before response loss")
        .await;
    assert_eq!(
        result.receipt.disposition,
        Disposition::ProviderAcknowledged
    );
    assert!(result.retry.is_none());
    assert_eq!(endpoint.attempts(), (1, 1));
    assert_eq!(endpoint.counter(), 1);
    endpoint.assert_applied(
        2,
        b"durably applied before response loss",
        result.receipt.provider_receipt.as_deref().unwrap(),
        10_100,
    );
    fixture.finish().await;
    proxy.finish().await;
    endpoint.finish(1).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn absent_or_expired_remote_lookup_never_schedules_duplicate_execution() {
    for (loss, fault, expected, mutations) in [
        (
            Loss::BeforeForward,
            Fault::Normal,
            "remote-status-absent",
            0,
        ),
        (
            Loss::AfterApply,
            Fault::ExpireLookup,
            "remote-retention-expired",
            1,
        ),
    ] {
        let endpoint = Endpoint::new(Arc::new(Clock(AtomicU64::new(100))), fault).await;
        let proxy = Proxy::new(&endpoint, loss).await;
        let fixture = Fixture::new(proxy.port, proxy.root_certificate.clone(), 2000).await;
        let result = fixture.run(3, b"cannot infer execution from absence").await;
        assert_eq!(result.receipt.disposition, Disposition::Uncertain);
        assert_eq!(result.receipt.reason, expected);
        assert!(result.retry.is_none());
        assert!(result.receipt.provider_receipt.is_none());
        assert_eq!(endpoint.attempts().1, 1);
        fixture.finish().await;
        proxy.finish().await;
        endpoint.finish(mutations).await;
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_remote_horizon_and_expired_history_reject_late_equal_key_mutation() {
    let remote_clock = Arc::new(Clock(AtomicU64::new(100)));
    let endpoint = Endpoint::new(remote_clock.clone(), Fault::Normal).await;
    let fixture =
        Fixture::with_horizon(endpoint.port, endpoint.root_certificate.clone(), 2000, 500).await;
    let body = b"original cutoff remains fixed after history removal";
    let first = fixture.run(60, body).await;
    assert_eq!(first.receipt.disposition, Disposition::ProviderAcknowledged);
    endpoint.assert_applied(
        60,
        body,
        first.receipt.provider_receipt.as_deref().unwrap(),
        600,
    );
    remote_clock.0.store(600, Ordering::SeqCst);
    endpoint.forget_expired(60);
    // The intentionally lagging client clock models a delayed original packet.
    // Even with its durable history removed, the endpoint checks the packet's
    // original cutoff before reserving or mutating; no replacement cutoff exists.
    let late = fixture.run(60, body).await;
    assert_eq!(late.receipt.disposition, Disposition::Uncertain);
    assert_eq!(late.receipt.reason, "remote-retention-expired");
    assert!(late.retry.is_none());
    assert_eq!(endpoint.attempts(), (2, 1));
    assert_eq!(endpoint.counter(), 1);

    let (authority, payload, mut record) = fixture.retained(61, b"expires before first poll");
    let (context, attempt, operation) = fixture.accepted(&authority, payload, &mut record);
    record.begin_send(&attempt).unwrap();
    fixture.clock.0.store(600, Ordering::SeqCst);
    let expired = watched(operation).await;
    assert_eq!(expired.receipt.disposition, Disposition::PolicyBlocked);
    assert_eq!(expired.receipt.reason, "remote-retention-expired");
    assert!(expired.retry.is_none());
    context.retire().unwrap();
    assert_eq!(endpoint.attempts(), (2, 1));
    fixture.finish().await;
    endpoint.finish(1).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn reservation_retry_retains_original_identity_body_incarnation_and_horizon() {
    let endpoint = Endpoint::new(Arc::new(Clock(AtomicU64::new(100))), Fault::ReserveOnce).await;
    let fixture = Fixture::new(endpoint.port, endpoint.root_certificate.clone(), 2000).await;
    let (authority, payload, mut record) = fixture.retained(4, b"reserved immutable body");
    let (context, attempt, operation) = fixture.accepted(&authority, payload.clone(), &mut record);
    record.begin_send(&attempt).unwrap();
    let result = watched(operation).await;
    context.retire().unwrap();
    assert_eq!(result.receipt.disposition, Disposition::KnownFailed);
    assert_eq!(endpoint.counter(), 0);
    record.complete(&attempt, result.receipt.clone()).unwrap();
    let (proof, delay) = result.retry.unwrap();
    record
        .schedule_retry(proof, fixture.clock.observe(), delay)
        .unwrap();
    fixture.clock.0.store(110, Ordering::SeqCst);
    let (context, attempt, operation) = fixture.accepted(&authority, payload, &mut record);
    assert_eq!(attempt.attempt(), 2);
    assert_eq!(attempt.retry_horizon_millis(), Some(10_100));
    record.begin_send(&attempt).unwrap();
    let result = watched(operation).await;
    context.retire().unwrap();
    assert_eq!(
        result.receipt.disposition,
        Disposition::ProviderAcknowledged
    );
    assert_eq!(endpoint.attempts(), (2, 0));
    fixture.finish().await;
    endpoint.finish(1).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn malformed_oversized_redirect_and_unqualified_remote_replies_remain_bounded_and_private() {
    for (index, fault) in [
        Fault::Status(400),
        Fault::Status(401),
        Fault::Status(403),
        Fault::Status(409),
        Fault::Status(500),
        Fault::Status(503),
        Fault::Malformed,
        Fault::Oversized,
        Fault::Redirect,
        Fault::WrongIncarnation,
        Fault::UnknownField,
        Fault::Encoded,
    ]
    .into_iter()
    .enumerate()
    {
        let endpoint = Endpoint::new(Arc::new(Clock(AtomicU64::new(100))), fault).await;
        let fixture = Fixture::new(endpoint.port, endpoint.root_certificate.clone(), 2000).await;
        let result = fixture
            .run(index as u64 + 10, b"only closed receipts are retained")
            .await;
        let expected = if matches!(fault, Fault::Status(400 | 401 | 403 | 409)) {
            Disposition::KnownFailed
        } else {
            Disposition::Uncertain
        };
        assert_eq!(result.receipt.disposition, expected, "{fault:?}");
        assert!(result.retry.is_none());
        assert!(result.receipt.provider_receipt.is_none());
        assert!(!result.receipt.reason.contains("synthetic"));
        assert!(!result.receipt.reason.contains("Bearer"));
        assert_eq!(endpoint.attempts().0, 1);
        assert!(endpoint.attempts().1 <= 1);
        let mutations = u64::from(matches!(
            fault,
            Fault::WrongIncarnation | Fault::UnknownField | Fault::Encoded
        ));
        fixture.finish().await;
        endpoint.finish(mutations).await;
    }
}
