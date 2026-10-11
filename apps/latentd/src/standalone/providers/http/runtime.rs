use super::{unavailable, ProviderRuntime};
use crate::config::HttpInstallation;
use latent_core::PlatformError;
use latent_effects::runtime::{DeferredEffectAdapter, EffectTimeSource};
use std::sync::Arc;

impl ProviderRuntime {
    pub fn deferred_http_adapters(
        &self,
        installation: &HttpInstallation,
        time: Arc<dyn EffectTimeSource>,
    ) -> Result<Vec<Arc<dyn DeferredEffectAdapter>>, PlatformError> {
        self.typed_deferred_http_adapters(installation, time)
            .map(|adapters| {
                adapters
                    .into_iter()
                    .map(|a| a as Arc<dyn DeferredEffectAdapter>)
                    .collect()
            })
    }

    /// Uses the exact already installed buffered provider and its original
    /// TLS, credential, epoch and capacity owners. No second client is installed.
    pub fn typed_deferred_http_adapters(
        &self,
        installation: &HttpInstallation,
        time: Arc<dyn EffectTimeSource>,
    ) -> Result<Vec<Arc<latent_http::deferred::HttpEffectAdapter>>, PlatformError> {
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
                    .map(Arc::new)
                    .map_err(|_| unavailable())
            })
            .collect()
    }
}
