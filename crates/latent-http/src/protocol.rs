//! Trusted protocol adapters share HTTP's finite socket/TLS ownership. This
//! transport never grants a guest HTTP capability or accepts a guest endpoint.
mod body;
mod exchange;
use crate::{dns::Answers, network::Network, HttpError, HttpProviderConfig, HttpResolution};
pub use body::{ProtocolBody, ProtocolPage, MAXIMUM_PROTOCOL_BODY_BYTES, PROTOCOL_PAGE_BYTES};
use latent_capabilities::broker::{
    pools::{
        InstalledProvider, MaintenanceRequest, PoolAdmission, PoolCall, ProviderClient,
        ProviderMaintenance, ProviderMetadata, ProviderPools,
    },
    CapabilitySession,
};
use std::{future::Future, sync::Arc, time::Instant};
use zeroize::Zeroizing;

#[derive(Clone, Copy)]
pub enum ProtocolScope<'a> {
    Invocation(&'a PoolCall),
    Maintenance(&'a MaintenanceRequest),
}
impl ProtocolScope<'_> {
    pub(crate) fn checkpoint(self) -> Result<(), HttpError> {
        match self {
            Self::Invocation(call) => call.io().checkpoint()?,
            Self::Maintenance(request) => request.checkpoint()?,
        }
        Ok(())
    }
    pub(crate) async fn wait<F: Future>(self, future: F) -> Result<F::Output, HttpError> {
        self.checkpoint()?;
        match self {
            Self::Invocation(call) => Ok(call.io().wait_for(future).await?),
            Self::Maintenance(request) => {
                let value = tokio::time::timeout_at(request.deadline().into(), future)
                    .await
                    .map_err(|_| HttpError::DeadlineExceeded)?;
                self.checkpoint()?;
                Ok(value)
            }
        }
    }
}
pub struct ProtocolHeader {
    pub name: String,
    pub value: Zeroizing<String>,
    pub sensitive: bool,
}
pub struct ProtocolRequest {
    pub method: String,
    pub path_and_query: String,
    pub headers: Vec<ProtocolHeader>,
    pub body: ProtocolBody,
}
pub struct ProtocolResponse {
    pub status: u16,
    pub headers: Vec<(String, String)>,
    pub body_bytes: usize,
    _metadata: ProviderMetadata,
}
#[derive(Debug)]
pub struct ProtocolFailure {
    pub error: HttpError,
    /// A transport error after an HTTP write can leave a remote mutation uncertain.
    pub request_started: bool,
}
impl From<HttpError> for ProtocolFailure {
    fn from(error: HttpError) -> Self {
        Self {
            error,
            request_started: false,
        }
    }
}
#[derive(Clone)]
pub struct ProtocolTransport {
    inner: Arc<Inner>,
}
struct Inner {
    config: HttpProviderConfig,
    answers: Answers,
    pools: Arc<ProviderPools>,
    client: Arc<ProviderClient<Network>>,
    tls: Arc<rustls::ClientConfig>,
    _metadata: ProviderMetadata,
}
impl ProtocolTransport {
    pub fn new(
        pools: Arc<ProviderPools>,
        provider: &InstalledProvider,
        config: HttpProviderConfig,
    ) -> Result<Self, HttpError> {
        config.validate()?;
        if config.destinations.len() != 1
            || config.destinations[0].origin.scheme != "https"
            || !config.destinations[0].allowed_request_headers.is_empty()
            || !config.destinations[0].redirect_destinations.is_empty()
            || config.limits.maximum_redirects != 0
        {
            return Err(HttpError::InvalidRequest);
        }
        let HttpResolution::Static { addresses } = &config.destinations[0].resolution else {
            return Err(HttpError::InvalidRequest);
        };
        let metadata = pools.reserve_protocol_metadata(
            65536
                + usize::from(config.public_roots) * 256 * 1024
                + 3 * config.extra_roots.iter().map(Vec::capacity).sum::<usize>(),
        )?;
        let answers = Answers::from_static(addresses)?;
        let tls = crate::tls::configure(&config)?;
        let client = pools.client(provider, 0)?;
        Ok(Self {
            inner: Arc::new(Inner {
                config,
                answers,
                pools,
                client,
                tls,
                _metadata: metadata,
            }),
        })
    }
    pub fn admit(&self, session: &CapabilitySession) -> Result<PoolAdmission, HttpError> {
        Ok(self.inner.pools.admit(&self.inner.client, session)?)
    }
    pub fn maintenance(
        &self,
        deadline: Instant,
        requests: usize,
    ) -> Result<ProviderMaintenance, HttpError> {
        Ok(self
            .inner
            .pools
            .maintenance(&self.inner.client, deadline, requests)?)
    }
    /// The callback must be bounded and retain no borrowed data. It receives
    /// unverified protocol bytes; callers validate hashes/status before disclosure.
    pub async fn exchange(
        &self,
        scope: ProtocolScope<'_>,
        request: ProtocolRequest,
        maximum_response_bytes: usize,
        consume: &mut (dyn FnMut(&[u8]) -> Result<(), HttpError> + Send),
    ) -> Result<ProtocolResponse, ProtocolFailure> {
        exchange::run(&self.inner, scope, request, maximum_response_bytes, consume).await
    }
}
