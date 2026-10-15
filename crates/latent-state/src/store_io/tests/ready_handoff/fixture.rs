use super::*;
use std::future::Future;
use std::panic::{catch_unwind, resume_unwind, AssertUnwindSafe};
use std::pin::Pin;
use std::sync::{Mutex, Weak};
use std::task::{Context, Poll, Wake, Waker};

struct Release(Option<mpsc::SyncSender<()>>);

impl Release {
    fn release(&mut self) {
        if let Some(sender) = self.0.take() {
            let _ = sender.try_send(());
        }
    }
}

impl Drop for Release {
    fn drop(&mut self) {
        self.release();
    }
}

struct BlockingWake {
    entered: mpsc::SyncSender<()>,
    release: Mutex<mpsc::Receiver<()>>,
    cutoff: Instant,
}

impl Wake for BlockingWake {
    fn wake(self: Arc<Self>) {
        self.entered.send(()).unwrap();
        self.release
            .lock()
            .unwrap()
            .recv_timeout(remaining(self.cutoff))
            .expect("original response wake cutoff");
    }
}

fn remaining(cutoff: Instant) -> Duration {
    cutoff.saturating_duration_since(Instant::now())
}

pub(super) fn kind_name(kind: StoreIoKind) -> &'static str {
    match kind {
        StoreIoKind::Read => "read",
        StoreIoKind::Write => "write",
        StoreIoKind::RecoveryRead => "recovery-read",
        StoreIoKind::RecoveryWrite => "recovery-write",
    }
}

pub(super) struct Observed {
    pub initially_pending: bool,
    pub unclaimed: StoreIoSnapshot,
    pub unclaimed_keeper: bool,
    pub unclaimed_result: bool,
    pub unclaimed_custody: Result<(), StoreIoError>,
    pub delivered: Option<Result<usize, StoreIoError>>,
    pub active: [usize; 4],
    pub accepted: usize,
    pub operation_bytes: u64,
    pub keeper_released: bool,
    pub result_released: bool,
    pub custody: Result<(), StoreIoError>,
}

pub(super) struct Report {
    pub observed: Observed,
    pub callbacks: usize,
    pub clean: bool,
    pub physically_retired: bool,
    pub store_destroyed: bool,
    pub threads_joined: usize,
}

struct Fixture {
    owner: StoreIoOwner<Store>,
    job: Pin<Box<StoreIoJob<Arc<Vec<u8>>>>>,
    callbacks: Arc<AtomicUsize>,
    closed: Arc<AtomicBool>,
    keeper: Weak<()>,
    result: Weak<Vec<u8>>,
    callback_entered: mpsc::Receiver<()>,
    wake_entered: mpsc::Receiver<()>,
    callback_release: Release,
    wake_release: Release,
    waker: Waker,
    cutoff: Instant,
}

impl Fixture {
    fn new(kind: StoreIoKind, panics: bool, cutoff: Instant) -> Self {
        let (store, callbacks, closed) = store();
        let mut config = limits();
        config.workers = 3;
        config.recovery = Some(StoreIoRecoveryLimits {
            workers: 1,
            queued_jobs: 4,
            accepted_jobs: 8,
            retained_bytes: 20_000,
            job_bytes: 10_000,
        });
        let owner = StoreIoOwner::new(store, config, |_| Ok(())).unwrap();
        let keeper = Arc::new(());
        let weak_keeper = Arc::downgrade(&keeper);
        let result = Arc::new(vec![7_u8; 128]);
        let weak_result = Arc::downgrade(&result);
        let (callback_started, callback_entered) = mpsc::sync_channel(1);
        let (callback_release, callback_resume) = mpsc::sync_channel(1);
        let job = owner
            .submit_retaining(kind, 128, keeper, move |store| {
                store.writes.fetch_add(1, Ordering::SeqCst);
                callback_started.send(()).unwrap();
                callback_resume
                    .recv_timeout(remaining(cutoff))
                    .expect("original callback release cutoff");
                assert!(!panics, "controlled callback panic");
                result
            })
            .unwrap();
        let (wake_started, wake_entered) = mpsc::sync_channel(1);
        let (wake_release, wake_resume) = mpsc::sync_channel(1);
        let waker = Waker::from(Arc::new(BlockingWake {
            entered: wake_started,
            release: Mutex::new(wake_resume),
            cutoff,
        }));
        Self {
            owner,
            job: Box::pin(job),
            callbacks,
            closed,
            keeper: weak_keeper,
            result: weak_result,
            callback_entered,
            wake_entered,
            callback_release: Release(Some(callback_release)),
            wake_release: Release(Some(wake_release)),
            waker,
            cutoff,
        }
    }

    fn observe(&mut self) -> Observed {
        self.callback_entered
            .recv_timeout(remaining(self.cutoff))
            .expect("original callback entry cutoff");
        let mut context = Context::from_waker(&self.waker);
        let initially_pending = self.job.as_mut().poll(&mut context).is_pending();
        self.callback_release.release();
        self.wake_entered
            .recv_timeout(remaining(self.cutoff))
            .expect("original response publication cutoff");
        let unclaimed = self.owner.snapshot().unwrap();
        let unclaimed_keeper = self.keeper.upgrade().is_some();
        let unclaimed_result = self.result.upgrade().is_some();
        let unclaimed_custody = self.custody();
        let delivered = match self.job.as_mut().poll(&mut context) {
            Poll::Ready(value) => Some(value.map(|bytes| bytes.len())),
            Poll::Pending => None,
        };
        let claimed = self.owner.snapshot().unwrap();
        Observed {
            initially_pending,
            unclaimed,
            unclaimed_keeper,
            unclaimed_result,
            unclaimed_custody,
            delivered,
            active: [
                claimed.active_reads,
                claimed.active_writes,
                claimed.active_recovery_reads,
                claimed.active_recovery_writes,
            ],
            accepted: claimed.accepted,
            operation_bytes: claimed.retained_operation_bytes,
            keeper_released: self.keeper.upgrade().is_none(),
            result_released: self.result.upgrade().is_none(),
            custody: self.custody(),
        }
    }

    fn custody(&self) -> Result<(), StoreIoError> {
        self.owner
            .reserve_custody::<()>(128, self.cutoff, Arc::new(()))
            .map(drop)
    }
}

pub(super) fn exercise(kind: StoreIoKind, panics: bool, cutoff: Instant) -> Report {
    let mut fixture = Fixture::new(kind, panics, cutoff);
    // Retire even a failed observation before resuming its original panic or
    // making any intended positive assertion about the original-source order.
    let observed = catch_unwind(AssertUnwindSafe(|| fixture.observe()));
    fixture.callback_release.release();
    fixture.wake_release.release();
    drop(fixture.job);
    let retired = block_on(with_watchdog(
        remaining(cutoff),
        fixture
            .owner
            .drain_async(cutoff, std::future::pending())
            .unwrap(),
    ));
    let threads_joined = reap(&fixture.owner, cutoff);
    let observed = observed.unwrap_or_else(|error| resume_unwind(error));
    Report {
        observed,
        callbacks: fixture.callbacks.load(Ordering::SeqCst),
        clean: retired.clean,
        physically_retired: retired.snapshot.physically_retired(),
        store_destroyed: fixture.closed.load(Ordering::SeqCst),
        threads_joined,
    }
}

fn reap(owner: &StoreIoOwner<Store>, cutoff: Instant) -> usize {
    let mut joined = 0;
    loop {
        joined += owner.reap_retired_threads().unwrap();
        if owner.pending_thread_joins().unwrap() == 0 {
            return joined;
        }
        assert!(
            Instant::now() < cutoff,
            "original native thread join cutoff"
        );
        std::thread::yield_now();
    }
}
