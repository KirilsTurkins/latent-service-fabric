mod channel;
mod config;
mod error;
mod ownership;
mod profile;

#[cfg(test)]
mod tests;

pub use config::{ClientConfig, ClientLimits};
pub use error::{
    AuditAcknowledgement, FailureKind, RecoveryIdentity, RpcFailure, UnsupportedWireValue,
};
pub use ownership::ClientUsage;

use channel::CallChannel;
use ownership::Resources;
use prost::Message;
use std::{future::Future, sync::Arc};
use tokio::{
    sync::Mutex,
    time::{timeout_at, Instant},
};
use tonic::{
    metadata::{Ascii, MetadataValue},
    transport::Channel,
    Request, Response, Status,
};

#[derive(Clone)]
pub struct RpcClient {
    inner: Arc<Inner>,
}

struct Inner {
    endpoint: std::net::SocketAddr,
    tenant: latent_core::TenantId,
    credential: MetadataValue<Ascii>,
    connection: Mutex<Connection>,
    resources: Arc<Resources>,
}

enum Connection {
    New,
    Ready(Channel),
    Failed,
}

#[derive(Clone, Debug)]
struct RpcResponse<Value> {
    value: Value,
    audit: Option<AuditAcknowledgement>,
}

impl RpcClient {
    pub fn new(config: ClientConfig) -> Result<Self, RpcFailure> {
        let credential = config.validate()?;
        Ok(Self {
            inner: Arc::new(Inner {
                endpoint: config.endpoint,
                tenant: config.tenant,
                credential,
                connection: Mutex::new(Connection::New),
                resources: Resources::new(config.limits),
            }),
        })
    }

    #[must_use]
    pub fn limits(&self) -> ClientLimits {
        self.inner.resources.limits
    }

    #[must_use]
    pub fn usage(&self) -> ClientUsage {
        self.inner.resources.usage()
    }

    pub async fn shutdown(&self, deadline: Instant) -> Result<(), RpcFailure> {
        self.inner.resources.close();
        let mut connection = timeout_at(deadline, self.inner.connection.lock())
            .await
            .map_err(|_| RpcFailure::local(FailureKind::Deadline))?;
        *connection = Connection::Failed;
        drop(connection);
        loop {
            let retired = self.inner.resources.retired.notified();
            tokio::pin!(retired);
            retired.as_mut().enable();
            let usage = self.usage();
            if usage.active_calls == 0 && usage.executor_tasks == 0 && usage.sockets == 0 {
                return Ok(());
            }
            timeout_at(deadline, retired)
                .await
                .map_err(|_| RpcFailure::local(FailureKind::Deadline))?;
        }
    }

    async fn connection(&self, deadline: Instant) -> Result<Channel, RpcFailure> {
        let mut connection = timeout_at(deadline, self.inner.connection.lock())
            .await
            .map_err(|_| RpcFailure::local(FailureKind::Deadline))?;
        if *self.inner.resources.closed.borrow() {
            return Err(RpcFailure::local(FailureKind::Closed));
        }
        match &*connection {
            Connection::Ready(channel) => return Ok(channel.clone()),
            Connection::Failed => return Err(RpcFailure::local(FailureKind::Connection)),
            Connection::New => {}
        }
        *connection = Connection::Failed;
        let deadline = deadline.min(Instant::now() + self.limits().connect_timeout);
        let channel = channel::connect(
            self.inner.endpoint,
            Arc::clone(&self.inner.resources),
            deadline,
        )
        .await?;
        *connection = Connection::Ready(channel.clone());
        Ok(channel)
    }

    async fn unary<Input, Output, Call, Reply>(
        &self,
        input: Input,
        deadline: Instant,
        recovery: RecoveryIdentity,
        call: Call,
    ) -> Result<RpcResponse<Output>, RpcFailure>
    where
        Input: Message + Send,
        Output: Message + Send,
        Call: FnOnce(CallChannel, Request<Input>) -> Reply + Send,
        Reply: Future<Output = Result<Response<Output>, Status>> + Send,
    {
        let deadline = deadline.min(Instant::now() + self.limits().rpc_timeout);
        if deadline <= Instant::now() {
            return Err(RpcFailure::local(FailureKind::Deadline).context(&recovery, false));
        }
        let lease = self
            .inner
            .resources
            .begin(input.encoded_len())
            .map_err(|error| error.context(&recovery, false))?;
        let mut closed = self.inner.resources.closed.subscribe();
        let channel = tokio::select! {
            biased;
            _ = closed.changed() => Err(RpcFailure::local(FailureKind::Closed)),
            result = self.connection(deadline) => result,
        }
        .map_err(|error| error.context(&recovery, false))?;
        let mut request = Request::new(input);
        request
            .metadata_mut()
            .insert("authorization", self.inner.credential.clone());
        let remaining = deadline
            .checked_duration_since(Instant::now())
            .filter(|remaining| !remaining.is_zero())
            .ok_or_else(|| RpcFailure::local(FailureKind::Deadline).context(&recovery, false))?;
        request.set_timeout(remaining);
        let future = call(CallChannel { channel, lease }, request);
        let response = tokio::select! {
            biased;
            _ = closed.changed() => Err(RpcFailure::local(FailureKind::Closed)),
            result = timeout_at(deadline, future) => match result {
                Ok(Ok(response)) => Ok(response),
                Ok(Err(_)) if Instant::now() >= deadline => Err(RpcFailure::local(FailureKind::Deadline)),
                Ok(Err(status)) => Err(RpcFailure::status(&status)),
                Err(_) => Err(RpcFailure::local(FailureKind::Deadline)),
            },
        }
        .map_err(|error| error.context(&recovery, true))?;
        if response.get_ref().encoded_len() > self.limits().maximum_response_bytes {
            return Err(RpcFailure::local(FailureKind::InvalidResponse).context(&recovery, true));
        }
        let audit =
            error::audit(response.metadata()).map_err(|error| error.context(&recovery, true))?;
        Ok(RpcResponse {
            value: response.into_inner(),
            audit,
        })
    }
}

impl Drop for Inner {
    fn drop(&mut self) {
        self.resources.close();
    }
}
