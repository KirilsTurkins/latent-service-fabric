mod convert;
mod status;

use super::{FailureKind, RecoveryIdentity, RpcClient, RpcFailure, RpcResponse};
use crate::{
    ActivationStatus, CancelResponse, ClientTransportError, InvocationOutcome, InvokeRequest,
    LatentClient,
};
use latent_core::{ActivationId, BoxFuture};
use latent_rpc::invocation::v1::{
    self as proto, invocation_service_client::InvocationServiceClient,
};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::time::Instant;

impl RpcClient {
    pub async fn invoke_until(
        &self,
        request: InvokeRequest,
        deadline: Instant,
    ) -> Result<RpcResponse<InvocationOutcome>, RpcFailure> {
        let recovery = RecoveryIdentity {
            activation_id: request
                .activation_id
                .as_ref()
                .filter(|value| value.0.len() <= 256)
                .map(|value| value.0.clone()),
            operation_id: None,
        };
        convert::request_bounds(&request, self.limits().maximum_request_bytes)
            .map_err(|error| error.context(&recovery, false))?;
        if request.target.tenant != self.inner.tenant {
            return Err(RpcFailure::local(FailureKind::InvalidRequest).context(&recovery, false));
        }
        let mut deadline = deadline.min(Instant::now() + self.limits().rpc_timeout);
        if let Some(wall_deadline) = request.options.deadline_unix_millis {
            let now = SystemTime::now().duration_since(UNIX_EPOCH).map_err(|_| {
                RpcFailure::local(FailureKind::InvalidRequest).context(&recovery, false)
            })?;
            let remaining = Duration::from_millis(wall_deadline)
                .checked_sub(now)
                .filter(|remaining| !remaining.is_zero())
                .ok_or_else(|| {
                    RpcFailure::local(FailureKind::Deadline).context(&recovery, false)
                })?;
            deadline = deadline.min(Instant::now() + remaining.min(self.limits().rpc_timeout));
        }
        let limits = self.limits();
        let reply = self
            .unary(
                convert::request(request),
                deadline,
                recovery.clone(),
                move |channel, request| async move {
                    InvocationServiceClient::new(channel)
                        .max_decoding_message_size(limits.maximum_response_bytes)
                        .max_encoding_message_size(limits.maximum_request_bytes)
                        .invoke(request)
                        .await
                },
            )
            .await?;
        if recovery
            .activation_id
            .as_ref()
            .is_some_and(|id| id != &reply.value.activation_id)
        {
            return Err(RpcFailure::local(FailureKind::InvalidResponse)
                .received(&recovery, reply.audit.as_ref()));
        }
        let value = convert::outcome(reply.value)
            .map_err(|error| error.received(&recovery, reply.audit.as_ref()))?;
        Ok(RpcResponse {
            value,
            audit: reply.audit,
        })
    }

    pub async fn cancel_until(
        &self,
        activation_id: &ActivationId,
        reason: &str,
        deadline: Instant,
    ) -> Result<RpcResponse<CancelResponse>, RpcFailure> {
        bounded_id(&activation_id.0)?;
        let recovery = RecoveryIdentity {
            activation_id: Some(activation_id.0.clone()),
            operation_id: None,
        };
        if reason.len() > 1024 {
            return Err(RpcFailure::local(FailureKind::InvalidRequest).context(&recovery, false));
        }
        let limits = self.limits();
        let reply = self
            .unary(
                proto::CancelRequest {
                    activation_id: activation_id.0.clone(),
                    reason: reason.into(),
                },
                deadline,
                recovery.clone(),
                move |channel, request| async move {
                    InvocationServiceClient::new(channel)
                        .max_decoding_message_size(limits.maximum_response_bytes)
                        .max_encoding_message_size(limits.maximum_request_bytes)
                        .cancel(request)
                        .await
                },
            )
            .await?;
        let value = match (reply.value.disposition, reply.value.terminal_state) {
            (1, None) => CancelResponse::Accepted,
            (2, Some(state)) => CancelResponse::AlreadyTerminal(
                status::terminal(&state)
                    .map_err(|error| error.received(&recovery, reply.audit.as_ref()))?,
            ),
            (3, None) => CancelResponse::NotFound,
            _ => {
                return Err(RpcFailure::local(FailureKind::InvalidResponse)
                    .received(&recovery, reply.audit.as_ref()));
            }
        };
        Ok(RpcResponse {
            value,
            audit: reply.audit,
        })
    }

    pub async fn get_activation_until(
        &self,
        activation_id: &ActivationId,
        deadline: Instant,
    ) -> Result<RpcResponse<ActivationStatus>, RpcFailure> {
        bounded_id(&activation_id.0)?;
        let recovery = RecoveryIdentity {
            activation_id: Some(activation_id.0.clone()),
            operation_id: None,
        };
        let limits = self.limits();
        let reply = self
            .unary(
                proto::GetActivationRequest {
                    activation_id: activation_id.0.clone(),
                },
                deadline,
                recovery.clone(),
                move |channel, request| async move {
                    InvocationServiceClient::new(channel)
                        .max_decoding_message_size(limits.maximum_response_bytes)
                        .max_encoding_message_size(limits.maximum_request_bytes)
                        .get_activation(request)
                        .await
                },
            )
            .await?;
        if reply.value.activation_id != activation_id.0 {
            return Err(RpcFailure::local(FailureKind::InvalidResponse)
                .received(&recovery, reply.audit.as_ref()));
        }
        let value = status::convert(reply.value)
            .map_err(|error| error.received(&recovery, reply.audit.as_ref()))?;
        Ok(RpcResponse {
            value,
            audit: reply.audit,
        })
    }
}

impl LatentClient for RpcClient {
    fn invoke(
        &self,
        request: InvokeRequest,
    ) -> BoxFuture<'_, Result<InvocationOutcome, ClientTransportError>> {
        Box::pin(async move {
            self.invoke_until(request, Instant::now() + self.limits().rpc_timeout)
                .await
                .map(|response| response.value)
                .map_err(Into::into)
        })
    }
    fn cancel<'a>(
        &'a self,
        activation_id: &'a ActivationId,
        reason: &'a str,
    ) -> BoxFuture<'a, Result<CancelResponse, ClientTransportError>> {
        Box::pin(async move {
            self.cancel_until(
                activation_id,
                reason,
                Instant::now() + self.limits().rpc_timeout,
            )
            .await
            .map(|response| response.value)
            .map_err(Into::into)
        })
    }
    fn get_activation<'a>(
        &'a self,
        activation_id: &'a ActivationId,
    ) -> BoxFuture<'a, Result<ActivationStatus, ClientTransportError>> {
        Box::pin(async move {
            self.get_activation_until(activation_id, Instant::now() + self.limits().rpc_timeout)
                .await
                .map(|response| response.value)
                .map_err(Into::into)
        })
    }
}

pub(super) fn bounded_id(value: &str) -> Result<(), RpcFailure> {
    if value.len() > 256 {
        return Err(RpcFailure::local(FailureKind::InvalidRequest));
    }
    Ok(())
}
