use super::*;
use std::{cell::RefCell, sync::mpsc};

struct ExitGate {
    entered: mpsc::Sender<()>,
    release: mpsc::Receiver<()>,
}

impl Drop for ExitGate {
    fn drop(&mut self) {
        let _ = self.entered.send(());
        let _ = self.release.recv_timeout(WATCHDOG);
    }
}

thread_local! {
    static EXIT_GATE: RefCell<Option<ExitGate>> = const { RefCell::new(None) };
}

#[tokio::test]
async fn shutdown_waits_for_the_actual_os_exit_after_logical_store_retirement() {
    let fixture = Fixture::new();
    let (state, mut effects) = fixture.open().await;
    let (entered, observed) = mpsc::channel();
    let (release, wait) = mpsc::channel();
    state
        .0
        .store
        .with_store(StoreIoKind::Read, 1024, move |_| {
            EXIT_GATE.with(|slot| {
                *slot.borrow_mut() = Some(ExitGate {
                    entered,
                    release: wait,
                });
            });
            Ok(())
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    state.close_ordinary();
    effects.close();
    let deadline = Instant::now() + WATCHDOG;
    let effect = effects.shutdown(deadline).await.unwrap();
    assert!(effect.clean && effect.physically_retired);
    let mut shutdown = Box::pin(state.shutdown(deadline));
    let exit_started = async {
        loop {
            match observed.try_recv() {
                Ok(()) => break,
                Err(mpsc::TryRecvError::Empty) => tokio::task::yield_now().await,
                Err(mpsc::TryRecvError::Disconnected) => panic!("owned exit gate disappeared"),
            }
        }
    };
    tokio::select! {
        result = &mut shutdown => panic!("shutdown returned before the actual OS exit: {result:?}"),
        result = tokio::time::timeout_at(deadline.into(), exit_started) => result.unwrap(),
    }
    assert!(state.0.store.snapshot().unwrap().physically_retired());
    assert!(state.0.store.pending_thread_joins().unwrap() > 0);
    release.send(()).unwrap();
    let report = shutdown.await.unwrap();
    assert!(report.clean && !report.store_quarantined && !report.native_quarantined);
    assert_eq!(report.store_threads_joined, 4);
    assert_eq!(state.0.store.pending_thread_joins().unwrap(), 0);
}
