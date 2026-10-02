//! The original sealed node role survives request and activation waiters.
use latent_commit::atomic::{AdmittedCommand, AtomicError, CommandTime, RetiredAttempt};
use latent_effects::{
    authority::EffectTime,
    runtime::{CommandAdmission, CommandAdmissionSource},
};
use std::sync::{Arc, Mutex};

pub(super) struct CommandRole {
    epoch: u64,
    captured: CommandTime,
    guard: Mutex<Option<CommandAdmission>>,
}
impl CommandRole {
    pub fn capture(source: &CommandAdmissionSource) -> Result<Arc<Self>, AtomicError> {
        let guard = source.capture().map_err(|_| AtomicError::Unavailable)?;
        let time = guard.captured_time();
        Ok(Arc::new(Self {
            epoch: guard.owner_epoch(),
            captured: command_time(time),
            guard: Mutex::new(Some(guard)),
        }))
    }
    pub const fn epoch(&self) -> u64 {
        self.epoch
    }
    pub const fn captured_time(&self) -> CommandTime {
        self.captured
    }
    pub fn with_current<T>(
        &self,
        action: impl FnOnce(EffectTime) -> Result<T, AtomicError>,
    ) -> Result<T, AtomicError> {
        let guard = self
            .guard
            .lock()
            .map_err(|_| AtomicError::RecoveryRequired)?;
        guard
            .as_ref()
            .ok_or(AtomicError::PermissionDenied)?
            .with_current(|epoch, time| {
                if epoch != self.epoch {
                    return Err(AtomicError::PermissionDenied);
                }
                action(time)
            })
            .map_err(|_| AtomicError::PermissionDenied)?
    }
    /// Called only by the physical completion owner after positive cleanup.
    pub fn retire(&self) -> Result<(), AtomicError> {
        if let Some(guard) = self
            .guard
            .lock()
            .map_err(|_| AtomicError::RecoveryRequired)?
            .take()
        {
            guard.retire();
        }
        Ok(())
    }
}

pub(super) fn command_time(time: EffectTime) -> CommandTime {
    CommandTime {
        unix_millis: time.unix_millis,
        continuity_proven: time.continuity_proven,
    }
}
pub(super) struct CommandClock(pub CommandAdmissionSource);
impl super::CommandTimeSource for CommandClock {
    fn sample(&self) -> CommandTime {
        self.0.command_time().map_or(
            CommandTime {
                unix_millis: 0,
                continuity_proven: false,
            },
            command_time,
        )
    }
}

/// Pending was flushed, but no guest host was installed. This owner retains
/// the original node role until the actual attempt proves non-acceptance.
pub struct PendingCommandAdmission {
    pub(super) claim: AdmittedCommand,
    pub(super) role: Arc<CommandRole>,
}
impl PendingCommandAdmission {
    #[must_use]
    pub fn record(&self) -> &latent_commit::atomic::CommandRecord {
        self.claim.record()
    }
    pub fn retire_without_guest(self) -> Result<RetiredAttempt, AtomicError> {
        let retirement = self.claim.retirement();
        drop(self.claim);
        let proof = retirement.proven_noncommit()?;
        self.role.retire()?;
        Ok(proof)
    }
}
