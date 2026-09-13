mod client;
use super::reference::Endpoint;
use super::{exhausted, invalid, RegistryConfig, RegistryLimits, Result};
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
    client: reqwest::Client,
    auth: Option<HeaderValue>,
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
}
impl Transport {
    pub(crate) fn new(config: RegistryConfig) -> Result<Self> {
        config.limits.validate()?;
        let endpoint = Endpoint::new(&config)?;
        let client = client::build(&config, &endpoint)?;
        let auth = client::authorization(config.credentials)?;
        Ok(Self {
            client,
            auth,
            endpoint,
            limits: config.limits,
            operations: Arc::new(Semaphore::new(config.limits.max_in_flight)),
            packages: Arc::new(Semaphore::new(config.limits.max_retained_packages)),
            bytes: Arc::new(Semaphore::new(config.limits.max_retained_bytes as usize)),
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
        }
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
        self.endpoint.check_url(&url)?;
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
            .request(method, url)
            .timeout(remaining.min(self.limits.request_timeout));
        if let Some(auth) = &self.auth {
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
