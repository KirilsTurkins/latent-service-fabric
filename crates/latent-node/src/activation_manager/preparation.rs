use std::sync::Arc;

use latent_activation::ActivationEnvelope;
use latent_core::{ActivationBudget, CapabilityId, PlatformError, PlatformErrorCode};
use latent_executor::{
    BoundImport, PreparationKey, PreparedComponent, PreparedReadiness, PreparedUse,
};

use crate::CancellationToken;

use super::control::{cancelled, deadline_error, error, stage};
use super::probes::ActivationControl;
use super::transport_stop::TransportStop;
use super::Inner;

impl Inner {
    pub(super) async fn prepare_ready(
        &self,
        envelope: &ActivationEnvelope,
        token: &CancellationToken,
        budget: &ActivationBudget,
        transport: &TransportStop,
    ) -> Result<(PreparationKey, PreparedReadiness), PlatformError> {
        let release = &envelope
            .resolved_revision
            .as_ref()
            .expect("pinned revision")
            .release;
        let key = self.dependencies.backend.preparation_key(release)?;
        if &key.release != release {
            return Err(error(
                PlatformErrorCode::IncompatibleContract,
                "backend preparation key changed the pinned release",
            ));
        }
        let ready = stage(
            self.dependencies.backend.prepare_ready_from_repository(
                Arc::clone(&self.dependencies.artifacts),
                key.clone(),
            ),
            token,
            budget.deadline().monotonic(),
            &self.clock,
            transport,
        )
        .await?;
        self.verify_preparation(ready.descriptor(), &key)?;
        Ok((key, ready))
    }

    pub(super) fn materialize(
        &self,
        envelope: &ActivationEnvelope,
        control: &ActivationControl,
        budget: &ActivationBudget,
        key: &PreparationKey,
        ready: PreparedReadiness,
    ) -> Result<(PreparedUse, Vec<BoundImport>), PlatformError> {
        if control.token().is_cancelled() {
            return Err(cancelled(control.token()));
        }
        if budget.deadline().is_expired_at(self.clock.monotonic_now()) {
            return Err(deadline_error());
        }
        if let Some(failure) = control.transport().failure() {
            return Err(failure);
        }
        self.verify_preparation(ready.descriptor(), key)?;
        let activation = self.dependencies.backend.materialize_ready(ready)?;
        self.verify_preparation(activation.prepared.descriptor(), key)?;
        let imports = activation
            .imports
            .into_iter()
            .map(|import| BoundImport {
                capability: CapabilityId(import.0.clone()),
                contract: import.0,
                opaque_handle: envelope.activation_id.0.clone(),
            })
            .collect();
        Ok((activation.prepared, imports))
    }

    fn verify_preparation(
        &self,
        prepared: &PreparedComponent,
        key: &PreparationKey,
    ) -> Result<(), PlatformError> {
        if &prepared.key != key || prepared.backend != self.dependencies.backend.backend_id() {
            return Err(error(
                PlatformErrorCode::IncompatibleContract,
                "prepared ownership does not match the requested release or backend",
            ));
        }
        Ok(())
    }
}
