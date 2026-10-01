use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{mpsc, Arc};
use std::time::{Duration, Instant};

use latent_core::test_support::coordination::{
    with_watchdog, PauseTicket, PollProbe, Registration, Rendezvous, Stage, WATCHDOG,
};
use latent_core::test_support::{block_on, TestClock};
use latent_core::ActivationClock;

use super::*;

mod initialization;
mod ownership;
mod retirement;
mod shutdown;

struct Store {
    writes: Arc<AtomicUsize>,
    closed: Arc<AtomicBool>,
    close_notice: Option<mpsc::Sender<()>>,
}

impl Drop for Store {
    fn drop(&mut self) {
        self.closed.store(true, Ordering::SeqCst);
        if let Some(notice) = self.close_notice.take() {
            let _ = notice.send(());
        }
    }
}

fn limits() -> StoreIoLimits {
    StoreIoLimits {
        workers: 2,
        queued_jobs: 8,
        accepted_jobs: 16,
        active_reads: 2,
        active_writes: 1,
        retained_bytes: 50_000,
        job_bytes: 10_000,
        resident_bytes: 0,
    }
}

fn store() -> (Store, Arc<AtomicUsize>, Arc<AtomicBool>) {
    let writes = Arc::new(AtomicUsize::new(0));
    let closed = Arc::new(AtomicBool::new(false));
    (
        Store {
            writes: Arc::clone(&writes),
            closed: Arc::clone(&closed),
            close_notice: None,
        },
        writes,
        closed,
    )
}

fn clock() -> TestClock {
    TestClock::new(1_000, Instant::now(), 1)
}

fn finish<S: Send + Sync + 'static>(owner: &StoreIoOwner<S>) -> StoreIoShutdown {
    let deadline = Instant::now() + WATCHDOG;
    block_on(with_watchdog(
        WATCHDOG,
        owner.drain_async(deadline, std::future::pending()).unwrap(),
    ))
}

fn wait<T>(future: impl std::future::Future<Output = T>) -> T {
    block_on(with_watchdog(WATCHDOG, future))
}

fn pause<T>(
    rendezvous: &Rendezvous,
    notice: &mpsc::Sender<(Registration, PauseTicket)>,
    buffer: T,
) {
    let (registration, mut physical) = rendezvous.track(buffer).unwrap();
    physical.commit(Stage::Entered).unwrap();
    let mut parked = Box::pin(physical.pause());
    PollProbe::default().pending(parked.as_mut());
    let readiness = rendezvous.blocked(registration, Stage::Entered).unwrap();
    notice.send((registration, readiness)).unwrap();
    block_on(parked);
}

fn ready(receiver: &mpsc::Receiver<(Registration, PauseTicket)>) -> (Registration, PauseTicket) {
    receiver
        .recv_timeout(WATCHDOG)
        .expect("physical I/O did not reach its owned pause")
}
