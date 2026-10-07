use super::{capacity, error, expired, Arc, Instant, PlatformError, PlatformErrorCode};
use super::{StateManagementAdmission, StateManagementReservation};
use latent_core::native_capacity::{
    NativeAdmissionClass, NativeCapacityError, NativeCapacityOwner, NativeReservation,
    NativeReservationRequest,
};

/// Uses the installed node's shared native owner. Construction creates no pool,
/// worker or quota; all clones of `owner` retain the same physical counters.
pub struct StateManagementRecoveryAdmission {
    owner: NativeCapacityOwner,
}
impl StateManagementRecoveryAdmission {
    #[must_use]
    pub const fn new(owner: NativeCapacityOwner) -> Self {
        Self { owner }
    }
}
struct Reservation {
    native: NativeReservation,
    response_bytes: usize,
}
impl StateManagementAdmission for StateManagementRecoveryAdmission {
    fn native_capacity(&self) -> NativeCapacityOwner {
        self.owner.clone()
    }
    fn reserve_recovery(
        &self,
        request_bytes: usize,
        work_bytes: usize,
        response_bytes: usize,
        deadline: Instant,
    ) -> Result<Arc<dyn StateManagementReservation>, PlatformError> {
        let request = NativeReservationRequest {
            request_bytes: u64::try_from(request_bytes).map_err(|_| capacity())?,
            work_bytes: u64::try_from(work_bytes).map_err(|_| capacity())?,
            response_bytes: u64::try_from(response_bytes).map_err(|_| capacity())?,
        };
        let native = self
            .owner
            .reserve(NativeAdmissionClass::Recovery, request, deadline)
            .map_err(native_error)?;
        Ok(Arc::new(Reservation {
            native,
            response_bytes,
        }))
    }
}
impl StateManagementReservation for Reservation {
    fn uses_native_capacity(&self, owner: &NativeCapacityOwner) -> bool {
        self.native.is_from_owner(owner)
    }
    fn reserved_response_bytes(&self) -> usize {
        // The total also includes request/work capacities and metadata. Only
        // the exact prepaid response capacity can authorize a response frame.
        self.response_bytes
    }
    fn with_live(&self, action: &mut dyn FnMut()) -> Result<(), PlatformError> {
        self.native.with_live(action).map_err(native_error)
    }
}
fn native_error(value: NativeCapacityError) -> PlatformError {
    match value {
        NativeCapacityError::DeadlineExceeded => expired(),
        NativeCapacityError::InvalidRequest | NativeCapacityError::DeadlineTooLong => error(
            PlatformErrorCode::InvalidArgument,
            "invalid-native-management-reservation",
        ),
        NativeCapacityError::ReservationTooLarge
        | NativeCapacityError::SlotsFull
        | NativeCapacityError::BytesFull
        | NativeCapacityError::BufferLimit
        | NativeCapacityError::BufferTooLarge
        | NativeCapacityError::AllocationFailed
        | NativeCapacityError::Exhausted => capacity(),
        NativeCapacityError::InvalidLimits
        | NativeCapacityError::AdmissionClosed
        | NativeCapacityError::Quarantined
        | NativeCapacityError::Poisoned
        | NativeCapacityError::DrainWaiterBusy => error(
            PlatformErrorCode::Unavailable,
            "native-management-owner-unavailable",
        ),
    }
}

#[cfg(test)]
mod tests;
