use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, TryLockError};

use latent_core::{PlatformError, PlatformErrorCode};
use tokio::sync::Notify;
use tonic::Status;

use super::signal::Signal;
use super::{failure, TransportConfig};

#[cfg(test)]
mod tests;

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct TransportSnapshot {
    pub accepting: bool,
    pub cancellation_requested: bool,
    pub force_close_requested: bool,
    pub active_connections: usize,
    pub active_rpcs: usize,
    pub active_control_jobs: usize,
    pub rejected_connections: u64,
    pub rejected_rpcs: u64,
    pub rejected_control_jobs: u64,
}

#[derive(Clone)]
pub struct TransportHandle {
    pub(super) shared: Arc<Shared>,
}

impl TransportHandle {
    pub fn start_accepting(&self) -> Result<(), PlatformError> {
        let mut counts = self
            .shared
            .counts
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if counts.phase != Phase::Starting {
            return Err(failure(
                PlatformErrorCode::StateConflict,
                "standalone acceptance is already settled",
            ));
        }
        counts.phase = Phase::Ready;
        Ok(())
    }
    pub fn stop_accepting(&self) {
        self.shared
            .counts
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .phase = Phase::Closing;
        self.shared.stop.trigger();
    }
    pub fn cancel_active(&self) {
        self.stop_accepting();
        self.shared.cancel.trigger();
    }
    pub fn force_close(&self) {
        self.cancel_active();
        self.shared.force.trigger();
    }
    #[must_use]
    pub fn snapshot(&self) -> TransportSnapshot {
        self.shared.snapshot()
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Phase {
    Starting,
    Ready,
    Closing,
}

struct Counts {
    phase: Phase,
    connections: usize,
    rpcs: usize,
    ordinary_rpcs: usize,
    control_jobs: usize,
}

pub(super) struct Shared {
    pub(super) config: TransportConfig,
    counts: Mutex<Counts>,
    pub(super) stop: Arc<Signal>,
    pub(super) cancel: Arc<Signal>,
    pub(super) force: Arc<Signal>,
    changed: Arc<Notify>,
    rejected_connections: AtomicU64,
    rejected_rpcs: AtomicU64,
    rejected_control_jobs: AtomicU64,
}

#[derive(Clone, Copy)]
pub(super) enum Kind {
    Connection,
    Rpc { inspection: bool },
    ControlJob,
}

impl Shared {
    pub(super) fn new(config: TransportConfig) -> Arc<Self> {
        Arc::new(Self {
            config,
            counts: Mutex::new(Counts {
                phase: Phase::Starting,
                connections: 0,
                rpcs: 0,
                ordinary_rpcs: 0,
                control_jobs: 0,
            }),
            stop: Arc::default(),
            cancel: Arc::default(),
            force: Arc::default(),
            changed: Arc::default(),
            rejected_connections: AtomicU64::new(0),
            rejected_rpcs: AtomicU64::new(0),
            rejected_control_jobs: AtomicU64::new(0),
        })
    }

    pub(super) fn acquire(self: &Arc<Self>, kind: Kind) -> Result<Guard, Status> {
        let mut counts = match self.counts.try_lock() {
            Ok(counts) => counts,
            Err(TryLockError::Poisoned(error)) => error.into_inner(),
            Err(TryLockError::WouldBlock) => {
                #[cfg(test)]
                tests::note_contention();
                // This mutex protects only phase and scalar counters. Brief
                // contention is not exhausted capacity; inspect the actual
                // limits after the current count operation has completed.
                self.counts
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
            }
        };
        let closed = match kind {
            Kind::Connection => counts.phase == Phase::Closing,
            _ => counts.phase != Phase::Ready,
        };
        if closed {
            self.reject(kind);
            return Err(Status::unavailable("standalone node is not accepting work"));
        }
        let full = match kind {
            Kind::Connection => counts.connections == self.config.maximum_connections,
            Kind::Rpc { inspection } => {
                counts.rpcs == self.config.maximum_rpcs
                    || (!inspection
                        && counts.ordinary_rpcs
                            == self.config.maximum_rpcs - self.config.reserved_cancel_status_rpcs)
            }
            Kind::ControlJob => counts.control_jobs == self.config.maximum_control_jobs,
        };
        if full {
            self.reject(kind);
            return Err(Status::resource_exhausted(
                "standalone dispatch capacity is exhausted",
            ));
        }
        match kind {
            Kind::Connection => counts.connections += 1,
            Kind::Rpc { inspection } => {
                counts.rpcs += 1;
                counts.ordinary_rpcs += usize::from(!inspection);
            }
            Kind::ControlJob => counts.control_jobs += 1,
        }
        Ok(Guard {
            shared: Arc::clone(self),
            kind,
        })
    }

    fn reject(&self, kind: Kind) {
        let counter = match kind {
            Kind::Connection => &self.rejected_connections,
            Kind::Rpc { .. } => &self.rejected_rpcs,
            Kind::ControlJob => &self.rejected_control_jobs,
        };
        let _ = counter.fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
            Some(value.saturating_add(1))
        });
    }

    pub(super) fn snapshot(&self) -> TransportSnapshot {
        let counts = self
            .counts
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        TransportSnapshot {
            accepting: counts.phase == Phase::Ready,
            cancellation_requested: self.cancel.is_set(),
            force_close_requested: self.force.is_set(),
            active_connections: counts.connections,
            active_rpcs: counts.rpcs,
            active_control_jobs: counts.control_jobs,
            rejected_connections: self.rejected_connections.load(Ordering::Relaxed),
            rejected_rpcs: self.rejected_rpcs.load(Ordering::Relaxed),
            rejected_control_jobs: self.rejected_control_jobs.load(Ordering::Relaxed),
        }
    }

    pub(super) async fn idle(&self) {
        loop {
            let changed = Arc::clone(&self.changed).notified_owned();
            let snapshot = self.snapshot();
            if snapshot.active_connections == 0
                && snapshot.active_rpcs == 0
                && snapshot.active_control_jobs == 0
            {
                return;
            }
            changed.await;
        }
    }
}

pub(super) struct Guard {
    shared: Arc<Shared>,
    kind: Kind,
}

impl Drop for Guard {
    fn drop(&mut self) {
        let mut counts = self
            .shared
            .counts
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        match self.kind {
            Kind::Connection => counts.connections -= 1,
            Kind::Rpc { inspection } => {
                counts.rpcs -= 1;
                counts.ordinary_rpcs -= usize::from(!inspection);
            }
            Kind::ControlJob => counts.control_jobs -= 1,
        }
        drop(counts);
        self.shared.changed.notify_waiters();
    }
}
