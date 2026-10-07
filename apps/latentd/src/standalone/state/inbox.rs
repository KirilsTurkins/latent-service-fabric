//! The existing installed command runtime consumes only sealed inbox identities.
use super::{StateRequest, StateRuntime};
use latent_core::PlatformError;
use latent_nats::triggers::{InboxAdmissionFactory, InboxDelivery};
use latent_node::{
    transaction_runtime::command_completion::CanonicalCommandResult, InboundActivationReservation,
    TransactionActivationAdmission,
};
use std::sync::Arc;

impl StateRuntime {
    pub(in crate::standalone) fn check_inbox_configuration(
        &self,
        configuration: &latent_nats::triggers::TriggerConfig,
    ) -> Result<(), PlatformError> {
        for binding in &configuration.bindings {
            let selected = binding.transaction.as_ref().ok_or_else(super::denied)?;
            let operation = self
                .0
                .installed
                .iter()
                .find(|operation| {
                    let target = operation.target();
                    target.tenant.0 == binding.tenant
                        && target.service.0 == binding.service
                        && target.contract.0 == binding.contract
                        && target.function.0 == binding.function
                        && target.route == binding.route
                        && operation.namespace() == selected.namespace
                        && operation.incarnation() == selected.incarnation
                        && operation.mode()
                            == latent_manifest::TransactionOperationMode::StrictCommand
                })
                .ok_or_else(super::denied)?;
            operation.publication().check_current()?;
        }
        Ok(())
    }
}

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
