//! Bounded duplicate delivery notifications for already admitted commands.
//!
//! This table owns no execution, result, commit, native view or cancellation.
//! Every wake requires a fresh authorized durable lookup. Dropping any handle
//! cannot establish a durable disposition or retire physical command work.

mod state;
mod waiter;

use std::sync::{Arc, Mutex};

use latent_commit::atomic::{AdmittedCommand, AtomicError, CommandRecord, Outcome};

use state::{AttemptIdentity, Inner, State};
pub use waiter::{CommandNotification, CommandNotificationOwner, CommandNotificationWaiter};

const MAXIMUM_OWNERS: usize = 4096;
const MAXIMUM_WAITERS: usize = 8192;
const MAXIMUM_WAITERS_PER_ATTEMPT: usize = 128;
const MAXIMUM_RESIDENT_BYTES: u64 = 8 * 1024 * 1024;

#[derive(Debug, Clone, Copy)]
pub struct CommandWaiterConfig {
    pub maximum_owners: usize,
    pub maximum_waiters: usize,
    pub maximum_waiters_per_attempt: usize,
    /// All fixed table allocations must fit before construction allocates.
    pub maximum_resident_bytes: u64,
}

impl Default for CommandWaiterConfig {
    fn default() -> Self {
        Self {
            maximum_owners: 256,
            maximum_waiters: 1024,
            maximum_waiters_per_attempt: 32,
            maximum_resident_bytes: 1024 * 1024,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CommandWaiterError {
    InvalidConfiguration,
    Capacity,
    Exhausted,
    DuplicateOwner,
    Conflict,
    Unavailable,
    Authorization(AtomicError),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CommandWaiterSnapshot {
    pub owners: usize,
    pub waiters: usize,
    /// Fixed tables remain reserved until the last registry/handle retires.
    pub resident_bytes: u64,
}

/// Absence of a notification owner does not establish nonexecution or abort.
pub enum CommandWaiterDecision {
    Wait(CommandNotificationWaiter),
    ReloadDurableState,
    RecoveryRequired,
}

/// Preallocated node metadata. Accepted commands never grow its allocations.
#[derive(Clone)]
pub struct CommandWaiterRegistry {
    inner: Arc<Inner>,
}

impl CommandWaiterRegistry {
    pub fn new(config: CommandWaiterConfig) -> Result<Self, CommandWaiterError> {
        let state = State::new(config)?;
        Ok(Self {
            inner: Arc::new(Inner {
                state: Mutex::new(state),
            }),
        })
    }

    /// The caller moves the returned affine notification handle into its
    /// existing physical command driver, before scheduling the admitted claim.
    /// A decoded record cannot create an owner. This handle grants no execution.
    pub fn register(
        &self,
        claim: &AdmittedCommand,
    ) -> Result<CommandNotificationOwner, CommandWaiterError> {
        let record = claim.record();
        if record.outcome() != Outcome::Pending {
            return Err(CommandWaiterError::Conflict);
        }
        let mut state = self.inner.lock()?;
        let token = state.register(AttemptIdentity::from_record(record), record.fingerprint())?;
        Ok(CommandNotificationOwner::new(
            Arc::clone(&self.inner),
            token,
        ))
    }

    /// Supply the original record from a fresh atomic lookup. The trusted host
    /// rechecks current application/coalescing and result-read permissions,
    /// including its captured result-read policy, before any table observation.
    /// No permission, request/deadline or credential is cached in this table.
    pub fn attach(
        &self,
        record: &CommandRecord,
        authorize: impl FnOnce(&CommandRecord) -> Result<(), AtomicError>,
    ) -> Result<CommandWaiterDecision, CommandWaiterError> {
        authorize(record).map_err(CommandWaiterError::Authorization)?;
        if record.outcome() != Outcome::Pending {
            return Ok(CommandWaiterDecision::ReloadDurableState);
        }
        let mut state = self.inner.lock()?;
        let Some(token) =
            state.attach(AttemptIdentity::from_record(record), record.fingerprint())?
        else {
            // This includes the short publish/register gap and interrupted work.
            // Neither authorizes rescheduling or a deadline-based abort inference.
            return Ok(CommandWaiterDecision::RecoveryRequired);
        };
        Ok(CommandWaiterDecision::Wait(CommandNotificationWaiter::new(
            Arc::clone(&self.inner),
            token,
        )))
    }

    pub fn snapshot(&self) -> Result<CommandWaiterSnapshot, CommandWaiterError> {
        let state = self.inner.lock()?;
        Ok(CommandWaiterSnapshot {
            owners: state.owners.iter().flatten().count(),
            waiters: state.waiters.iter().flatten().count(),
            resident_bytes: state.resident_bytes,
        })
    }
}

#[cfg(test)]
mod tests;
