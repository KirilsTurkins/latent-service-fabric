//! Prepaid original request, native work and response ownership.
use latent_activation::ActivationEnvelope;
use latent_core::{
    native_capacity::{
        NativeAdmissionClass, NativeCapacityOwner, NativeReservation, NativeReservationRequest,
    },
    transaction_contract, ActivationBudget, HostMemoryReservation, PlatformError,
    PlatformErrorCode,
};
use std::sync::Arc;
use std::time::Instant;

const REQUEST_METADATA_BYTES: u64 = 2 * 1024 * 1024;
const WORK_BYTES: u64 = 4 * transaction_contract::STAGED_BYTES as u64 + 16 * 1024 * 1024;
const RESPONSE_BYTES: u64 = 8 * transaction_contract::VALUE_BYTES as u64 + 16 * 1024;

pub(super) fn reserve_ingress(
    owner: &NativeCapacityOwner,
    encoded_request_bytes: usize,
    deadline: Instant,
) -> Result<NativeReservation, PlatformError> {
    owner
        .reserve(
            NativeAdmissionClass::Ordinary,
            NativeReservationRequest {
                request_bytes: request_bytes(encoded_request_bytes)?,
                work_bytes: WORK_BYTES,
                response_bytes: RESPONSE_BYTES,
            },
            deadline,
        )
        .map_err(|_| unavailable())
}

fn request_bytes(input_capacity: usize) -> Result<u64, PlatformError> {
    u64::try_from(input_capacity)
        .ok()
        .and_then(|bytes| bytes.checked_mul(2))
        .and_then(|bytes| bytes.checked_add(REQUEST_METADATA_BYTES))
        .ok_or_else(unavailable)
}

/// A sealed physical retention guard. It contains no guest Store or cell.
/// Moving or cloning its Arc never admits another operation or renews a deadline.
pub struct TransactionRetention {
    _memory: Arc<HostMemoryReservation>,
    native: NativeReservation,
}

impl TransactionRetention {
    pub(super) fn reserve(
        owner: &NativeCapacityOwner,
        envelope: &ActivationEnvelope,
        budget: &ActivationBudget,
    ) -> Result<Arc<Self>, PlatformError> {
        let deadline = budget.deadline().monotonic().ok_or_else(unavailable)?;
        // Both independently bounded state/intent staging sets, their encoded
        // copies and the bounded read/authority/codec working set. Engine
        // resident memory is separately bounded by the sole protected owner.
        // The frozen public response is bounded to two canonical value sizes.
        // Prepay the same four-copy/body/frame envelope required by Wire before
        // any native lookup or guest execution, including encoder metadata.
        let native = reserve_ingress(owner, envelope.input.capacity(), deadline)?;
        Self::from_ingress(owner, native, envelope, budget)
    }

    pub(super) fn validate_ingress(
        owner: &NativeCapacityOwner,
        native: &NativeReservation,
    ) -> Result<(), PlatformError> {
        if !native.is_from_owner(owner)
            || native.class() != NativeAdmissionClass::Ordinary
            || native.request_bytes() < REQUEST_METADATA_BYTES
            || native.work_bytes() < WORK_BYTES
            || native.response_bytes() < RESPONSE_BYTES
        {
            return Err(unavailable());
        }
        native.with_live(|| ()).map_err(|_| unavailable())
    }

    pub(super) fn from_ingress(
        owner: &NativeCapacityOwner,
        native: NativeReservation,
        envelope: &ActivationEnvelope,
        budget: &ActivationBudget,
    ) -> Result<Arc<Self>, PlatformError> {
        Self::validate_ingress(owner, &native)?;
        if native.request_bytes() < request_bytes(envelope.input.capacity())? {
            return Err(unavailable());
        }
        let retained_bytes = native
            .request_bytes()
            .checked_add(native.response_bytes())
            .ok_or_else(unavailable)?;
        let memory = budget
            .reserve_host_memory(retained_bytes)
            .map_err(|error| error.to_platform_error())?;
        Ok(Arc::new(Self {
            _memory: Arc::new(memory),
            native,
        }))
    }

    pub(super) fn with_current<T>(&self, action: impl FnOnce() -> T) -> Result<T, PlatformError> {
        self.native.with_live(action).map_err(|_| unavailable())
    }

    pub(super) fn monotonic_now(&self) -> Instant {
        self.native.monotonic_now()
    }

    pub(super) fn with_current_until<T>(
        &self,
        deadline: Instant,
        action: impl FnOnce() -> T,
    ) -> Result<T, PlatformError> {
        self.native
            .with_live_until(deadline, action)
            .map_err(|_| unavailable())
    }

    pub(super) fn check_current(&self) -> Result<(), PlatformError> {
        self.with_current(|| ())
    }

    pub(super) fn request_bytes(&self) -> u64 {
        self.native.request_bytes()
    }

    pub(super) fn response_bytes(&self) -> u64 {
        self.native.response_bytes()
    }
}

fn unavailable() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::ResourceExhausted,
        message: "transaction native admission unavailable".into(),
        retryable: false,
        details: Vec::new(),
    }
}
