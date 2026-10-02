//! Input produced by the authoritative prepared component's parameter codec.

use latent_core::HostMemoryReservation;

/// The canonical allocation and its original activation memory charge travel
/// together. The backend must reserve before encoding and retain the same ready
/// owner; this operation must never create a Store or execute a guest.
#[must_use = "retain the memory charge until the canonical input is physically retired"]
pub struct CanonicalTransactionInput {
    bytes: Vec<u8>,
    memory: HostMemoryReservation,
}

impl CanonicalTransactionInput {
    #[must_use = "retain the canonical bytes and their original charge together"]
    pub const fn new(bytes: Vec<u8>, memory: HostMemoryReservation) -> Self {
        Self { bytes, memory }
    }

    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    /// Both parts must remain owned by the activation through native cleanup.
    #[must_use = "retain the returned charge through physical input retirement"]
    pub fn into_parts(self) -> (Vec<u8>, HostMemoryReservation) {
        (self.bytes, self.memory)
    }
}
