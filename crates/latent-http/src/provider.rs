use crate::{
    credentials::{self, CredentialInput, HashWriter, HttpCredential, HttpCredentialReference},
    destination,
    dns::Resolver,
    headers,
    network::Network,
    HttpError, HttpProviderConfig,
};
use latent_capabilities::broker::{
    http::{HttpInvocation, HttpRequest, OutboundHttpInvoker, HTTP_CAPABILITY},
    pools::{InstalledProvider, ProviderClient, ProviderMetadata, ProviderPools, ProviderSetup},
    CapabilitySession, ProviderBudgetRequirement, ProviderConfiguration, ProviderReference,
};
use latent_core::{BudgetDimension, PlatformError};
use sha2::{Digest, Sha256};
use std::{
    sync::Arc,
    time::{Duration, Instant},
};

pub const HTTP_PROVIDER_PROFILE: &str = "bounded-http-v1";
#[derive(Clone)]
pub struct HttpProvider {
    pub(crate) inner: Arc<Inner>,
}
pub(crate) struct Inner {
    pub config: HttpProviderConfig,
    pub credential_references: Vec<HttpCredentialReference>,
    pub streaming: Option<crate::streaming::HttpStreamLimits>,
    pub installed: InstalledProvider,
    pub tls: Arc<rustls::ClientConfig>,
    pub resolver: Resolver,
    pub pools: Arc<ProviderPools>,
    _configuration: ProviderMetadata,
}
impl HttpProvider {
    pub fn install(
        pools: Arc<ProviderPools>,
        logical_id: &str,
        epoch: u64,
        expected_epoch: u64,
        config: HttpProviderConfig,
        credentials: &[HttpCredential<'_>],
    ) -> Result<Self, HttpError> {
        Self::install_profile(
            pools,
            logical_id,
            epoch,
            expected_epoch,
            config,
            CredentialInput::Inline(credentials),
            None,
        )
    }
    pub fn install_with_secret_references(
        pools: Arc<ProviderPools>,
        logical_id: &str,
        epoch: u64,
        expected_epoch: u64,
        config: HttpProviderConfig,
        references: Vec<HttpCredentialReference>,
    ) -> Result<Self, HttpError> {
        Self::install_profile(
            pools,
            logical_id,
            epoch,
            expected_epoch,
            config,
            CredentialInput::References(references),
            None,
        )
    }
    pub(crate) fn install_profile(
        pools: Arc<ProviderPools>,
        logical_id: &str,
        epoch: u64,
        expected_epoch: u64,
        config: HttpProviderConfig,
        credentials: CredentialInput<'_, '_>,
        streaming: Option<crate::streaming::HttpStreamLimits>,
    ) -> Result<Self, HttpError> {
        config.validate()?;
        let (credentials, references) = match credentials {
            CredentialInput::Inline(values) => (values, Vec::new()),
            CredentialInput::References(values) => (&[][..], values),
        };
        if references.capacity() > 16 {
            return Err(HttpError::InvalidRequest);
        }
        let (capability, profile, operation) = profile(&config, streaming)?;
        let configuration = pools.reserve_protocol_metadata(
            65536
                + usize::from(config.public_roots) * 256 * 1024
                + 3 * config.extra_roots.iter().map(Vec::capacity).sum::<usize>(),
        )?;
        let _encoding = pools.reserve_protocol_metadata(8192)?;
        credentials::validate_references(&references, logical_id, &config)?;
        let encoded = credentials::encode(credentials, config.destinations.len())?;
        for credential in credentials {
            if config.destinations[credential.destination]
                .allowed_request_headers
                .iter()
                .any(|h| h.eq_ignore_ascii_case(credential.name))
            {
                return Err(HttpError::InvalidRequest);
            }
        }
        let mut hash = HashWriter(Sha256::new());
        hash.0.update(b"lsf-bounded-http-v1\0");
        if let Some(limits) = streaming {
            hash.0.update(b"streaming-identity-v1\0");
            serde_json::to_writer(&mut hash, &limits).map_err(|_| HttpError::InvalidRequest)?;
        }
        serde_json::to_writer(&mut hash, &config).map_err(|_| HttpError::InvalidRequest)?;
        // Public content identity excludes credentials. Their opaque installed
        // epoch separately fences rotations; publishing a secret hash would
        // permit offline guessing of weak credentials.
        credentials::hash_references(&mut hash, &references)?;
        let digest = format!("sha256:{:x}", hash.0.finalize());
        let tls = crate::tls::configure(&config)?;
        let restriction = serde_json::to_vec(&serde_json::json!({"operations":[operation],"resources":{"kind":"http","origins":config.destinations.iter().map(|d| &d.origin).collect::<Vec<_>>(),"methods":["GET","HEAD","POST","PUT","PATCH","DELETE","OPTIONS"],"paths":[],"pathPrefixes":["/"]}})).map_err(|_| HttpError::InvalidRequest)?;
        let installed = pools.install(
            ProviderSetup {
                logical_id,
                credentials: &encoded,
                authority: ProviderConfiguration {
                    capability,
                    profile,
                    configuration_digest: &digest,
                    configuration_epoch: epoch,
                    restriction_json: &restriction,
                    minimum_call_charges: &[ProviderBudgetRequirement {
                        operation,
                        dimension: BudgetDimension::OutboundRequests,
                        minimum: 1,
                    }],
                },
            },
            expected_epoch,
        )?;
        Ok(Self {
            inner: Arc::new(Inner {
                config,
                credential_references: references,
                streaming,
                installed,
                tls,
                resolver: Resolver::new(),
                pools,
                _configuration: configuration,
            }),
        })
    }
    #[must_use]
    pub fn reference(&self) -> ProviderReference {
        self.inner.installed.reference()
    }
}
impl OutboundHttpInvoker for HttpProvider {
    fn start(
        &self,
        session: &CapabilitySession,
        request: HttpRequest,
    ) -> Result<HttpInvocation, HttpError> {
        if self.inner.streaming.is_some() || !session.uses_provider(&self.reference())? {
            return Err(HttpError::PermissionDenied);
        }
        let destination = destination::parse(&request.url, &self.inner.config)?;
        self.inner
            .check_credential_tenant(session.tenant(), destination.index)?;
        let size = headers::validate(
            &request,
            &self.inner.config.destinations[destination.index],
            self.inner.config.limits,
        )?;
        let now = Instant::now();
        let original = session.deadline()?;
        let deadline = request.timeout_millis.map_or(original, |millis| {
            now + Duration::from_millis(millis).min(original.saturating_duration_since(now))
        });
        let client = self.inner.client(destination.index)?;
        let admission = self.inner.pools.admit_until(&client, session, deadline)?;
        let memory = Arc::new(admission.reserve_input(size.retained, 4096)?);
        let inner = Arc::clone(&self.inner);
        Ok(Box::pin(crate::execute::run(
            inner,
            crate::execute::RequestOwner {
                request,
                destination,
                memory,
                logical: size.logical,
            },
            client,
            admission,
        )))
    }
}
impl Inner {
    pub fn check_credential_tenant(
        &self,
        tenant: &latent_core::TenantId,
        index: usize,
    ) -> Result<(), HttpError> {
        if self
            .credential_references
            .iter()
            .any(|r| r.destination == index && r.binding.scope().tenant != *tenant)
        {
            return Err(HttpError::PermissionDenied);
        }
        Ok(())
    }
    pub fn client(&self, index: usize) -> Result<Arc<ProviderClient<Network>>, HttpError> {
        self.pools
            .client(
                &self.installed,
                u16::try_from(index).map_err(|_| invalid())?,
            )
            .map_err(Into::into)
    }
}
fn invalid() -> PlatformError {
    PlatformError {
        code: latent_core::PlatformErrorCode::InvalidArgument,
        message: "http-provider-config".into(),
        retryable: false,
        details: Vec::new(),
    }
}

fn profile(
    config: &HttpProviderConfig,
    streaming: Option<crate::streaming::HttpStreamLimits>,
) -> Result<(&'static str, &'static str, &'static str), HttpError> {
    let selected = if let Some(limits) = streaming {
        limits.validate()?;
        if config.limits.maximum_redirects != 0
            || config
                .destinations
                .iter()
                .any(|d| !d.redirect_destinations.is_empty())
        {
            return Err(HttpError::InvalidRequest);
        }
        (
            latent_capabilities::broker::streaming_http::STREAMING_HTTP_CAPABILITY,
            crate::streaming::STREAMING_HTTP_PROVIDER_PROFILE,
            "open",
        )
    } else {
        (HTTP_CAPABILITY, HTTP_PROVIDER_PROFILE, "send")
    };
    Ok(selected)
}
