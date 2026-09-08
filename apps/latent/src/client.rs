//! One channel and one RPC under a single monotonic time allowance.
#[cfg(test)]
mod tests;

use crate::{config::ResolvedConfig, error::Failure};
use prost::Message;
use std::{
    future::Future,
    sync::atomic::{AtomicBool, Ordering},
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tokio::time::{timeout_at, Instant};
use tonic::{
    metadata::{Ascii, MetadataValue},
    transport::{Channel, Endpoint},
    Request, Response, Status,
};

pub struct Session {
    channel: Channel,
    tenant: String,
    authorization: MetadataValue<Ascii>,
    deadline: Instant,
    dispatched: AtomicBool,
    maximum_response: usize,
    maximum_request: usize,
}
impl Session {
    pub async fn connect(
        config: &ResolvedConfig,
        absolute_deadline: Option<u64>,
    ) -> Result<Self, Failure> {
        let started = Instant::now();
        let mut allowance = config.rpc_timeout;
        if let Some(deadline) = absolute_deadline {
            let now = SystemTime::now().duration_since(UNIX_EPOCH).map_err(|_| {
                Failure::local("clock-unavailable", "The current time is unavailable.")
            })?;
            let remaining = Duration::from_millis(deadline)
                .checked_sub(now)
                .filter(|remaining| !remaining.is_zero())
                .ok_or_else(|| {
                    Failure::local(
                        "deadline-expired",
                        "The requested deadline has already expired.",
                    )
                })?;
            allowance = allowance.min(remaining);
        }
        let deadline = started + allowance;
        let connect_deadline = deadline.min(started + config.connect_timeout);
        let endpoint = Endpoint::from_shared(config.endpoint.clone())
            .map_err(|_| Failure::local("invalid-endpoint", "The configured endpoint is invalid."))?
            .http2_max_header_list_size(16 * 1024)
            .http2_header_table_size(4096)
            .max_frame_size(16 * 1024);
        let channel = timeout_at(connect_deadline, endpoint.connect())
            .await
            .map_err(|_| {
                Failure::transport("connect-timeout", "The connection time allowance expired.")
            })?
            .map_err(|_| {
                Failure::transport(
                    "connect-failed",
                    "The client could not connect to the node.",
                )
            })?;
        let mut authorization = MetadataValue::try_from(format!("Bearer {}", config.token))
            .map_err(|_| {
                Failure::local(
                    "invalid-credential",
                    "The configured credential is invalid.",
                )
            })?;
        authorization.set_sensitive(true);
        Ok(Self {
            channel,
            tenant: config.tenant.clone(),
            authorization,
            deadline,
            dispatched: AtomicBool::new(false),
            maximum_response: config.limits.maximum_response_bytes,
            maximum_request: config
                .limits
                .maximum_component_bytes
                .saturating_add(3 * 1024 * 1024),
        })
    }
    pub fn tenant(&self) -> &str {
        &self.tenant
    }
    pub fn channel(&self) -> Channel {
        self.channel.clone()
    }
    pub const fn max_response_bytes(&self) -> usize {
        self.maximum_response
    }
    pub const fn max_request_bytes(&self) -> usize {
        self.maximum_request
    }
    pub fn dispatched(&self) -> bool {
        self.dispatched.load(Ordering::Acquire)
    }
    pub fn request<T: Message>(&self, value: T) -> Result<Request<T>, Failure> {
        if value.encoded_len() > self.maximum_request {
            return Err(Failure::local(
                "request-limit",
                "The encoded request exceeds the configured limit.",
            ));
        }
        let remaining = self
            .deadline
            .checked_duration_since(Instant::now())
            .filter(|remaining| !remaining.is_zero())
            .ok_or_else(|| {
                Failure::transport(
                    "rpc-timeout",
                    "The RPC time allowance expired before dispatch.",
                )
            })?;
        let mut request = Request::new(value);
        request
            .metadata_mut()
            .insert("authorization", self.authorization.clone());
        request.set_timeout(remaining);
        Ok(request)
    }
    pub async fn call<T, F>(&self, future: F) -> Result<Response<T>, Failure>
    where
        F: Future<Output = Result<Response<T>, Status>>,
    {
        if Instant::now() >= self.deadline {
            return Err(Failure::transport(
                "rpc-timeout",
                "The RPC time allowance expired before dispatch.",
            ));
        }
        self.dispatched.store(true, Ordering::Release);
        match timeout_at(self.deadline, future).await {
            Ok(Ok(value)) => Ok(value),
            Ok(Err(status)) => Err(Failure::from_status(&status)),
            Err(_) => Err(Failure::protocol(
                "rpc-timeout",
                "The RPC time allowance expired after dispatch.",
            )),
        }
    }
}
