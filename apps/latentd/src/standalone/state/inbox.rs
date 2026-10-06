//! The existing installed command runtime consumes only sealed inbox identities.
use super::{StateRequest, StateRuntime};
use latent_core::PlatformError;
use latent_nats::triggers::{InboxAdmissionFactory, InboxDelivery};
use latent_node::{
    transaction_runtime::command_completion::CanonicalCommandResult, InboundActivationReservation,
    TransactionActivationAdmission,
};
use std::sync::Arc;

impl InboxAdmissionFactory for StateRuntime {
    fn admission(
        &self,
        reservation: &InboundActivationReservation,
        delivery: &InboxDelivery,
    ) -> Result<Arc<dyn TransactionActivationAdmission>, PlatformError> {
        let publication = reservation.publication_eligibility()?;
        let target = &reservation.revision().target;
        let installed = self
            .0
            .installed
            .iter()
            .find(|operation| {
                operation.target() == target
                    && operation.target().tenant.0 == delivery.tenant()
                    && operation.publication().cache_digest() == publication.cache_digest()
                    && operation.namespace() == delivery.namespace()
                    && operation.incarnation() == delivery.incarnation()
                    && operation.mode() == latent_manifest::TransactionOperationMode::StrictCommand
            })
            .ok_or_else(super::denied)?;
        installed.publication().check_current()?;
        self.admission(
            Arc::clone(installed),
            StateRequest::inbox(delivery)?,
            Arc::new(CanonicalCommandResult),
        )
    }
}
