//! Cooperative bridge from accepted commands to the existing scheduler.
use std::collections::BTreeMap;
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc, Mutex,
};
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
    DuplicateNeedsAuthorization { source: [u8; 32], owner: u64 },
    DuplicateCapacity,
    OriginalOwnerEnded,
}

type CommandIdentity = latent_commit::atomic::Identity;
type Commands = Arc<Mutex<BTreeMap<CommandIdentity, Arc<CommandEntry>>>>;
type DuplicateWaiters = Arc<Mutex<BTreeMap<EntityScope, usize>>>;

struct CommandEntry {
    fingerprint: CommandIdentity,
    source: [u8; 32],
    generation: u64,
    owner: Option<Arc<super::SharedCommandOwner>>,
}

struct DuplicateWaiter {
    waiters: DuplicateWaiters,
    scope: EntityScope,
    _sponsor: Option<super::shared_owner::SharedCommandWaiter>,
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
    entry: Arc<CommandEntry>,
    signal: watch::Sender<u64>,
}
impl Drop for CommandRegistration {
    fn drop(&mut self) {
        if let Ok(mut commands) = self.commands.lock() {
            if commands
                .get(&self.identity)
                .is_some_and(|entry| Arc::ptr_eq(entry, &self.entry))
            {
                commands.remove(&self.identity);
            }
        }
        self.signal
            .send_modify(|version| *version = version.wrapping_add(1));
    }
}

struct Pending {
    current: Arc<dyn Fn() -> bool + Send + Sync>,
    deadline: Instant,
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
    next_command_generation: AtomicU64,
    duplicate_waiters: DuplicateWaiters,
    maximum_global_waiters: usize,
    maximum_tenant_waiters: usize,
    maximum_entity_waiters: usize,
    maximum_wait_age: Duration,
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
        let maximum_tenant_waiters = limits.tenant_queued;
        let maximum_entity_waiters = limits.entity_queued;
        let maximum_wait_age = limits.maximum_wait_age;
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
            next_command_generation: AtomicU64::new(1),
            duplicate_waiters: Arc::new(Mutex::new(BTreeMap::new())),
            maximum_global_waiters: maximum_turn,
            maximum_tenant_waiters,
            maximum_entity_waiters,
            maximum_wait_age,
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
            None,
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
        command: Option<(
            CommandIdentity,
            CommandIdentity,
            [u8; 32],
            Option<Arc<super::SharedCommandOwner>>,
        )>,
        duplicate_authorized: bool,
        mut first_owner: Option<(u64, [u8; 32])>,
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
        let duplicate_deadline = self
            .clock
            .monotonic_now()
            .checked_add(self.maximum_wait_age)
            .ok_or(QueueError::Unavailable)?
            .min(deadline);
        let mut changes = self.signal.subscribe();
        let mut duplicate_waiter = None;
        let registration = loop {
            if duplicate_waiter.is_some() {
                if self.clock.monotonic_now() >= duplicate_deadline {
                    return Err(QueueError::Expired);
                }
                // Recheck the original ingress authority whenever the shared
                // owner changes, before recovering an existing command.
                if !(current)() {
                    return Err(QueueError::Rejected(EntityRejection::AuthorityChanged));
                }
                if self.clock.monotonic_now() >= duplicate_deadline {
                    return Err(QueueError::Expired);
                }
            }
            let Some((identity, fingerprint, source, owner)) = &command else {
                break None;
            };
            let (next, sponsor) = {
                let mut commands = self.commands.lock().map_err(|_| QueueError::Unavailable)?;
                if let Some(existing) = commands.get(identity) {
                    if !duplicate_authorized {
                        return Err(QueueError::DuplicateNeedsAuthorization {
                            source: existing.source,
                            owner: existing.generation,
                        });
                    }
                    if first_owner
                        .is_some_and(|first| first != (existing.generation, existing.source))
                    {
                        return Err(QueueError::OriginalOwnerEnded);
                    }
                    if existing.fingerprint != *fingerprint {
                        return Err(QueueError::DuplicateConflict);
                    }
                    first_owner = Some((existing.generation, existing.source));
                    (None, existing.owner.clone())
                } else {
                    if first_owner.is_some() {
                        return Err(QueueError::OriginalOwnerEnded);
                    }
                    if commands.len() >= self.maximum_commands {
                        return Err(QueueError::Unavailable);
                    }
                    let generation = self
                        .next_command_generation
                        .fetch_update(Ordering::AcqRel, Ordering::Acquire, |value| {
                            value.checked_add(1)
                        })
                        .map_err(|_| QueueError::Unavailable)?;
                    let entry = Arc::new(CommandEntry {
                        fingerprint: *fingerprint,
                        source: *source,
                        generation,
                        owner: owner.clone(),
                    });
                    commands.insert(*identity, Arc::clone(&entry));
                    (
                        Some(Arc::new(CommandRegistration {
                            commands: Arc::clone(&self.commands),
                            identity: *identity,
                            entry,
                            signal: self.signal.clone(),
                        })),
                        None,
                    )
                }
            };
            if let Some(next) = next {
                drop(duplicate_waiter.take());
                break Some(next);
            }
            if duplicate_waiter.is_none() {
                let mut waiters = self
                    .duplicate_waiters
                    .lock()
                    .map_err(|_| QueueError::Unavailable)?;
                let mut global = 0_usize;
                let mut tenant = 0_usize;
                for (key, count) in waiters.iter() {
                    global = global.saturating_add(*count);
                    if key.tenant() == scope.tenant() {
                        tenant = tenant.saturating_add(*count);
                    }
                }
                if global >= self.maximum_global_waiters
                    || tenant >= self.maximum_tenant_waiters
                    || waiters.get(&scope).copied().unwrap_or(0) >= self.maximum_entity_waiters
                {
                    return Err(QueueError::DuplicateCapacity);
                }
                let sponsor = match sponsor {
                    Some(owner) => Some(
                        owner
                            .try_subscribe()
                            .ok_or(QueueError::OriginalOwnerEnded)?,
                    ),
                    None => None,
                };
                *waiters.entry(scope.clone()).or_default() += 1;
                duplicate_waiter = Some(DuplicateWaiter {
                    waiters: Arc::clone(&self.duplicate_waiters),
                    scope: scope.clone(),
                    _sponsor: sponsor,
                });
            }
            tokio::select! {
                result = changes.changed() => if result.is_err() { return Err(QueueError::Unavailable); },
                () = wait_until(duplicate_deadline, self.clock.as_ref()) => return Err(QueueError::Expired),
            }
        };
        let (send, mut receive) = oneshot::channel();
        let pending = Arc::new(Pending {
            current,
            deadline,
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
                    let now = self.clock.monotonic_now();
                    let cancelled = execution.cancellation_requested(now);
                    let (request, owner) = execution.into_owned_work();
                    let pending = request.into_payload();
                    if cancelled {
                        let failure = if now >= pending.deadline {
                            QueueError::Expired
                        } else {
                            QueueError::Rejected(EntityRejection::CancelledBeforeExecution)
                        };
                        drop(owner);
                        (pending, Err(failure))
                    } else {
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
