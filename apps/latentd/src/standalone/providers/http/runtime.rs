use super::{unavailable, ProviderRuntime};
use crate::config::HttpInstallation;
use latent_core::PlatformError;
use latent_effects::runtime::{DeferredEffectAdapter, EffectTimeSource};
use std::sync::Arc;

impl ProviderRuntime {
    /// Uses the exact already installed buffered provider and its original
    /// TLS, credential, epoch and capacity owners. No second client is installed.
    pub fn deferred_http_adapters(
        &self,
        installation: &HttpInstallation,
        time: Arc<dyn EffectTimeSource>,
    ) -> Result<Vec<Arc<dyn DeferredEffectAdapter>>, PlatformError> {
        if installation.deferred.is_empty() {
            return Ok(Vec::new());
        }
        if installation.deferred.capacity() > 16 {
            return Err(unavailable());
        }
        let provider = self.http.as_ref().ok_or_else(unavailable)?;
        installation
            .deferred
            .iter()
            .map(move |endpoint| {
                provider
                    .deferred_adapter(
                        &installation.identity.tenant,
                        endpoint.clone(),
                        Arc::clone(&time),
                    )
                    .map(|adapter| Arc::new(adapter) as Arc<dyn DeferredEffectAdapter>)
                    .map_err(|_| unavailable())
            })
            .collect()
    }
}
