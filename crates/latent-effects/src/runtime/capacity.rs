//! Ordinary dispatch uses the composition root's exact shared native owner.
use std::sync::Arc;
use std::time::{Duration, Instant};

use latent_core::native_capacity::{
    NativeAdmissionClass, NativeBufferClass, NativeBufferPermit, NativeCapacityError,
    NativeReservation, NativeReservationRequest,
};

use crate::authority::AuthorityError;

use super::store::Candidate;
use super::worker::Services;
use super::{DispatcherConfig, DispatcherError};

pub(super) const PREPARATION_BYTES: u64 = 8 * 1024 * 1024;
pub(super) const RECEIPT_BYTES: u64 = 2 * 1024 * 1024;
pub(super) const ATTEMPT_NATIVE_BYTES: u64 =
    DispatcherConfig::ATTEMPT_BYTES + PREPARATION_BYTES + RECEIPT_BYTES;

/// One original reservation and prepaid buffer allowance. Every physical owner
/// retains this same keeper; no provider, native callback or receipt mints a new
/// counter or refreshes its deadline. Actual values drop before the final keeper.
pub(super) struct AttemptCapacity {
    reservation: NativeReservation,
    _buffers: NativeBufferPermit,
}

impl AttemptCapacity {
    pub fn reserve(
        services: &Services,
        candidate: &Candidate,
    ) -> Result<Arc<Self>, DispatcherError> {
        let deadline = Instant::now()
            .checked_add(Duration::from_millis(
                candidate.authority.ceiling().attempt_timeout_millis,
            ))
            .ok_or(DispatcherError::InvalidConfiguration)?;
        let state = services
            .shared
            .state
            .lock()
            .map_err(|_| DispatcherError::AdmissionClosed)?;
        super::admission::check(services, &state)?;
        if state.paused {
            return Err(DispatcherError::AdmissionClosed);
        }
        let mut binding = services
            .native_capacity
            .lock()
            .map_err(|_| DispatcherError::AdmissionClosed)?;
        let installed = binding
            .owner
            .as_ref()
            .ok_or(DispatcherError::AdmissionClosed)?;
        if !services.store.uses_native_capacity(installed) {
            return Err(DispatcherError::InvalidConfiguration);
        }
        let reservation = installed
            .reserve(
                NativeAdmissionClass::Ordinary,
                NativeReservationRequest {
                    request_bytes: 0,
                    work_bytes: ATTEMPT_NATIVE_BYTES,
                    response_bytes: 0,
                },
                deadline,
            )
            .map_err(error)?;
        let buffers = reservation
            .reserve_buffer(NativeBufferClass::Work, ATTEMPT_NATIVE_BYTES)
            .map_err(error)?;
        binding.admissions_started = true;
        Ok(Arc::new(Self {
            reservation,
            _buffers: buffers,
        }))
    }

    pub fn deadline(&self) -> Instant {
        self.reservation.original_deadline()
    }

    pub fn check(&self) -> Result<(), AuthorityError> {
        self.reservation.with_live(|| ()).map_err(authority_error)
    }

    /// Effects -> Native for synchronous provider admission; no I/O or await.
    pub fn accept_provider<T>(&self, action: impl FnOnce() -> T) -> Result<T, AuthorityError> {
        self.reservation.with_live(action).map_err(authority_error)
    }
}

pub(super) fn transient(error: DispatcherError) -> bool {
    matches!(
        error,
        DispatcherError::AdmissionClosed
            | DispatcherError::Authority(AuthorityError::Capacity | AuthorityError::Expired)
    )
}

fn error(error: NativeCapacityError) -> DispatcherError {
    match error {
        NativeCapacityError::SlotsFull | NativeCapacityError::BytesFull => {
            AuthorityError::Capacity.into()
        }
        NativeCapacityError::DeadlineExceeded => AuthorityError::Expired.into(),
        NativeCapacityError::AdmissionClosed | NativeCapacityError::Quarantined => {
            DispatcherError::AdmissionClosed
        }
        _ => DispatcherError::InvalidConfiguration,
    }
}

fn authority_error(error: NativeCapacityError) -> AuthorityError {
    match error {
        NativeCapacityError::DeadlineExceeded => AuthorityError::Expired,
        NativeCapacityError::AdmissionClosed | NativeCapacityError::Quarantined => {
            AuthorityError::PolicyBlocked
        }
        _ => AuthorityError::Unavailable,
    }
}
