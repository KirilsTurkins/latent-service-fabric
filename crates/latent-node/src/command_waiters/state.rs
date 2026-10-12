use std::mem::size_of;
use std::sync::{Mutex, MutexGuard};
use std::task::Waker;

use latent_commit::atomic::{CommandRecord, Identity};

use super::{
    CommandWaiterConfig, CommandWaiterError, MAXIMUM_OWNERS, MAXIMUM_RESIDENT_BYTES,
    MAXIMUM_WAITERS, MAXIMUM_WAITERS_PER_ATTEMPT,
};

#[derive(Clone, Copy, PartialEq, Eq)]
pub(super) struct AttemptIdentity {
    command: Identity,
    attempt: Identity,
    transaction: Identity,
}
impl AttemptIdentity {
    pub(super) fn from_record(record: &CommandRecord) -> Self {
        Self {
            command: record.id(),
            attempt: record.attempt_id(),
            transaction: record.transaction_id(),
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub(super) struct Token {
    pub index: usize,
    pub generation: u64,
}

pub(super) struct OwnerSlot {
    identity: AttemptIdentity,
    fingerprint: Identity,
    generation: u64,
}
pub(super) struct WaiterSlot {
    pub generation: u64,
    pub owner: Token,
    pub notified: bool,
    pub waker: Option<Waker>,
}

pub(super) struct Inner {
    pub state: Mutex<State>,
}
impl Inner {
    pub fn lock(&self) -> Result<MutexGuard<'_, State>, CommandWaiterError> {
        self.state
            .lock()
            .map_err(|_| CommandWaiterError::Unavailable)
    }
}

pub(super) struct State {
    pub owners: Vec<Option<OwnerSlot>>,
    pub waiters: Vec<Option<WaiterSlot>>,
    pub resident_bytes: u64,
    pub next_generation: u64,
    maximum_waiters_per_attempt: usize,
}

impl State {
    pub fn new(config: CommandWaiterConfig) -> Result<Self, CommandWaiterError> {
        if config.maximum_owners == 0
            || config.maximum_owners > MAXIMUM_OWNERS
            || config.maximum_waiters == 0
            || config.maximum_waiters > MAXIMUM_WAITERS
            || config.maximum_waiters_per_attempt == 0
            || config.maximum_waiters_per_attempt > MAXIMUM_WAITERS_PER_ATTEMPT
            || config.maximum_waiters_per_attempt > config.maximum_waiters
            || config.maximum_resident_bytes == 0
            || config.maximum_resident_bytes > MAXIMUM_RESIDENT_BYTES
        {
            return Err(CommandWaiterError::InvalidConfiguration);
        }
        let resident_bytes = size_of::<Option<OwnerSlot>>()
            .checked_mul(config.maximum_owners)
            .and_then(|bytes| {
                size_of::<Option<WaiterSlot>>()
                    .checked_mul(config.maximum_waiters)
                    .and_then(|waiters| bytes.checked_add(waiters))
            })
            .and_then(|bytes| bytes.checked_add(size_of::<Inner>() + 128))
            .and_then(|bytes| u64::try_from(bytes).ok())
            .ok_or(CommandWaiterError::InvalidConfiguration)?;
        if resident_bytes > config.maximum_resident_bytes {
            return Err(CommandWaiterError::Capacity);
        }
        let mut owners = Vec::new();
        owners
            .try_reserve_exact(config.maximum_owners)
            .map_err(|_| CommandWaiterError::Capacity)?;
        owners.resize_with(config.maximum_owners, || None);
        let mut waiters = Vec::new();
        waiters
            .try_reserve_exact(config.maximum_waiters)
            .map_err(|_| CommandWaiterError::Capacity)?;
        waiters.resize_with(config.maximum_waiters, || None);
        Ok(Self {
            owners,
            waiters,
            resident_bytes,
            next_generation: 1,
            maximum_waiters_per_attempt: config.maximum_waiters_per_attempt,
        })
    }

    fn next_token(&mut self, index: usize) -> Result<Token, CommandWaiterError> {
        let generation = self.next_generation;
        self.next_generation = generation
            .checked_add(1)
            .filter(|_| generation != 0)
            .ok_or(CommandWaiterError::Exhausted)?;
        Ok(Token { index, generation })
    }

    pub fn register(
        &mut self,
        identity: AttemptIdentity,
        fingerprint: Identity,
    ) -> Result<Token, CommandWaiterError> {
        if self
            .owners
            .iter()
            .flatten()
            .any(|owner| owner.identity == identity)
        {
            return Err(CommandWaiterError::DuplicateOwner);
        }
        let index = self
            .owners
            .iter()
            .position(Option::is_none)
            .ok_or(CommandWaiterError::Capacity)?;
        let token = self.next_token(index)?;
        self.owners[index] = Some(OwnerSlot {
            identity,
            fingerprint,
            generation: token.generation,
        });
        Ok(token)
    }

    pub fn attach(
        &mut self,
        identity: AttemptIdentity,
        fingerprint: Identity,
    ) -> Result<Option<Token>, CommandWaiterError> {
        let Some(index) = self
            .owners
            .iter()
            .position(|owner| owner.as_ref().is_some_and(|o| o.identity == identity))
        else {
            return Ok(None);
        };
        let owner = self.owners[index].as_ref().expect("matching occupied slot");
        if owner.fingerprint != fingerprint {
            return Err(CommandWaiterError::Conflict);
        }
        let owner = Token {
            index,
            generation: owner.generation,
        };
        if self
            .waiters
            .iter()
            .flatten()
            .filter(|waiter| waiter.owner == owner)
            .count()
            >= self.maximum_waiters_per_attempt
        {
            return Err(CommandWaiterError::Capacity);
        }
        let index = self
            .waiters
            .iter()
            .position(Option::is_none)
            .ok_or(CommandWaiterError::Capacity)?;
        let token = self.next_token(index)?;
        self.waiters[index] = Some(WaiterSlot {
            generation: token.generation,
            owner,
            notified: false,
            waker: None,
        });
        Ok(Some(token))
    }

    /// Take bounded wakers under the lock and wake outside it. Finished delivery
    /// slots remain reserved until the actual waiter returns or is dropped.
    pub fn finish(&mut self, owner: Token) -> [Option<Waker>; MAXIMUM_WAITERS_PER_ATTEMPT] {
        let mut wakers = std::array::from_fn(|_| None);
        if self
            .owners
            .get(owner.index)
            .and_then(Option::as_ref)
            .is_none_or(|slot| slot.generation != owner.generation)
        {
            return wakers;
        }
        self.owners[owner.index] = None;
        for (index, waiter) in self
            .waiters
            .iter_mut()
            .flatten()
            .filter(|w| w.owner == owner)
            .enumerate()
        {
            waiter.notified = true;
            wakers[index] = waiter.waker.take();
        }
        wakers
    }

    pub fn detach(&mut self, token: Token) -> Option<Waker> {
        if self
            .waiters
            .get(token.index)
            .and_then(Option::as_ref)
            .is_some_and(|slot| slot.generation == token.generation)
        {
            return self.waiters[token.index].take().and_then(|slot| slot.waker);
        }
        None
    }
}
