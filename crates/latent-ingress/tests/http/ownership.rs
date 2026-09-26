use crate::http_support::*;
use latent_core::IncomingDeadline;
use latent_ingress::http::*;
use std::time::{Duration, Instant};

#[test]
fn cancellation_retains_every_actual_owner_until_cleanup_and_allows_later_reuse() {
    let pool = pool();
    let mut collector = pool
        .begin(
            head(
                "POST",
                &[
                    HOST,
                    HeaderView {
                        name: "content-length",
                        value: b"3",
                    },
                ],
            ),
            deadline(),
        )
        .unwrap();
    collector.append(b"abc").unwrap();
    let cancellation = collector.cancellation();
    cancellation.disconnect();
    assert_eq!(collector.append(b"d"), Err(HttpError::Disconnected));
    assert_eq!(pool.snapshot().reserved_bytes, EXCHANGE_RESERVATION_BYTES);
    assert_eq!(
        pool.begin(head("GET", &[HOST]), deadline()).err(),
        Some(HttpError::Overloaded)
    );
    drop(collector);
    assert_eq!(pool.snapshot().active_exchanges, 1);
    drop(cancellation);
    assert_eq!(pool.snapshot().active_exchanges, 0);
    drop(invocation(&pool, "GET"));
    assert_eq!(pool.snapshot().reserved_bytes, 0);
}

#[test]
fn completed_application_is_not_a_completed_delivery_and_disconnect_keeps_charge() {
    let pool = pool();
    let mut response = deliver(&pool, "POST", RESPONSE.as_bytes());
    response.mark_headers_written().unwrap();
    response.advance(1).unwrap();
    let cancellation = response.cancellation();
    cancellation.disconnect();
    assert_eq!(response.remaining_body(), Err(HttpError::Disconnected));
    assert_eq!(pool.snapshot().active_exchanges, 1);
    drop(cancellation);
    assert_eq!(response.finish(), Err(HttpError::Disconnected));
    assert_eq!(pool.snapshot().reserved_bytes, 0);
    let response = deliver(&pool, "POST", RESPONSE.as_bytes());
    assert_eq!(response.finish(), Err(HttpError::IncompleteDelivery));
    assert_eq!(pool.snapshot().active_exchanges, 0);
}

#[test]
fn pool_intersects_slot_and_byte_caps_and_rejects_without_an_unbounded_queue() {
    assert!(HttpPool::new(0, EXCHANGE_RESERVATION_BYTES).is_err());
    assert!(HttpPool::new(1, EXCHANGE_RESERVATION_BYTES - 1).is_err());
    let pool = HttpPool::new(4, EXCHANGE_RESERVATION_BYTES).unwrap();
    assert_eq!(pool.snapshot().maximum_exchanges, 1);
    let held = invocation(&pool, "GET");
    std::thread::scope(|scope| {
        for _ in 0..8 {
            scope.spawn(|| {
                assert_eq!(
                    pool.begin(head("GET", &[HOST]), deadline()).err(),
                    Some(HttpError::Overloaded)
                );
            });
        }
    });
    assert_eq!(pool.snapshot().active_exchanges, 1);
    drop(held);
    assert_eq!(pool.snapshot().reserved_bytes, 0);
}

#[tokio::test]
async fn disconnect_and_absolute_deadline_wake_waiters_without_early_refunds() {
    let pool = pool();
    let collector = pool.begin(head("GET", &[HOST]), deadline()).unwrap();
    let cancel = collector.cancellation();
    let observer = cancel.clone();
    let wait = tokio::spawn(async move { observer.cancelled().await });
    cancel.disconnect();
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(2), wait)
            .await
            .unwrap()
            .unwrap(),
        HttpError::Disconnected
    );
    assert_eq!(pool.snapshot().active_exchanges, 1);
    drop(cancel);
    drop(collector);
    let collector = pool
        .begin(
            head("GET", &[HOST]),
            IncomingDeadline::new(Instant::now() + Duration::from_millis(30), 1),
        )
        .unwrap();
    let cancel = collector.cancellation();
    assert_eq!(
        tokio::time::timeout(Duration::from_secs(2), cancel.cancelled())
            .await
            .unwrap(),
        HttpError::DeadlineExceeded
    );
    assert_eq!(pool.snapshot().active_exchanges, 1);
    assert_eq!(
        collector.finish(context()).err(),
        Some(HttpError::DeadlineExceeded)
    );
    drop(cancel);
    assert_eq!(pool.snapshot().active_exchanges, 0);
}
