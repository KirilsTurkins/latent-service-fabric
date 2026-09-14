use crate::{
    credentials::{self, HashWriter, HttpCredential},
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
            credentials,
            None,
        )
    }
    pub(crate) fn install_profile(
        pools: Arc<ProviderPools>,
        logical_id: &str,
        epoch: u64,
        expected_epoch: u64,
        config: HttpProviderConfig,
        credentials: &[HttpCredential<'_>],
        streaming: Option<crate::streaming::HttpStreamLimits>,
    ) -> Result<Self, HttpError> {
        config.validate()?;
        let (capability, profile, operation) = profile(&config, streaming)?;
        let configuration = pools.reserve_protocol_metadata(
            65536
                + usize::from(config.public_roots) * 256 * 1024
                + 3 * config.extra_roots.iter().map(Vec::capacity).sum::<usize>(),
        )?;
        let _encoding = pools.reserve_protocol_metadata(8192)?;
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
        let digest = format!("sha256:{:x}", hash.0.finalize());
        let mut roots = rustls::RootCertStore::empty();
        if config.public_roots {
            roots.extend(webpki_roots::TLS_SERVER_ROOTS.iter().cloned());
        }
        for certificate in &config.extra_roots {
            roots
                .add(rustls::pki_types::CertificateDer::from(certificate.clone()))
                .map_err(|_| HttpError::InvalidRequest)?;
        }
        if roots.is_empty()
            && config
                .destinations
                .iter()
                .any(|d| d.origin.scheme == "https")
        {
            return Err(HttpError::InvalidRequest);
        }
        let mut tls = rustls::ClientConfig::builder_with_provider(Arc::new(
            rustls::crypto::ring::default_provider(),
        ))
        .with_safe_default_protocol_versions()
        .map_err(|_| HttpError::InvalidRequest)?
        .with_root_certificates(roots)
        .with_no_client_auth();
        tls.alpn_protocols = vec![b"http/1.1".to_vec()];
        tls.resumption = rustls::client::Resumption::disabled();
        tls.enable_early_data = false;
        tls.cert_decompressors.clear();
        tls.key_log = Arc::new(rustls::NoKeyLog);
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
                streaming,
                installed,
                tls: Arc::new(tls),
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
