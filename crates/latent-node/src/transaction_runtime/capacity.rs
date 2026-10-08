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
        let request_bytes = u64::try_from(envelope.input.capacity())
            .ok()
            .and_then(|bytes| bytes.checked_mul(2))
            .and_then(|bytes| bytes.checked_add(2 * 1024 * 1024))
            .ok_or_else(unavailable)?;
        let deadline = budget.deadline().monotonic().ok_or_else(unavailable)?;
        // Both independently bounded state/intent staging sets, their encoded
        // copies and the bounded read/authority/codec working set. Engine
        // resident memory is separately bounded by the sole protected owner.
        let work_bytes = 4 * transaction_contract::STAGED_BYTES as u64 + 16 * 1024 * 1024;
        // Canonical output plus encoded transport copy and bounded metadata.
        let response_bytes = 2 * transaction_contract::VALUE_BYTES as u64
            + 4 * transaction_contract::METADATA_BYTES as u64
            + 64 * 1024;
        let native = owner
            .reserve(
                NativeAdmissionClass::Ordinary,
                NativeReservationRequest {
                    request_bytes,
                    work_bytes,
                    response_bytes,
                },
                deadline,
            )
            .map_err(|_| unavailable())?;
        let memory = budget
            .reserve_host_memory(request_bytes)
            .map_err(|error| error.to_platform_error())?;
        Ok(Arc::new(Self {
            _memory: Arc::new(memory),
            native,
        }))
    }

    pub(super) fn with_current<T>(&self, action: impl FnOnce() -> T) -> Result<T, PlatformError> {
        self.native.with_live(action).map_err(|_| unavailable())
    }

    pub(super) fn check_current(&self) -> Result<(), PlatformError> {
        self.with_current(|| ())
    }

    pub(super) fn request_bytes(&self) -> u64 {
        self.native.request_bytes()
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
