//! Cooperative bridge from accepted commands to the existing scheduler.
use std::sync::{Arc, Mutex};
use std::task::{Wake, Waker};
use std::time::{Duration, Instant};

use latent_core::{
    native_capacity::{NativeBufferClass, NativeBufferPermit},
    ActivationClock,
};
use latent_state::entity_lanes::{
    EntityCallKind, EntityDispatch, EntityLaneError, EntityLaneLimits, EntityLaneRequest,
    EntityLanes, EntityPhysicalOwner, EntityRejection, EntityScope,
};
use tokio::sync::{oneshot, watch};

pub(super) type Physical = Arc<PhysicalLease>;

// Keep the same prepaid charge through the last independently retained owner.
// The lane and its metadata are destroyed before the permit is refunded.
pub(super) struct PhysicalLease {
    _lane: EntityPhysicalOwner<Arc<Pending>>,
    _permit: NativeBufferPermit,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum QueueError {
    Lane(EntityLaneError),
    Rejected(EntityRejection),
    Expired,
    Unavailable,
}

struct Pending {
    current: Arc<dyn Fn() -> bool + Send + Sync>,
    result: Mutex<Option<oneshot::Sender<Result<Physical, QueueError>>>>,
    permit: Mutex<Option<NativeBufferPermit>>,
}

struct Signal(watch::Sender<u64>);
impl Wake for Signal {
    fn wake(self: Arc<Self>) {
        self.0
            .send_modify(|version| *version = version.wrapping_add(1));
    }
}

pub(super) struct EntityQueue {
    lanes: EntityLanes<Arc<Pending>>,
    signal: watch::Sender<u64>,
    claims: watch::Sender<u64>,
    waker: Waker,
    maximum_turn: usize,
    clock: Arc<dyn ActivationClock>,
}

impl EntityQueue {
    pub(super) fn observe(
        &self,
    ) -> Result<latent_state::entity_lanes::EntityLaneSnapshot, QueueError> {
        self.lanes.snapshot().map_err(QueueError::Lane)
    }

    #[cfg(test)]
    pub(super) fn snapshot(&self) -> latent_state::entity_lanes::EntityLaneSnapshot {
        self.lanes.snapshot().unwrap()
    }

    pub(super) fn new(
        limits: EntityLaneLimits,
        clock: Arc<dyn ActivationClock>,
    ) -> Result<Self, QueueError> {
        let maximum_turn = limits.global_queued;
        let lanes = EntityLanes::new(limits).map_err(QueueError::Lane)?;
        let (signal, _) = watch::channel(0);
        let (claims, _) = watch::channel(0);
        let waker = Waker::from(Arc::new(Signal(signal.clone())));
        Ok(Self {
            lanes,
            signal,
            claims,
            waker,
            maximum_turn,
            clock,
        })
    }

    pub(super) fn claim_changes(&self) -> watch::Receiver<u64> {
        self.claims.subscribe()
    }

    pub(super) fn claimed(&self) {
        self.claims
            .send_modify(|version| *version = version.wrapping_add(1));
    }

    pub(super) async fn acquire(
        &self,
        scope: EntityScope,
        identity: Vec<u8>,
        retained_bytes: u64,
        deadline: Instant,
        current: Arc<dyn Fn() -> bool + Send + Sync>,
        permit: NativeBufferPermit,
    ) -> Result<Physical, QueueError> {
        // Cover the queue's own objects and the lane's bounded copies before
        // building the channel or inserting the request. The trusted caller
        // obtains this permit from the original ingress reservation first.
        let scope_bytes = scope
            .tenant()
            .0
            .len()
            .checked_add(scope.namespace().0.len())
            .and_then(|n| n.checked_add(scope.entity().0.len()))
            .ok_or(QueueError::Unavailable)?;
        let charge = scope_bytes
            .checked_mul(6)
            .and_then(|n| {
                identity
                    .len()
                    .checked_mul(2)
                    .and_then(|ids| n.checked_add(ids))
            })
            .and_then(|n| n.checked_add(4096))
            .and_then(|n| u64::try_from(n).ok())
            .and_then(|n| n.checked_add(retained_bytes))
            .ok_or(QueueError::Unavailable)?;
        if permit.buffer_class() != NativeBufferClass::Request || permit.bytes() < charge {
            return Err(QueueError::Unavailable);
        }
        let (send, mut receive) = oneshot::channel();
        let pending = Arc::new(Pending {
            current,
            result: Mutex::new(Some(send)),
            permit: Mutex::new(Some(permit)),
        });
        let request = EntityLaneRequest::new(
            scope,
            identity,
            pending,
            retained_bytes,
            deadline,
            EntityCallKind::Root,
        );
        let _waiter = self
            .lanes
            .enqueue(request, self.clock.monotonic_now())
            .map_err(|error| QueueError::Lane(error.reason))?;
        let mut changes = self.signal.subscribe();
        loop {
            let now = self.clock.monotonic_now();
            self.drive(now)?;
            match receive.try_recv() {
                Ok(result) => return result,
                Err(oneshot::error::TryRecvError::Closed) => return Err(QueueError::Unavailable),
                Err(oneshot::error::TryRecvError::Empty) => {}
            }
            if now >= deadline {
                return Err(QueueError::Expired);
            }
            let observed = self
                .lanes
                .register_dispatch_waker(now, &self.waker)
                .map_err(QueueError::Lane)?;
            if observed.ready {
                continue;
            }
            let until = observed.next_deadline.unwrap_or(deadline).min(deadline);
            tokio::select! {
                result = &mut receive => return result.map_err(|_| QueueError::Unavailable)?,
                notification = changes.changed() => if notification.is_err() { return Err(QueueError::Unavailable); },
                () = wait_until(until, self.clock.as_ref()) => {},
            }
        }
    }

    fn drive(&self, now: Instant) -> Result<(), QueueError> {
        for _ in 0..self.maximum_turn {
            let Some(next) = self
                .lanes
                .try_start_next(now, |_, pending| (pending.current)())
                .map_err(QueueError::Lane)?
            else {
                return Ok(());
            };
            let (pending, outcome) = match next {
                EntityDispatch::Ready(execution) => {
                    let (request, owner) = execution.into_owned_work();
                    let pending = request.into_payload();
                    let permit = pending
                        .permit
                        .lock()
                        .map_err(|_| QueueError::Unavailable)?
                        .take()
                        .ok_or(QueueError::Unavailable)?;
                    let lease = Arc::new(PhysicalLease {
                        _lane: owner,
                        _permit: permit,
                    });
                    (pending, Ok(lease))
                }
                EntityDispatch::Rejected(rejected) => (
                    rejected.request.into_payload(),
                    Err(QueueError::Rejected(rejected.reason)),
                ),
            };
            let sender = pending
                .result
                .lock()
                .map_err(|_| QueueError::Unavailable)?
                .take();
            if let Some(sender) = sender {
                let _ = sender.send(outcome);
            }
        }
        self.signal
            .send_modify(|version| *version = version.wrapping_add(1));
        Ok(())
    }
}

async fn wait_until(deadline: Instant, clock: &dyn ActivationClock) {
    loop {
        let remaining = deadline.saturating_duration_since(clock.monotonic_now());
        if remaining.is_zero() {
            return;
        }
        if clock.uses_system_monotonic() {
            tokio::time::sleep_until(deadline.into()).await;
        } else {
            tokio::time::sleep(remaining.min(Duration::from_millis(5))).await;
        }
    }
}

#[cfg(test)]
mod tests;
