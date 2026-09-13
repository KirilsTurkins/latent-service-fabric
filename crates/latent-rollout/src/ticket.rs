use crate::{cancelled, deadline, model::no_attempt, OwnedResponse, Result, RolloutFailure};
use latent_artifacts::{ReleaseAuditAck, ReleaseAuditStatus};
use std::{
    sync::{
        atomic::{AtomicBool, AtomicU64, AtomicU8, Ordering},
        Arc,
    },
    time::Instant,
};
use tokio::sync::oneshot;

pub(crate) type Completion<T> = std::result::Result<OwnedResponse<T>, RolloutFailure>;

pub(crate) struct Control {
    cancelled: AtomicBool,
    done: AtomicBool,
    sequence: AtomicU64,
    status: AtomicU8,
    wake: tokio::sync::Notify,
}
impl Control {
    pub(crate) fn new() -> Arc<Self> {
        Arc::new(Self {
            cancelled: AtomicBool::new(false),
            done: AtomicBool::new(false),
            sequence: AtomicU64::new(0),
            status: AtomicU8::new(0),
            wake: tokio::sync::Notify::new(),
        })
    }
    pub(crate) fn check(&self, expires: Instant) -> Result<()> {
        if Instant::now() >= expires {
            Err(deadline())
        } else if self.cancelled.load(Ordering::Acquire) {
            Err(cancelled())
        } else {
            Ok(())
        }
    }
    pub(crate) fn set_ack(&self, ack: ReleaseAuditAck) {
        self.sequence
            .store(ack.attempt_sequence.unwrap_or(0), Ordering::Release);
        self.status.store(
            match ack.status {
                ReleaseAuditStatus::Durable => 1,
                ReleaseAuditStatus::OutcomeUnknown => 2,
                ReleaseAuditStatus::Disabled | ReleaseAuditStatus::AuditUnavailable => 0,
            },
            Ordering::Release,
        );
    }
    pub(crate) fn ack(&self) -> ReleaseAuditAck {
        let status = match self.status.load(Ordering::Acquire) {
            1 => ReleaseAuditStatus::Durable,
            2 => ReleaseAuditStatus::OutcomeUnknown,
            _ => return no_attempt(),
        };
        let sequence = self.sequence.load(Ordering::Acquire);
        ReleaseAuditAck {
            status,
            attempt_sequence: (sequence != 0).then_some(sequence),
        }
    }
    pub(crate) fn done(&self) {
        self.done.store(true, Ordering::Release);
    }
    pub(crate) async fn cancelled(&self) {
        loop {
            let notified = self.wake.notified();
            if self.cancelled.load(Ordering::Acquire) {
                return;
            }
            notified.await;
        }
    }
}

#[derive(Clone)]
pub struct RolloutControl(Arc<Control>);
impl RolloutControl {
    /// Cancellation stops uncommitted work at a safe control checkpoint. It
    /// never withdraws an already-started catalog commit or refunds its owner.
    #[must_use]
    pub fn cancel(&self) -> bool {
        let changed =
            !self.0.done.load(Ordering::Acquire) && !self.0.cancelled.swap(true, Ordering::AcqRel);
        if changed {
            self.0.wake.notify_one();
        }
        changed
    }
}

pub struct RolloutTicket<T> {
    receiver: oneshot::Receiver<Completion<T>>,
    control: RolloutControl,
    expires: Instant,
}
impl<T> RolloutTicket<T> {
    pub(crate) fn new(
        receiver: oneshot::Receiver<Completion<T>>,
        control: Arc<Control>,
        expires: Instant,
    ) -> Self {
        Self {
            receiver,
            control: RolloutControl(control),
            expires,
        }
    }
    #[must_use]
    pub fn control(&self) -> RolloutControl {
        self.control.clone()
    }

    pub async fn wait(mut self) -> Completion<T> {
        if Instant::now() >= self.expires {
            return Err(RolloutFailure::new(deadline(), self.control.0.ack()));
        }
        let result = tokio::time::timeout_at(self.expires.into(), &mut self.receiver).await;
        // Tokio timeout may poll an already-ready inner reply before its timer.
        if Instant::now() >= self.expires {
            drop(result);
            return Err(RolloutFailure::new(deadline(), self.control.0.ack()));
        }
        match result {
            Ok(Ok(value)) => value,
            Ok(Err(_)) => Err(RolloutFailure::new(crate::closed(), self.control.0.ack())),
            Err(_) => Err(RolloutFailure::new(deadline(), self.control.0.ack())),
        }
    }
}
impl<T> Drop for RolloutTicket<T> {
    fn drop(&mut self) {
        let _ = self.control.cancel();
    }
}
