//! Actual original rule and rejection generations for installation bookkeeping.
use super::{check_time, rejection, AuthorityError, EffectAuthorityOwner, EffectTime, Owner};
use latent_core::{
    authority_rejection::AuthorityRejectionGeneration,
    native_capacity::{
        NativeBufferClass, NativeBufferPermit, NativeCapacityOwner, NativeReservation,
    },
};
use std::sync::Arc;

/// Affine metadata capture, containing no permission, provider context, secret
/// value or copied rule map. Its finite original caller charge and the real
/// resident effect owner survive until this capture is physically destroyed.
pub struct EffectControlGeneration {
    owner: Arc<Owner>,
    generation: u64,
    rejections: AuthorityRejectionGeneration,
    original: Arc<NativeReservation>,
    _memory: NativeBufferPermit,
}

impl EffectControlGeneration {
    pub const METADATA_BYTES: u64 = 2048;

    /// Descriptive counters from their real owners; neither confers approval.
    #[must_use]
    pub const fn rules_generation(&self) -> u64 {
        self.generation
    }
    #[must_use]
    pub fn rejection_generation(&self) -> u64 {
        self.rejections.generation()
    }
}

impl EffectAuthorityOwner {
    pub fn capture_control_generation(
        &self,
        native: &NativeCapacityOwner,
        original: Arc<NativeReservation>,
        time: EffectTime,
    ) -> Result<EffectControlGeneration, AuthorityError> {
        if !self.uses_native_capacity(native) || !original.is_from_owner(native) {
            return Err(AuthorityError::Invalid);
        }
        let memory = original
            .reserve_buffer(
                NativeBufferClass::Work,
                EffectControlGeneration::METADATA_BYTES,
            )
            .map_err(|_| AuthorityError::Capacity)?;
        let mut state = self
            .0
            .state
            .try_lock()
            .map_err(|_| AuthorityError::Unavailable)?;
        check_time(&mut state, time)?;
        if state
            .rules
            .values()
            .any(|rule| rule.enabled && !rule.rejection.is_current())
        {
            return Err(AuthorityError::PolicyBlocked);
        }
        let rejections = self
            .0
            .rejections
            .capture_control_generation()
            .map_err(|error| rejection::error(error.code))?;
        original
            .with_live(|| ())
            .map_err(|_| AuthorityError::Expired)?;
        Ok(EffectControlGeneration {
            owner: Arc::clone(&self.0),
            generation: state.generation,
            rejections,
            original,
            _memory: memory,
        })
    }

    /// The actual Policy -> Catalog -> Namespace -> Effects metadata fences
    /// must already be held by the trusted installation adapter. This final
    /// callback runs under the same rule/rejection and original Native fence;
    /// it must be short, with no I/O, await, effect mutation or Native reentry.
    /// This generation check does not authorize any state/effect operation.
    pub fn with_control_generation<R>(
        &self,
        captured: &EffectControlGeneration,
        time: EffectTime,
        action: impl FnOnce() -> R,
    ) -> Result<R, AuthorityError> {
        if !Arc::ptr_eq(&self.0, &captured.owner) {
            return Err(AuthorityError::Stale);
        }
        let mut state = self
            .0
            .state
            .try_lock()
            .map_err(|_| AuthorityError::Unavailable)?;
        check_time(&mut state, time)?;
        if state.generation != captured.generation {
            return Err(AuthorityError::Stale);
        }
        if state
            .rules
            .values()
            .any(|rule| rule.enabled && !rule.rejection.is_current())
        {
            return Err(AuthorityError::PolicyBlocked);
        }
        self.0
            .rejections
            .with_control_generation(&captured.rejections, || {
                captured
                    .original
                    .with_live(action)
                    .map_err(|_| AuthorityError::Expired)
            })
            .map_err(|error| rejection::error(error.code))?
    }
}
