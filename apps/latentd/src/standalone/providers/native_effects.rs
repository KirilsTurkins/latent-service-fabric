//! Native effect construction shares the actual HTTP and protected secret owner.
use super::runtime::{unavailable, ProviderRuntime};
use latent_capabilities::broker::secrets::CredentialScope;
use latent_core::PlatformError;
use latent_effects::runtime::EffectTimeSource;
use latent_http::effects::{PutOnceContract, QualifiedHttpEffectAdapter};
use std::sync::Arc;

impl ProviderRuntime {
    pub(in crate::standalone) fn qualified_http(
        &self,
        contract: PutOnceContract,
        reference: &str,
        time: Arc<dyn EffectTimeSource>,
    ) -> Result<(QualifiedHttpEffectAdapter, u64), PlatformError> {
        let (identity, provider) = self.native_http.as_ref().ok_or_else(unavailable)?;
        if identity.id != contract.provider_id
            || identity.tenant != contract.tenant.0
            || identity.epoch != provider.reference().configuration_epoch()
        {
            return Err(unavailable());
        }
        let credential = self
            .secrets
            .as_ref()
            .ok_or_else(unavailable)?
            .bind_credential(
                CredentialScope {
                    tenant: contract.tenant.clone(),
                    provider_id: contract.provider_id.clone(),
                    origin: contract.origin.clone(),
                },
                reference.into(),
            )
            .map_err(|_| unavailable())?;
        QualifiedHttpEffectAdapter::new(provider, contract, identity.epoch, credential, time)
            .map(|adapter| (adapter, identity.epoch))
            .map_err(|_| unavailable())
    }
}
