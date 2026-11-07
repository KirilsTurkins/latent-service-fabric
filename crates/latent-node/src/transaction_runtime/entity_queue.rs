//! Cooperative bridge from accepted commands to the existing scheduler.
use std::collections::BTreeMap;
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
    _command: Option<Arc<CommandRegistration>>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum QueueError {
    Lane(EntityLaneError),
    Rejected(EntityRejection),
    Expired,
    Unavailable,
    DuplicateConflict,
    DuplicateNeedsAuthorization,
    DuplicateCapacity,
}

type CommandIdentity = latent_commit::atomic::Identity;
type Commands = Arc<Mutex<BTreeMap<CommandIdentity, CommandIdentity>>>;
type DuplicateWaiters = Arc<Mutex<BTreeMap<EntityScope, usize>>>;

struct DuplicateWaiter {
    waiters: DuplicateWaiters,
    scope: EntityScope,
}
impl Drop for DuplicateWaiter {
    fn drop(&mut self) {
        if let Ok(mut waiters) = self.waiters.lock() {
            if let Some(count) = waiters.get_mut(&self.scope) {
                *count -= 1;
                if *count == 0 {
                    waiters.remove(&self.scope);
                }
            }
        }
    }
}

struct CommandRegistration {
    commands: Commands,
    identity: CommandIdentity,
    signal: watch::Sender<u64>,
}
impl Drop for CommandRegistration {
    fn drop(&mut self) {
        if let Ok(mut commands) = self.commands.lock() {
            commands.remove(&self.identity);
        }
        self.signal
            .send_modify(|version| *version = version.wrapping_add(1));
    }
}

struct Pending {
    current: Arc<dyn Fn() -> bool + Send + Sync>,
    result: Mutex<Option<oneshot::Sender<Result<Physical, QueueError>>>>,
    permit: Mutex<Option<NativeBufferPermit>>,
    command: Option<Arc<CommandRegistration>>,
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
    commands: Commands,
    maximum_commands: usize,
    duplicate_waiters: DuplicateWaiters,
    maximum_entity_waiters: usize,
}

impl EntityQueue {
    pub(super) fn duplicate_waiter_count(&self) -> Result<usize, QueueError> {
        let waiters = self
            .duplicate_waiters
            .lock()
            .map_err(|_| QueueError::Unavailable)?;
        Ok(waiters.values().copied().sum())
    }
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
        let maximum_entity_waiters = limits.entity_queued;
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
            commands: Arc::new(Mutex::new(BTreeMap::new())),
            maximum_commands: maximum_turn.saturating_mul(2),
            duplicate_waiters: Arc::new(Mutex::new(BTreeMap::new())),
            maximum_entity_waiters,
        })
    }

    pub(super) fn claim_changes(&self) -> watch::Receiver<u64> {
        self.claims.subscribe()
    }

    pub(super) fn claimed(&self) {
        self.claims
            .send_modify(|version| *version = version.wrapping_add(1));
    }

    #[cfg(test)]
    pub(super) async fn acquire(
        &self,
        scope: EntityScope,
        identity: Vec<u8>,
        retained_bytes: u64,
        deadline: Instant,
        current: Arc<dyn Fn() -> bool + Send + Sync>,
        permit: NativeBufferPermit,
    ) -> Result<Physical, QueueError> {
        self.acquire_for_command(
            scope,
            identity,
            retained_bytes,
            deadline,
            current,
            permit,
            None,
            false,
        )
        .await
    }

    #[expect(
        clippy::too_many_arguments,
        clippy::too_many_lines,
        reason = "Keep the original prepaid owner, duplicate registration, and cooperative dispatch together"
    )]
    pub(super) async fn acquire_for_command(
        &self,
        scope: EntityScope,
        identity: Vec<u8>,
        retained_bytes: u64,
        deadline: Instant,
        current: Arc<dyn Fn() -> bool + Send + Sync>,
        permit: NativeBufferPermit,
        command: Option<(CommandIdentity, CommandIdentity)>,
        duplicate_authorized: bool,
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
            .ok_or(QueueError::Unavailable)?;
        // `retained_bytes` is separately held by the permit's original global
        // reservation; the subpermit covers these additional lane objects.
        if permit.buffer_class() != NativeBufferClass::Request || permit.bytes() < charge {
            return Err(QueueError::Unavailable);
        }
        let mut changes = self.signal.subscribe();
        let registration = loop {
            let Some((identity, fingerprint)) = &command else {
                break None;
            };
            let next = {
                let mut commands = self.commands.lock().map_err(|_| QueueError::Unavailable)?;
                if let Some(existing) = commands.get(identity) {
                    if !duplicate_authorized {
                        return Err(QueueError::DuplicateNeedsAuthorization);
                    }
                    if existing != fingerprint {
                        return Err(QueueError::DuplicateConflict);
                    }
                    None
                } else {
                    if commands.len() >= self.maximum_commands {
                        return Err(QueueError::Unavailable);
                    }
                    commands.insert(*identity, *fingerprint);
                    Some(Arc::new(CommandRegistration {
                        commands: Arc::clone(&self.commands),
                        identity: *identity,
                        signal: self.signal.clone(),
                    }))
                }
            };
            if let Some(next) = next {
                break Some(next);
            }
            let waiter = {
                let mut waiters = self
                    .duplicate_waiters
                    .lock()
                    .map_err(|_| QueueError::Unavailable)?;
                let count = waiters.entry(scope.clone()).or_default();
                if *count >= self.maximum_entity_waiters {
                    return Err(QueueError::DuplicateCapacity);
                }
                *count += 1;
                DuplicateWaiter {
                    waiters: Arc::clone(&self.duplicate_waiters),
                    scope: scope.clone(),
                }
            };
            tokio::select! {
                result = changes.changed() => if result.is_err() { return Err(QueueError::Unavailable); },
                () = wait_until(deadline, self.clock.as_ref()) => return Err(QueueError::Expired),
            }
            drop(waiter);
        };
        let (send, mut receive) = oneshot::channel();
        let pending = Arc::new(Pending {
            current,
            result: Mutex::new(Some(send)),
            permit: Mutex::new(Some(permit)),
            command: registration,
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
                        _command: pending.command.clone(),
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
