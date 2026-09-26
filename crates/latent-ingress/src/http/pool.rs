use super::{Collector, HttpError, RawHead, EXCHANGE_RESERVATION_BYTES};
use latent_core::IncomingDeadline;
use std::{
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Arc,
    },
    time::Instant,
};
use tokio::sync::Notify;

struct PoolState {
    maximum: usize,
    active: AtomicUsize,
}

/// One shared node pool. Construction allocates no request buffers or workers.
#[derive(Clone)]
pub struct HttpPool {
    state: Arc<PoolState>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PoolSnapshot {
    pub maximum_exchanges: usize,
    pub active_exchanges: usize,
    pub reserved_bytes: usize,
}

impl HttpPool {
    pub fn new(maximum_exchanges: usize, maximum_bytes: usize) -> Result<Self, HttpError> {
        let maximum = maximum_exchanges.min(maximum_bytes / EXCHANGE_RESERVATION_BYTES);
        if maximum == 0 || maximum_bytes > isize::MAX as usize {
            return Err(HttpError::InvalidLimits);
        }
        Ok(Self {
            state: Arc::new(PoolState {
                maximum,
                active: AtomicUsize::new(0),
            }),
        })
    }
    pub fn begin(
        &self,
        head: RawHead<'_>,
        deadline: IncomingDeadline,
    ) -> Result<Collector, HttpError> {
        self.state
            .active
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |active| {
                (active < self.state.maximum).then_some(active + 1)
            })
            .map_err(|_| HttpError::Overloaded)?;
        let lease = Arc::new(Lease {
            pool: self.state.clone(),
            deadline,
            disconnected: AtomicBool::new(false),
            changed: Notify::new(),
        });
        lease.check()?;
        Collector::new(head, lease)
    }
    #[must_use]
    pub fn snapshot(&self) -> PoolSnapshot {
        let active = self.state.active.load(Ordering::Acquire);
        PoolSnapshot {
            maximum_exchanges: self.state.maximum,
            active_exchanges: active,
            reserved_bytes: active * EXCHANGE_RESERVATION_BYTES,
        }
    }
}

pub(super) struct Lease {
    pool: Arc<PoolState>,
    pub deadline: IncomingDeadline,
    disconnected: AtomicBool,
    changed: Notify,
}
impl Lease {
    pub fn check(&self) -> Result<(), HttpError> {
        if self.disconnected.load(Ordering::Acquire) {
            return Err(HttpError::Disconnected);
        }
        if Instant::now() >= self.deadline.monotonic() {
            return Err(HttpError::DeadlineExceeded);
        }
        Ok(())
    }
}
impl Drop for Lease {
    fn drop(&mut self) {
        self.pool.active.fetch_sub(1, Ordering::AcqRel);
    }
}

/// Transport-owned disconnect signal and deadline wait. Signalling never refunds
/// a live buffer or activation. Drop all owners only after actual cleanup.
#[derive(Clone)]
pub struct Cancellation(pub(super) Arc<Lease>);
impl Cancellation {
    pub fn disconnect(&self) {
        self.0.disconnected.store(true, Ordering::Release);
        self.0.changed.notify_waiters();
    }
    pub fn check(&self) -> Result<(), HttpError> {
        self.0.check()
    }
    #[must_use]
    pub fn deadline(&self) -> IncomingDeadline {
        self.0.deadline
    }
    pub async fn cancelled(&self) -> HttpError {
        loop {
            let changed = self.0.changed.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            if let Err(error) = self.check() {
                return error;
            }
            tokio::select! {
                () = changed => {},
                () = tokio::time::sleep_until(self.0.deadline.monotonic().into()) => {},
            }
        }
    }
}
