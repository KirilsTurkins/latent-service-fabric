//! Original global-capacity identity, independent of local physical I/O limits.
use std::sync::Mutex;

use latent_core::native_capacity::NativeCapacityOwner;

use super::{ProtectedStoreError, ProtectedStoreOwner};

#[derive(Default)]
struct State {
    owner: Option<NativeCapacityOwner>,
    sealed: bool,
}

#[derive(Default)]
pub(super) struct NativeBinding(Mutex<State>);

impl NativeBinding {
    pub(super) fn seal(&self) -> Result<(), ProtectedStoreError> {
        self.0
            .lock()
            .map_err(|_| ProtectedStoreError::InvalidConfiguration)?
            .sealed = true;
        Ok(())
    }
}

impl ProtectedStoreOwner {
    /// Install the node's original owner before the first published native job,
    /// view, provider role or operation pin is admitted. Clones alias this same
    /// binding; identical limits, paths and epochs cannot prove owner identity.
    /// This creates no reservation, replacement counter or worker. Actual work
    /// still retains its original `NativeReservation` through physical cleanup.
    pub fn bind_native_capacity(
        &self,
        owner: &NativeCapacityOwner,
    ) -> Result<(), ProtectedStoreError> {
        if self.snapshot()?.admission_closed {
            return Err(ProtectedStoreError::InvalidConfiguration);
        }
        let mut state = self
            .native_capacity
            .0
            .lock()
            .map_err(|_| ProtectedStoreError::InvalidConfiguration)?;
        if let Some(original) = &state.owner {
            return if original.is_same_owner(owner) {
                Ok(())
            } else {
                Err(ProtectedStoreError::InvalidConfiguration)
            };
        }
        if state.sealed {
            return Err(ProtectedStoreError::InvalidConfiguration);
        }
        state.owner = Some(owner.clone());
        Ok(())
    }

    /// Descriptive original identity only. A getter cannot refresh an existing
    /// permit, approve an unbound store or prove a pending write has retired.
    pub fn native_capacity(&self) -> Result<NativeCapacityOwner, ProtectedStoreError> {
        self.native_capacity
            .0
            .lock()
            .map_err(|_| ProtectedStoreError::InvalidConfiguration)?
            .owner
            .clone()
            .ok_or(ProtectedStoreError::InvalidConfiguration)
    }

    #[must_use]
    pub fn uses_native_capacity(&self, owner: &NativeCapacityOwner) -> bool {
        self.native_capacity()
            .is_ok_and(|original| original.is_same_owner(owner))
    }
}
