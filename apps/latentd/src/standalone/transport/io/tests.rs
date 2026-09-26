use super::*;
use std::time::Duration;

#[test]
fn first_authentication_and_expiry_are_terminal_competing_transitions() {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_time()
        .build()
        .unwrap();
    runtime.block_on(async {
        tokio::time::pause();
        let now = tokio::time::Instant::now();
        let connection = || ConnectionInfo {
            address: "127.0.0.1:1".parse().unwrap(),
            expires_at: now + Duration::from_secs(1),
            drain_at: now + Duration::from_secs(2),
            close_at: now + Duration::from_secs(3),
            phase: Arc::new(AtomicU8::new(UNAUTHENTICATED)),
        };
        let accepted = connection();
        let rejected = connection();
        let closed = connection();
        closed.phase.store(CLOSED, Ordering::Release);
        assert!(!closed.mark_authenticated());
        assert!(closed.is_draining());
        assert!(accepted.mark_authenticated());
        tokio::time::advance(Duration::from_secs(1)).await;
        assert!(!rejected.mark_authenticated());
        assert!(accepted.mark_authenticated());
        assert!(!accepted.is_draining());
        // An expiry racing an already accepted authentication cannot win.
        assert_eq!(
            accepted.phase.compare_exchange(
                UNAUTHENTICATED,
                CLOSED,
                Ordering::AcqRel,
                Ordering::Acquire
            ),
            Err(AUTHENTICATED)
        );
        tokio::time::advance(Duration::from_secs(1)).await;
        assert!(accepted.is_draining());
        accepted.phase.store(CLOSED, Ordering::Release);
        assert!(!accepted.mark_authenticated());
    });
}
