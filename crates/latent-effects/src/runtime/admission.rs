//! Command admission derives from the actual protected node role and clock.
use std::sync::Arc;

use crate::authority::{AuthorityError, EffectAuthorityOwner, EffectTime};

use super::worker::Services;
use super::{DispatcherControlGeneration, DispatcherError, DispatcherOwner};

/// Non-clone metadata owner. The command's physical cleanup owner must retain
/// this guard through actual guest/native retirement, including waiter loss.
/// It retains the protected node role; it does not itself authorize a caller.
pub struct CommandAdmission {
    services: Arc<Services>,
    generation: DispatcherControlGeneration,
    captured: EffectTime,
    retired: bool,
}

/// Sealed metadata source for a finite node admission registry. Cloning this
/// handle clones neither workers nor driver ownership, and cannot reopen a role.
#[derive(Clone)]
pub struct CommandAdmissionSource {
    services: Arc<Services>,
}

impl CommandAdmissionSource {
    /// Diagnostic original-clock projection. This reserves no command slot and
    /// must not be called recursively inside a held command acceptance fence.
    pub fn command_time(&self) -> Result<EffectTime, DispatcherError> {
        self.current_source().map(|source| source.1)
    }

    /// The exact installed effect registry, not a reconstructed authority owner.
    #[must_use]
    pub fn effect_authority(&self) -> EffectAuthorityOwner {
        self.services.authority.clone()
    }

    #[must_use]
    pub fn uses_effect_authority(&self, authority: &EffectAuthorityOwner) -> bool {
        self.services.authority.same_owner(authority)
    }

    #[must_use]
    pub fn uses_store(&self, store: &latent_state::protected_store::ProtectedStoreOwner) -> bool {
        self.services.store.is_same_owner(store)
    }

    fn current_source(&self) -> Result<(u64, EffectTime), DispatcherError> {
        let mut state = self
            .services
            .shared
            .state
            .lock()
            .map_err(|_| DispatcherError::AdmissionClosed)?;
        check(&self.services, &state)?;
        let time = observe(&self.services, &mut state)?;
        Ok((self.services.epoch.generation(), time))
    }

    pub fn capture(&self) -> Result<CommandAdmission, DispatcherError> {
        let mut state = self
            .services
            .shared
            .state
            .lock()
            .map_err(|_| DispatcherError::AdmissionClosed)?;
        check(&self.services, &state)?;
        if state.command_owners >= self.services.shared.maximum_command_owners {
            return Err(AuthorityError::Capacity.into());
        }
        let captured = observe(&self.services, &mut state)?;
        state.command_owners += 1;
        Ok(CommandAdmission {
            services: Arc::clone(&self.services),
            generation: state.control_generation,
            captured,
            retired: false,
        })
    }
}

impl DispatcherOwner {
    #[must_use]
    pub fn command_admission_source(&self) -> CommandAdmissionSource {
        CommandAdmissionSource {
            services: Arc::clone(&self.services),
        }
    }
    pub fn command_admission(&self) -> Result<CommandAdmission, DispatcherError> {
        self.command_admission_source().capture()
    }

    /// Diagnostic projection. Actual writer acceptance uses `CommandAdmission`.
    pub fn command_owner_epoch(&self) -> Result<u64, DispatcherError> {
        self.command_admission_source()
            .current_source()
            .map(|source| source.0)
    }

    /// The original node clock; wall time alone never establishes continuity.
    pub fn command_time(&self) -> Result<EffectTime, DispatcherError> {
        self.command_admission_source().command_time()
    }
}

impl CommandAdmission {
    #[must_use]
    pub const fn owner_epoch(&self) -> u64 {
        self.generation.owner_epoch()
    }

    #[must_use]
    pub const fn captured_time(&self) -> EffectTime {
        self.captured
    }

    /// The original physical command owner invokes this only after affirmative
    /// guest/native cleanup. Logical cancellation or waiter drop is insufficient.
    /// Retirement remains permitted after close, quarantine or control changes.
    pub fn retire(mut self) {
        let mut state = self
            .services
            .shared
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state.command_owners -= 1;
        self.retired = true;
        drop(state);
        self.services.shared.notify.notify_one();
    }

    /// Short no-I/O outer fence for native writer acceptance. Invoke namespace,
    /// policy/effect and cancellation acceptance inside this callback, then
    /// release it before physical flush. It may not perform I/O or await.
    pub fn with_current<T>(
        &self,
        accept: impl FnOnce(u64, EffectTime) -> T,
    ) -> Result<T, DispatcherError> {
        let mut state = self
            .services
            .shared
            .state
            .lock()
            .map_err(|_| DispatcherError::AdmissionClosed)?;
        check(&self.services, &state)?;
        if state.control_generation != self.generation {
            return Err(DispatcherError::AdmissionClosed);
        }
        let time = observe(&self.services, &mut state)?;
        Ok(accept(self.owner_epoch(), time))
    }
}

impl Drop for CommandAdmission {
    fn drop(&mut self) {
        let mut state = self
            .services
            .shared
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if self.retired {
            return;
        }
        state.closed = true;
        state.paused = true;
        state
            .failure
            .get_or_insert(latent_state::store_io::StoreIoError::RecoveryRequired.into());
        // The original cleanup proof was lost. Preserve the bounded role guard
        // and protected-root pin rather than refunding command ownership.
        drop(state);
        self.services.store.quarantine();
        self.services.shared.notify.notify_one();
    }
}

fn check(services: &Services, state: &super::state::State) -> Result<(), DispatcherError> {
    if state.closed
        || state.scheduling_retired
        || state.pending_control.is_some()
        || state.restore_review.is_required()
        || state.control_generation.owner_epoch() != services.epoch.generation()
    {
        return Err(DispatcherError::AdmissionClosed);
    }
    if let Some(error) = state.failure {
        return Err(error);
    }
    if let Some(error) = services.store.failure() {
        return Err(error.into());
    }
    let store = services.store.snapshot()?;
    if store.admission_closed || store.quarantined {
        return Err(DispatcherError::AdmissionClosed);
    }
    Ok(())
}

fn observe(
    services: &Services,
    state: &mut super::state::State,
) -> Result<EffectTime, DispatcherError> {
    let time = services.time.observe();
    if !time.continuity_proven || time.unix_millis < state.command_clock_floor {
        return Err(AuthorityError::ClockDiscontinuity.into());
    }
    state.command_clock_floor = time.unix_millis;
    Ok(time)
}
