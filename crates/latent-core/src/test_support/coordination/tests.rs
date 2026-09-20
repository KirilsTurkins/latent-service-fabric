use super::*;
use std::time::Duration;

#[derive(Debug)]
struct Buffer {
    bytes: Option<Vec<u8>>,
    charged: Arc<AtomicUsize>,
}

impl Buffer {
    fn new(charged: &Arc<AtomicUsize>) -> Self {
        charged.fetch_add(16, Ordering::SeqCst);
        Self {
            bytes: Some(vec![0; 16]),
            charged: Arc::clone(charged),
        }
    }
}

impl Drop for Buffer {
    fn drop(&mut self) {
        assert_eq!(
            self.charged.load(Ordering::SeqCst),
            16,
            "premature buffer refund"
        );
        drop(self.bytes.take());
        self.charged.fetch_sub(16, Ordering::SeqCst);
    }
}

#[test]
fn missing_readiness_premature_retirement_and_illegal_transitions_fail() {
    let rendezvous = Rendezvous::new(1);
    let (id, mut owner) = rendezvous.track(()).unwrap();
    assert_eq!(
        rendezvous.blocked(id, Stage::Requested),
        Err(CoordinationError::MissingReadiness)
    );
    assert_eq!(
        rendezvous.require_retired(id),
        Err(CoordinationError::WrongStage)
    );
    assert_eq!(
        owner.commit(Stage::Retired),
        Err(CoordinationError::InvalidTransition)
    );
    let unpolled = owner.pause();
    assert!(!rendezvous.snapshot(id).unwrap().blocked);
    drop(unpolled);
    drop(owner);
    rendezvous.require_retired(id).unwrap();
}

#[test]
fn historical_arrival_abandoned_pause_and_recycled_registration_are_rejected() {
    let rendezvous = Rendezvous::new(1);
    let (id, mut owner) = rendezvous.track(()).unwrap();
    owner.commit(Stage::Queued).unwrap();
    let probe = PollProbe::default();
    let mut first = Box::pin(owner.pause());
    probe.pending(first.as_mut());
    let stale_pause = rendezvous.blocked(id, Stage::Queued).unwrap();
    drop(first);
    assert_eq!(
        rendezvous.blocked(id, Stage::Queued),
        Err(CoordinationError::MissingReadiness)
    );
    let mut second = Box::pin(owner.pause());
    probe.pending(second.as_mut());
    assert_eq!(
        rendezvous.release(stale_pause),
        Err(CoordinationError::StaleRegistration)
    );
    let ticket = rendezvous.blocked(id, Stage::Queued).unwrap();
    rendezvous.release(ticket).unwrap();
    assert_eq!(
        rendezvous.blocked(id, Stage::Queued),
        Err(CoordinationError::MissingReadiness)
    );
    probe.ready(second.as_mut());
    drop(second);
    owner.commit(Stage::CancellationObserved).unwrap();
    assert_eq!(
        rendezvous.require_retired(id),
        Err(CoordinationError::WrongStage)
    );
    drop(owner);
    rendezvous.require_retired(id).unwrap();
    let (_, next) = rendezvous.track(()).unwrap();
    assert_eq!(
        rendezvous.snapshot(id),
        Err(CoordinationError::StaleRegistration)
    );
    drop(next);
    assert_eq!(rendezvous.live_owners(), 0);
}

#[test]
fn bounded_capacity_and_owner_unwind_do_not_leak() {
    let rendezvous = Rendezvous::new(1);
    let charged = Arc::new(AtomicUsize::new(0));
    let (id, owner) = rendezvous.track(Buffer::new(&charged)).unwrap();
    assert!(matches!(
        rendezvous.track(()),
        Err(CoordinationError::Capacity)
    ));
    let panic = std::panic::catch_unwind(move || {
        let _owner = owner;
        panic!("injected task panic");
    });
    assert!(panic.is_err());
    assert_eq!(charged.load(Ordering::SeqCst), 0);
    rendezvous.require_retired(id).unwrap();
    assert_eq!(rendezvous.live_owners(), 0);
}

async fn cancellation_script() {
    with_watchdog(WATCHDOG, async {
        for panic_after_release in [false, true] {
            let rendezvous = Rendezvous::new(1);
            let charged = Arc::new(AtomicUsize::new(0));
            let (id, mut owner) = rendezvous.track(Buffer::new(&charged)).unwrap();
            owner.commit(Stage::Entered).unwrap();
            let mut future = Box::pin(async move {
                owner.pause().await;
                assert!(!panic_after_release, "injected worker panic");
                drop(owner);
            });
            PollProbe::default().pending(future.as_mut());
            let ticket = rendezvous.blocked(id, Stage::Entered).unwrap();
            let task = tokio::spawn(future);
            assert_eq!(charged.load(Ordering::SeqCst), 16);
            assert_eq!(
                rendezvous.require_retired(id),
                Err(CoordinationError::WrongStage)
            );
            if panic_after_release {
                rendezvous.release(ticket).unwrap();
            } else {
                task.abort();
            }
            let error = task.await.unwrap_err();
            assert_eq!(error.is_panic(), panic_after_release);
            assert_eq!(error.is_cancelled(), !panic_after_release);
            assert_eq!(charged.load(Ordering::SeqCst), 0);
            rendezvous.require_retired(id).unwrap();
            assert_eq!(rendezvous.live_owners(), 0);
        }
    })
    .await;
}

#[tokio::test(flavor = "current_thread")]
async fn cancellation_and_panic_current_thread() {
    cancellation_script().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cancellation_and_panic_multi_thread() {
    cancellation_script().await;
}

#[tokio::test(start_paused = true)]
async fn watchdog_expires_even_with_paused_tokio_time() {
    let result = tokio::spawn(with_watchdog(
        Duration::from_millis(1),
        std::future::pending::<()>(),
    ))
    .await;
    assert!(result.unwrap_err().is_panic());
}
