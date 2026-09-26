pub(super) mod client;
use super::auth::{self, ConfiguredBearer};
use super::network::Network;
use super::reference::Endpoint;
use super::{
    exhausted, invalid, BearerIdentity, BearerUsage, RegistryConfig, RegistryLimits,
    RegistryNetworkPolicy, RegistryNetworkUsage, Result,
};
use bytes::Bytes;
use latent_core::{PlatformError, PlatformErrorCode};
use reqwest::{
    header::{HeaderMap, HeaderValue},
    Method, Response, StatusCode, Url,
};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use tokio::{
    sync::{OwnedSemaphorePermit, Semaphore},
    time::{timeout_at, Instant},
};

pub(crate) struct Transport {
    pub(crate) endpoint: Endpoint,
    pub(crate) limits: RegistryLimits,
    client: Option<reqwest::Client>,
    auth: Option<HeaderValue>,
    challenge: Option<ConfiguredBearer>,
    network: Option<Arc<Network>>,
    operations: Arc<Semaphore>,
    packages: Arc<Semaphore>,
    bytes: Arc<Semaphore>,
    closed: AtomicBool,
}
pub(crate) struct Operation {
    pub(crate) deadline: Instant,
    _slot: OwnedSemaphorePermit,
    _bytes: OwnedSemaphorePermit,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RegistryUsage {
    pub in_flight: usize,
    pub retained_packages: usize,
    pub retained_bytes: usize,
    pub closed: bool,
    pub bearer: Option<BearerUsage>,
    pub network: Option<RegistryNetworkUsage>,
}
impl Transport {
    pub(crate) fn new(config: RegistryConfig) -> Result<Self> {
        Self::new_with_network(config, None)
    }
    pub(crate) fn new_with_network(
        mut config: RegistryConfig,
        network: Option<RegistryNetworkPolicy>,
    ) -> Result<Self> {
        config.limits.validate()?;
        let endpoint = if network.is_some() {
            Endpoint::configured(&config, true)?
        } else {
            Endpoint::new(&config)?
        };
        let network = network
            .map(|network| Network::new(&config, network).map(Arc::new))
            .transpose()?;
        let challenge = if let Some(network) = &network {
            ConfiguredBearer::with_network(&config, Some(network))?
        } else {
            ConfiguredBearer::new(&config)?
        };
        let client = network
            .is_none()
            .then(|| client::build(&config, &endpoint))
            .transpose()?;
        let auth = client::authorization(&config.credentials)?;
        let limits = config.limits;
        config.credentials.clear_secrets();
        drop(config);
        Ok(Self {
            client,
            auth,
            challenge,
            network,
            endpoint,
            limits,
            operations: Arc::new(Semaphore::new(limits.max_in_flight)),
            packages: Arc::new(Semaphore::new(limits.max_retained_packages)),
            bytes: Arc::new(Semaphore::new(limits.max_retained_bytes as usize)),
            closed: AtomicBool::new(false),
        })
    }
    pub(crate) fn begin(&self, bytes: usize) -> Result<Operation> {
        let permit = self
            .operations
            .clone()
            .try_acquire_owned()
            .map_err(|_| exhausted("oci-in-flight-limit"))?;
        if self.closed.load(Ordering::Acquire) {
            return Err(crate::error(
                PlatformErrorCode::Unavailable,
                "oci-client-closed",
            ));
        }
        Ok(Operation {
            deadline: Instant::now() + self.limits.operation_timeout,
            _slot: permit,
            _bytes: self.lease_bytes(bytes)?,
        })
    }
    pub(crate) fn lease_bytes(&self, bytes: usize) -> Result<OwnedSemaphorePermit> {
        let count = u32::try_from(bytes).map_err(|_| exhausted("oci-materialization-limit"))?;
        self.bytes
            .clone()
            .try_acquire_many_owned(count)
            .map_err(|_| exhausted("oci-materialization-limit"))
    }
    pub(crate) fn lease_package(&self) -> Result<OwnedSemaphorePermit> {
        self.packages
            .clone()
            .try_acquire_owned()
            .map_err(|_| exhausted("oci-retained-package-limit"))
    }
    pub(crate) fn usage(&self) -> RegistryUsage {
        RegistryUsage {
            in_flight: self.limits.max_in_flight - self.operations.available_permits(),
            retained_packages: self.limits.max_retained_packages
                - self.packages.available_permits(),
            retained_bytes: self.limits.max_retained_bytes as usize
                - self.bytes.available_permits(),
            closed: self.closed.load(Ordering::Acquire),
            bearer: self.challenge.as_ref().map(ConfiguredBearer::usage),
            network: self.network.as_ref().map(|network| network.usage()),
        }
    }

    pub(crate) fn rotate_bearer_credentials(
        &self,
        identity: BearerIdentity,
        username: &str,
        password: &str,
    ) -> Result<()> {
        if self.closed.load(Ordering::Acquire) {
            return Err(crate::error(
                PlatformErrorCode::Unavailable,
                "oci-client-closed",
            ));
        }
        self.challenge
            .as_ref()
            .ok_or_else(|| invalid("oci-bearer-not-configured"))?
            .rotate(identity, username, password)
    }
    pub(crate) async fn close_and_wait(&self, deadline: Instant) -> Result<()> {
        self.closed.store(true, Ordering::Release);
        let count =
            u32::try_from(self.limits.max_in_flight).map_err(|_| invalid("invalid-oci-limits"))?;
        let permit = timeout_at(deadline, self.operations.clone().acquire_many_owned(count))
            .await
            .map_err(|_| {
                crate::error(PlatformErrorCode::DeadlineExceeded, "oci-shutdown-deadline")
            })?
            .map_err(|_| crate::error(PlatformErrorCode::Unavailable, "oci-client-closed"))?;
        drop(permit);
        if let Some(challenge) = &self.challenge {
            challenge.close()?;
        }
        if let Some(network) = &self.network {
            network.close(deadline).await?;
        }
        Ok(())
    }
    pub(crate) async fn send(
        &self,
        method: Method,
        url: Url,
        body: Option<Bytes>,
        content_type: Option<&str>,
        deadline: Instant,
    ) -> Result<Response> {
        let mut response = self
            .send_registry(
                method.clone(),
                url.clone(),
                body.clone(),
                content_type,
                deadline,
            )
            .await?;
        let Some(network) = &self.network else {
            return Ok(response);
        };
        let mut current = url;
        let _redirect = if response.status().is_redirection() {
            Some(network.redirect_lease()?)
        } else {
            None
        };
        let mut seen = Vec::new();
        while response.status().is_redirection() {
            if !auth::read_continuation_allowed(&method, body.is_some())
                || !matches!(response.status().as_u16(), 301 | 302 | 303 | 307 | 308)
                || (!current
                    .path()
                    .starts_with(&format!("/v2/{}/blobs/sha256:", self.endpoint.repository))
                    && seen.is_empty())
                || seen.len() >= network.maximum_redirects
            {
                return Err(invalid("oci-redirect-outside-profile"));
            }
            let location = response
                .headers()
                .get(reqwest::header::LOCATION)
                .and_then(|value| value.to_str().ok())
                .ok_or_else(|| invalid("invalid-oci-content-redirect"))?;
            let (target, client) = network.content_target(&current, location)?;
            if target == current || seen.contains(&target) {
                return Err(invalid("oci-content-redirect-cycle"));
            }
            seen.push(current);
            current = target;
            drop(response);
            response = client
                .send(
                    method.clone(),
                    current.clone(),
                    HeaderMap::new(),
                    None,
                    deadline,
                )
                .await?;
        }
        Ok(response)
    }

    async fn send_registry(
        &self,
        method: Method,
        url: Url,
        body: Option<Bytes>,
        content_type: Option<&str>,
        deadline: Instant,
    ) -> Result<Response> {
        let Some(challenge) = self.challenge.as_ref() else {
            return self
                .send_once(
                    method,
                    url,
                    body,
                    content_type,
                    deadline,
                    self.auth.as_ref(),
                )
                .await;
        };
        challenge.require_method(&method)?;
        let epoch = challenge.epoch()?;
        let mut token = challenge.cached(epoch)?;
        let may_continue = auth::read_continuation_allowed(&method, body.is_some());
        if token.is_none() && !may_continue {
            token = Some(challenge.acquire(self, epoch, deadline).await?);
        }
        if let Some(token) = &token {
            challenge.current(token)?;
        }
        let mut response = self
            .send_once(
                method.clone(),
                url.clone(),
                body.clone(),
                content_type,
                deadline,
                token.as_ref().map(|token| &token.authorization),
            )
            .await?;
        if let Some(token) = &token {
            response.extensions_mut().insert(Arc::clone(token));
        }
        if response.status() != StatusCode::UNAUTHORIZED {
            return Ok(response);
        }
        if !may_continue {
            if let Some(token) = &token {
                challenge.invalidate(token)?;
            }
            return Ok(response);
        }
        challenge.validate_challenge(response.headers())?;
        drop(response);
        if let Some(token) = token {
            challenge.invalidate(&token)?;
        }
        let bearer = challenge.acquire(self, epoch, deadline).await?;
        challenge.current(&bearer)?;

        // There is exactly one authentication continuation. A second 401 is
        // returned to the caller and is never converted into a challenge loop.
        let mut response = self
            .send_once(
                method,
                url,
                body,
                content_type,
                deadline,
                Some(&bearer.authorization),
            )
            .await?;
        if response.status() == StatusCode::UNAUTHORIZED {
            challenge.invalidate(&bearer)?;
        }
        response.extensions_mut().insert(bearer);
        Ok(response)
    }

    async fn send_once(
        &self,
        method: Method,
        url: Url,
        body: Option<Bytes>,
        content_type: Option<&str>,
        deadline: Instant,
        authorization: Option<&HeaderValue>,
    ) -> Result<Response> {
        self.endpoint.check_url(&url)?;
        if let Some(network) = &self.network {
            let mut headers = HeaderMap::new();
            headers.insert(reqwest::header::ACCEPT, HeaderValue::from_static("application/vnd.oci.image.manifest.v1+json, application/vnd.oci.image.index.v1+json"));
            if let Some(authorization) = authorization {
                headers.insert(reqwest::header::AUTHORIZATION, authorization.clone());
            }
            if let Some(content_type) = content_type {
                headers.insert(
                    reqwest::header::CONTENT_TYPE,
                    HeaderValue::from_str(content_type)
                        .map_err(|_| invalid("invalid-oci-content-type"))?,
                );
            }
            return network
                .client(&url)?
                .send(method, url, headers, body, deadline)
                .await;
        }
        let remaining = deadline
            .checked_duration_since(Instant::now())
            .filter(|time| !time.is_zero())
            .ok_or_else(|| {
                crate::error(
                    PlatformErrorCode::DeadlineExceeded,
                    "oci-operation-deadline",
                )
            })?;
        let mut request = self
            .client
            .as_ref()
            .ok_or_else(|| invalid("oci-static-transport-unavailable"))?
            .request(method, url)
            .timeout(remaining.min(self.limits.request_timeout));
        if let Some(auth) = authorization {
            request = request.header(reqwest::header::AUTHORIZATION, auth.clone());
        }
        if let Some(content_type) = content_type {
            request = request.header(reqwest::header::CONTENT_TYPE, content_type);
        }
        if let Some(body) = body {
            request = request
                .header(reqwest::header::CONTENT_LENGTH, body.len())
                .body(body);
        }
        let response = request
            .send()
            .await
            .map_err(|error| network_error(&error))?;
        super::body::headers(&response)?;
        Ok(response)
    }
}
pub(crate) fn network_error(error: &reqwest::Error) -> PlatformError {
    if let Some(error) = super::network::response_error(error) {
        return error;
    }
    if error.is_timeout() {
        crate::error(PlatformErrorCode::DeadlineExceeded, "oci-request-deadline")
    } else {
        crate::error(PlatformErrorCode::Unavailable, "oci-transport-failed")
    }
}
pub(crate) fn expect_status(response: &Response, expected: &[StatusCode]) -> Result<()> {
    if expected.contains(&response.status()) {
        return Ok(());
    }
    let code = match response.status() {
        StatusCode::UNAUTHORIZED => PlatformErrorCode::Unauthenticated,
        StatusCode::FORBIDDEN => PlatformErrorCode::PermissionDenied,
        StatusCode::NOT_FOUND => PlatformErrorCode::NotFound,
        StatusCode::TOO_MANY_REQUESTS => PlatformErrorCode::ResourceExhausted,
        status if status.is_server_error() => PlatformErrorCode::Unavailable,
        _ => PlatformErrorCode::InvalidArgument,
    };
    Err(crate::error(code, "oci-unexpected-response-status"))
}
pub(crate) fn verify_digest_header(headers: &HeaderMap, expected: &str) -> Result<()> {
    for digest in headers.get_all("docker-content-digest") {
        if digest.as_bytes() != expected.as_bytes() {
            return Err(super::corrupt("oci-response-digest-mismatch"));
        }
    }
    Ok(())
}
