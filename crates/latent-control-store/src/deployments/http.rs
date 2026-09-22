//! HTTP metadata and route selection share the catalog's single publication fence.
mod commit;
mod prepare;
mod reads;
mod selection;
pub(super) mod table;
use super::PublicationView;
use crate::{
    deployment_operations::budget::Charge,
    http_routes::{TriggerOperationReceipt, TriggerReadLease, VersionedTrigger},
};
pub use selection::AcceptedHttpRoute;
use std::sync::{atomic::AtomicBool, Arc};

pub struct PreparedTriggerOperation {
    owner: Arc<AtomicBool>,
    previous: PublicationView,
    next: Arc<table::HttpTable>,
    receipt: TriggerOperationReceipt,
    apply_result: Option<VersionedTrigger>,
    bytes: Vec<u8>,
    replayed: bool,
    reply: TriggerReadLease,
    static_selection: Option<latent_artifacts::web::WebSelection>,
    _scratch: Charge,
    _work: super::rollouts::WorkReservation,
}
impl PreparedTriggerOperation {
    #[must_use]
    pub fn preview(&self) -> &TriggerOperationReceipt {
        &self.receipt
    }
    #[must_use]
    pub fn trigger(&self) -> Option<&VersionedTrigger> {
        self.apply_result.as_ref()
    }
    #[must_use]
    pub fn replayed(&self) -> bool {
        self.replayed
    }
}
fn unavailable() -> latent_core::PlatformError {
    super::error(
        latent_core::PlatformErrorCode::Unavailable,
        "http-route-state-uncertain",
    )
}
fn not_found() -> latent_core::PlatformError {
    super::error(
        latent_core::PlatformErrorCode::NotFound,
        "http-trigger-not-found",
    )
}
