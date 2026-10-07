use serde::Serialize;
mod metrics;
pub use metrics::MetricObservation;

pub(in crate::standalone) struct ProviderServices {
    pub audit: latent_audit::AuditHandle,
    pub clock: std::sync::Arc<dyn latent_core::ActivationClock>,
    pub control: tokio::runtime::Handle,
    pub telemetry: Option<latent_telemetry::TelemetryHandle>,
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod runtime;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub(super) use runtime::ProviderRuntime;
#[cfg(all(
    target_os = "linux",
    target_arch = "x86_64",
    feature = "development-outbound-streams"
))]
pub use runtime::StreamControlStatus;
#[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
mod unsupported;
#[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
pub(super) use unsupported::ProviderRuntime;

impl super::StandaloneNode {
    #[cfg(all(
        target_os = "linux",
        target_arch = "x86_64",
        feature = "development-outbound-streams"
    ))]
    pub async fn reload_outbound_streams(
        &mut self,
        guard: &crate::config::StreamReloadGuard,
    ) -> Result<StreamControlStatus, latent_core::PlatformError> {
        self.providers
            .as_deref_mut()
            .ok_or_else(runtime::unavailable)?
            .reload_streams(guard)
            .await
    }

    #[cfg(all(
        target_os = "linux",
        target_arch = "x86_64",
        feature = "development-outbound-streams"
    ))]
    pub async fn publish_outbound_stream_bindings(
        &mut self,
        guard: &crate::config::StreamReloadGuard,
    ) -> Result<StreamControlStatus, latent_core::PlatformError> {
        let owner = self
            .providers
            .as_deref_mut()
            .ok_or_else(runtime::unavailable)?;
        owner.check_stream_reload_owner(guard)?;
        owner.publish_stream_bindings("publish-bindings").await
    }

    #[cfg(all(
        target_os = "linux",
        target_arch = "x86_64",
        feature = "development-outbound-streams"
    ))]
    pub async fn drain_outbound_streams(
        &mut self,
        guard: &crate::config::StreamReloadGuard,
    ) -> Result<StreamControlStatus, latent_core::PlatformError> {
        let owner = self
            .providers
            .as_deref_mut()
            .ok_or_else(runtime::unavailable)?;
        owner.check_stream_reload_owner(guard)?;
        owner.drain_streams().await
    }

    #[cfg(all(
        target_os = "linux",
        target_arch = "x86_64",
        feature = "development-outbound-streams"
    ))]
    pub fn outbound_stream_control_status(
        &self,
    ) -> Result<StreamControlStatus, latent_core::PlatformError> {
        self.providers
            .as_deref()
            .ok_or_else(runtime::unavailable)?
            .stream_control_status("observe", "sampled-not-authority", None)
    }

    /// Builds qualified deferred adapters from the installed provider owner.
    /// Transaction startup supplies the same trusted clock and store runtime.
    pub fn deferred_event_adapters(
        &self,
        settings: &crate::config::NodeSettings,
        time: std::sync::Arc<dyn latent_effects::runtime::EffectTimeSource>,
    ) -> Result<
        Vec<std::sync::Arc<dyn latent_effects::runtime::DeferredEffectAdapter>>,
        latent_core::PlatformError,
    > {
        let Some(events) = settings
            .providers
            .as_ref()
            .and_then(|providers| providers.events.as_ref())
        else {
            return Ok(Vec::new());
        };
        if events.deferred.is_empty() {
            return Ok(Vec::new());
        }
        #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
        {
            self.providers
                .as_ref()
                .ok_or_else(|| {
                    super::error(
                        latent_core::PlatformErrorCode::Unavailable,
                        "deferred event provider owner unavailable",
                    )
                })?
                .deferred_event_adapters(events, time)
        }
        #[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
        {
            let _ = time;
            Err(super::error(
                latent_core::PlatformErrorCode::Unavailable,
                "deferred event provider requires supported Linux host",
            ))
        }
    }
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ProviderDescriptor {
    id: String,
    tenant: String,
    service: String,
    capability: String,
    profile: String,
    configuration_digest: String,
    configuration_epoch: String,
}

#[derive(Debug, Clone, Copy, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ProviderShutdownReport {
    pub clean: bool,
    pub control_owners: usize,
    pub connections: usize,
    pub pending_requests: usize,
    pub running_requests: usize,
    pub workers: usize,
    pub cleanup_jobs: usize,
    pub failed_cleanup: usize,
    pub sessions: usize,
    pub handles: usize,
    pub calls: usize,
    pub results: usize,
    pub io_calls: usize,
    pub io_retained_bytes: usize,
    pub blob_stages: usize,
    pub blob_handles: usize,
    pub blob_work: usize,
    pub secret_generations: usize,
    pub secret_references: usize,
    pub stream_owners: usize,
    pub stream_connections: usize,
    pub stream_pending_operations: usize,
    pub stream_retained_chunks: usize,
    pub stream_maintenance_owners: usize,
}
