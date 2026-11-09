//! Select the existing installed command owner for an authenticated delivery.
use std::sync::Arc;

use latent_core::{PlatformError, PlatformErrorCode};
use latent_manifest::TransactionOperationMode;
use latent_nats::triggers::{InboxAdmissionFactory, InboxDelivery};
use latent_node::{
    transaction_runtime::{
        NativeTransactionAdmission, TransactionAdmissionOwners, TransactionInstallation,
        TransactionSelection,
    },
    InboundActivationReservation,
};

pub(super) struct InboxFactory {
    pub owners: Arc<TransactionAdmissionOwners>,
    pub installations: Vec<Arc<TransactionInstallation>>,
}

impl InboxFactory {
    pub(super) fn check_configuration(
        &self,
        config: &latent_nats::triggers::TriggerConfig,
    ) -> Result<(), PlatformError> {
        let denied = || super::super::error(PlatformErrorCode::PermissionDenied, "inbox-selection");
        for binding in &config.bindings {
            let input = binding.transaction.as_ref().ok_or_else(denied)?;
            let target = latent_routing::InvocationTarget {
                tenant: latent_core::TenantId(binding.tenant.clone()),
                service: latent_core::ServiceId(binding.service.clone()),
                contract: latent_core::ContractId(binding.contract.clone()),
                function: latent_core::FunctionId(binding.function.clone()),
                route: binding.route.clone(),
            };
            let mut matches = 0usize;
            for installation in &self.installations {
                let Some(operation) = installation.operation_for(
                    &target,
                    &input.namespace,
                    TransactionOperationMode::StrictCommand,
                ) else {
                    continue;
                };
                let age = input.qualification.maximum_age_millis;
                if age != 0 && age < installation.identity_retention_millis() {
                    return Err(denied());
                }
                let selection = TransactionSelection {
                    namespace: input.namespace.clone(),
                    incarnation: input.incarnation,
                    entity: None,
                    operation: binding.function.clone(),
                    mode: TransactionOperationMode::StrictCommand,
                    client_key: Some("inbox-startup-probe".into()),
                    expected_versions: Vec::new(),
                    minimum_view_version: None,
                    input_format: operation.input_format.clone(),
                    retry: None,
                };
                NativeTransactionAdmission::new(
                    Arc::clone(&self.owners),
                    Arc::clone(installation),
                    selection,
                )?;
                matches += 1;
            }
            if matches != 1 {
                return Err(denied());
            }
        }
        Ok(())
    }
}

impl InboxAdmissionFactory for InboxFactory {
    fn admission(
        &self,
        reservation: &InboundActivationReservation,
        delivery: &InboxDelivery,
    ) -> Result<Arc<NativeTransactionAdmission>, PlatformError> {
        let denied = || super::super::error(PlatformErrorCode::PermissionDenied, "inbox-selection");
        let selected = reservation.revision();
        if selected.target.tenant.0 != delivery.tenant() {
            return Err(denied());
        }
        let publication = reservation.publication_eligibility()?;
        let mut match_found = None;
        for installation in &self.installations {
            let Some(operation) = installation.operation_for(
                &selected.target,
                delivery.namespace(),
                TransactionOperationMode::StrictCommand,
            ) else {
                continue;
            };
            let Ok(source) = installation.source_for_resolved(selected) else {
                continue;
            };
            if source.publication != publication.publication().as_str()
                || source.release_digest != publication.release().0
                || match_found.is_some()
            {
                return Err(denied());
            }
            match_found = Some((Arc::clone(installation), operation.input_format.clone()));
        }
        let (installation, input_format) = match_found.ok_or_else(denied)?;
        let selection = TransactionSelection {
            namespace: delivery.namespace().into(),
            incarnation: delivery.incarnation(),
            entity: None,
            operation: selected.target.function.0.clone(),
            mode: TransactionOperationMode::StrictCommand,
            client_key: Some(delivery.client_id().into()),
            expected_versions: Vec::new(),
            minimum_view_version: None,
            input_format,
            retry: None,
        };
        Ok(Arc::new(
            NativeTransactionAdmission::new(Arc::clone(&self.owners), installation, selection)?
                .with_trusted_inbox(delivery.identity().clone())?
                .with_trusted_inbox_scope(delivery.scope().clone())?,
        ))
    }
}
