use latent_core::{PlatformError, PlatformErrorCode};
use latent_effects::runtime::{DeferredEffectAdapter, EffectTimeSource};
use std::sync::Arc;

impl crate::standalone::StandaloneNode {
    /// Builds approved adapters from the same installed immediate HTTP owner.
    /// The caller supplies protected node settings and the shared runtime clock.
    pub fn deferred_http_adapters(
        &self,
        settings: &crate::config::NodeSettings,
        time: Arc<dyn EffectTimeSource>,
    ) -> Result<Vec<Arc<dyn DeferredEffectAdapter>>, PlatformError> {
        let Some(http) = settings
            .providers
            .as_ref()
            .and_then(|providers| providers.http.as_ref())
        else {
            return Ok(Vec::new());
        };
        if http.deferred.is_empty() {
            return Ok(Vec::new());
        }
        #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
        {
            self.providers
                .as_ref()
                .ok_or_else(|| {
                    crate::standalone::error(
                        PlatformErrorCode::Unavailable,
                        "deferred HTTP provider owner unavailable",
                    )
                })?
                .deferred_http_adapters(http, time)
        }
        #[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
        {
            let _ = time;
            Err(crate::standalone::error(
                PlatformErrorCode::Unavailable,
                "deferred HTTP provider requires supported Linux host",
            ))
        }
    }
}
