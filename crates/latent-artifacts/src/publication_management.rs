//! Additive management results leave historical operation bytes unchanged.

use crate::ReleaseOperationReceipt;
use latent_core::PublicationId;

/// A captured publication and its original bounded operation receipt.
/// Rejected uploads can have no publication; their byte hash is not admission.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicationOperationReceipt {
    pub publication: Option<PublicationId>,
    pub operation: ReleaseOperationReceipt,
}
