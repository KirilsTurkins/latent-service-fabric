//! Versioned identity-encoding streams over the same closed HTTP authority.
use crate::{
    destination, headers, provider::Inner, HttpCredential, HttpError, HttpProvider,
    HttpProviderConfig,
};
use latent_capabilities::broker::{
    pools::ProviderPools,
    streaming_http::{
        StreamingHttpError, StreamingHttpInvocation, StreamingHttpInvoker, StreamingHttpRequest,
    },
    CapabilitySession, ProviderReference,
};
use serde::{Deserialize, Serialize};
use std::{
    sync::Arc,
    time::{Duration, Instant},
};
mod exchange;
mod phase;
mod response;
pub(crate) mod wire;
pub const STREAMING_HTTP_PROVIDER_PROFILE: &str = "bounded-streaming-http-identity-v1";
pub const PHASE_TIMING_HTTP_PROVIDER_PROFILE: &str = "bounded-streaming-http-phase-timing-v1";
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct HttpStreamLimits {
    pub maximum_input_bytes: u64,
    pub maximum_output_bytes: u64,
    pub maximum_chunk_bytes: usize,
    pub maximum_outstanding_chunks: usize,
}
impl Default for HttpStreamLimits {
    fn default() -> Self {
        Self {
            maximum_input_bytes: 16 * 1024 * 1024,
            maximum_output_bytes: 16 * 1024 * 1024,
            maximum_chunk_bytes: 16 * 1024,
            maximum_outstanding_chunks: 4,
        }
    }
}
impl HttpStreamLimits {
    /// Check the closed transfer and chunk ceilings without installing a provider.
    pub fn validate(self) -> Result<(), HttpError> {
        if self.maximum_input_bytes > 63 * 1024 * 1024
            || self.maximum_output_bytes == 0
            || self.maximum_output_bytes > 63 * 1024 * 1024
            || !(1..=65536).contains(&self.maximum_chunk_bytes)
            || !(1..=32).contains(&self.maximum_outstanding_chunks)
        {
            return Err(HttpError::InvalidRequest);
        }
        Ok(())
    }
}
#[derive(Clone)]
pub struct StreamingHttpProvider {
    pub(crate) provider: HttpProvider,
}
impl StreamingHttpProvider {
    pub fn install(
        pools: Arc<ProviderPools>,
        logical_id: &str,
        epoch: u64,
        expected_epoch: u64,
        config: HttpProviderConfig,
        limits: HttpStreamLimits,
        credentials: &[HttpCredential<'_>],
    ) -> Result<Self, HttpError> {
        Ok(Self {
            provider: HttpProvider::install_profile(
                pools,
                logical_id,
                epoch,
                expected_epoch,
                config,
                crate::credentials::CredentialInput::Inline(credentials),
                Some(crate::provider::StreamingProfile::Identity(limits)),
            )?,
        })
    }
    pub fn install_with_secret_references(
        pools: Arc<ProviderPools>,
        logical_id: &str,
        epoch: u64,
        expected_epoch: u64,
        config: HttpProviderConfig,
        limits: HttpStreamLimits,
        references: Vec<crate::HttpCredentialReference>,
    ) -> Result<Self, HttpError> {
        Ok(Self {
            provider: HttpProvider::install_profile(
                pools,
                logical_id,
                epoch,
                expected_epoch,
                config,
                crate::credentials::CredentialInput::References(references),
                Some(crate::provider::StreamingProfile::Identity(limits)),
            )?,
        })
    }
    #[must_use]
    pub fn reference(&self) -> ProviderReference {
        self.provider.reference()
    }

    /// Install a distinct, explicitly selected authority for HTTP phase timers.
    pub fn install_phase_timing(
        pools: Arc<ProviderPools>,
        logical_id: &str,
        epoch: u64,
        expected_epoch: u64,
        config: HttpProviderConfig,
        limits: HttpStreamLimits,
        credentials: &[HttpCredential<'_>],
    ) -> Result<Self, HttpError> {
        Ok(Self {
            provider: HttpProvider::install_profile(
                pools,
                logical_id,
                epoch,
                expected_epoch,
                config,
                crate::credentials::CredentialInput::Inline(credentials),
                Some(crate::provider::StreamingProfile::PhaseTiming(limits)),
            )?,
        })
    }

    pub fn install_phase_timing_with_secret_references(
        pools: Arc<ProviderPools>,
        logical_id: &str,
        epoch: u64,
        expected_epoch: u64,
        config: HttpProviderConfig,
        limits: HttpStreamLimits,
        references: Vec<crate::HttpCredentialReference>,
    ) -> Result<Self, HttpError> {
        Ok(Self {
            provider: HttpProvider::install_profile(
                pools,
                logical_id,
                epoch,
                expected_epoch,
                config,
                crate::credentials::CredentialInput::References(references),
                Some(crate::provider::StreamingProfile::PhaseTiming(limits)),
            )?,
        })
    }
}
impl StreamingHttpInvoker for StreamingHttpProvider {
    fn start(
        &self,
        session: &CapabilitySession,
        request: StreamingHttpRequest,
    ) -> Result<StreamingHttpInvocation, StreamingHttpError> {
        let inner = &self.provider.inner;
        if !session.uses_provider(&self.reference())? {
            return Err(HttpError::PermissionDenied.into());
        }
        let limits = inner.streaming.expect("streaming configuration");
        if request.metadata.body.is_some()
            || request
                .body_length
                .is_some_and(|n| n > limits.maximum_input_bytes)
        {
            return Err(HttpError::InvalidRequest.into());
        }
        let destination = destination::parse(&request.metadata.url, &inner.config)?;
        inner.check_credential_tenant(session.tenant(), destination.index)?;
        let size = headers::validate(
            &request.metadata,
            &inner.config.destinations[destination.index],
            inner.config.limits,
        )?;
        let now = Instant::now();
        let original = session.deadline()?;
        let deadline = request.metadata.timeout_millis.map_or(original, |millis| {
            now + Duration::from_millis(millis).min(original.saturating_duration_since(now))
        });
        let client = inner.client(destination.index)?;
        let admission = inner.pools.admit_until(&client, session, deadline)?;
        let memory = Arc::new(admission.reserve_input(size.retained, 4096)?);
        Ok(Box::pin(exchange::open(
            Arc::clone(inner),
            crate::execute::RequestOwner {
                request: request.metadata,
                destination,
                memory,
                logical: size.logical,
            },
            request.body_length,
            client,
            admission,
        )))
    }
    fn start_with_connect_timeout(
        &self,
        session: &CapabilitySession,
        request: StreamingHttpRequest,
        timeout_millis: Option<u32>,
    ) -> Result<
        latent_capabilities::broker::streaming_http::PhaseHttpInvocation,
        latent_capabilities::broker::streaming_http::HttpPhaseError,
    > {
        let inner = &self.provider.inner;
        if timeout_millis.is_none_or(|millis| millis == 0) {
            let opening = self.start(session, request)?;
            return Ok(Box::pin(async move { opening.await.map_err(Into::into) }));
        }
        if !inner.phase_timing {
            return Err(latent_capabilities::broker::streaming_http::HttpPhaseError::Unsupported);
        }
        if !session.uses_provider(&self.reference())? {
            return Err(HttpError::PermissionDenied.into());
        }
        let limits = inner.streaming.expect("streaming configuration");
        if request.metadata.body.is_some()
            || request
                .body_length
                .is_some_and(|n| n > limits.maximum_input_bytes)
        {
            return Err(HttpError::InvalidRequest.into());
        }
        let destination = destination::parse(&request.metadata.url, &inner.config)?;
        inner.check_credential_tenant(session.tenant(), destination.index)?;
        let size = headers::validate(
            &request.metadata,
            &inner.config.destinations[destination.index],
            inner.config.limits,
        )?;
        let now = Instant::now();
        let original = session.deadline()?;
        let deadline = request.metadata.timeout_millis.map_or(original, |millis| {
            now + Duration::from_millis(millis).min(original.saturating_duration_since(now))
        });
        let client = inner.client(destination.index)?;
        let admission = inner.pools.admit_until(&client, session, deadline)?;
        let memory = Arc::new(admission.reserve_input(size.retained, 4096)?);
        let deadline = phase::Deadline::new(admission.stop_handle(), timeout_millis)?;
        let opening = exchange::open(
            Arc::clone(inner),
            crate::execute::RequestOwner {
                request: request.metadata,
                destination,
                memory,
                logical: size.logical,
            },
            request.body_length,
            client,
            admission,
        );
        Ok(Box::pin(async move {
            deadline
                .wait(
                    opening,
                    latent_capabilities::broker::streaming_http::HttpPhaseError::ConnectTimeout,
                )
                .await?
                .map_err(Into::into)
        }))
    }
}
