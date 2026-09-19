mod conversions;
mod metadata;
mod requests;
mod responses;

#[cfg(test)]
mod vectors;

use super::{
    channel::CallChannel, AuditAcknowledgement, FailureKind, RecoveryIdentity, RpcClient,
    RpcFailure,
};
use crate::management as model;
use latent_rpc::{control::v1 as control, invocation::v1 as invocation};
use prost::Message;
use requests::Context;
use responses::ResponseProfile;
use std::future::Future;
use tokio::time::Instant;
use tonic::{Request, Response, Status};

macro_rules! operation {
    ($method:ident, $request:ident, $response:ident, $module:ident, $service_module:ident, $service:ident) => {
        fn $method(
            &self,
            request: model::$request,
            options: model::CallOptions,
        ) -> model::ClientFuture<'_, model::$response> {
            let started = Instant::now();
            Box::pin(async move {
                let context = requests::context(&request, self, started, &options)
                    .map_err(model::ClientFailure::from)?;
                let maximum_request = context.maximum_request;
                let maximum_response = context.maximum_response;
                let request: $module::$request = request.into();
                self.profile_call(request, context, move |channel, request| async move {
                    $module::$service_module::$service::new(channel)
                        .max_encoding_message_size(maximum_request)
                        .max_decoding_message_size(maximum_response)
                        .$method(request)
                        .await
                })
                .await
            })
        }
    };
}

impl model::ClientProfile for RpcClient {
    operation!(
        invoke,
        InvokeRequest,
        InvokeResponse,
        invocation,
        invocation_service_client,
        InvocationServiceClient
    );
    operation!(
        cancel,
        CancelRequest,
        CancelResponse,
        invocation,
        invocation_service_client,
        InvocationServiceClient
    );
    operation!(
        get_activation,
        GetActivationRequest,
        ActivationStatus,
        invocation,
        invocation_service_client,
        InvocationServiceClient
    );
    operation!(
        get_policy,
        GetPolicyRequest,
        GetPolicyResponse,
        control,
        policy_service_client,
        PolicyServiceClient
    );
    operation!(
        list_policies,
        ListPoliciesRequest,
        ListPoliciesResponse,
        control,
        policy_service_client,
        PolicyServiceClient
    );
    operation!(
        list_capabilities,
        ListCapabilitiesRequest,
        ListCapabilitiesResponse,
        control,
        capability_service_client,
        CapabilityServiceClient
    );
    operation!(
        apply_policy,
        ApplyPolicyRequest,
        ApplyPolicyResponse,
        control,
        policy_service_client,
        PolicyServiceClient
    );
    operation!(
        get_policy_operation,
        GetPolicyOperationRequest,
        GetPolicyOperationResponse,
        control,
        policy_service_client,
        PolicyServiceClient
    );
}

impl RpcClient {
    async fn profile_call<Input, Wire, Output, Call, Reply>(
        &self,
        request: Input,
        context: Context,
        call: Call,
    ) -> Result<model::ClientResponse<Output>, model::ClientFailure>
    where
        Input: Message + Send,
        Wire: Message + ResponseProfile + Send,
        Output: From<Wire>,
        Call: FnOnce(CallChannel, Request<Input>) -> Reply + Send,
        Reply: Future<Output = Result<Response<Wire>, Status>> + Send,
    {
        if request.encoded_len() > context.maximum_request {
            return Err(RpcFailure::local(FailureKind::Capacity)
                .context(&context.recovery, false)
                .into());
        }
        let mut received_identity = context.recovery.clone();
        let mut checked = None;
        let reply = self
            .unary(
                request,
                context.deadline,
                context.recovery.clone(),
                |channel, request| async {
                    let reply = call(channel, request).await?;
                    let value = reply.get_ref();
                    if value.encoded_len() <= context.maximum_response {
                        if received_identity.activation_id.is_none() {
                            received_identity.activation_id = value
                                .activation_id()
                                .filter(|identity| responses::valid_id(identity))
                                .map(Into::into);
                        }
                        checked = Some(value.validate(&context, &self.inner.tenant.0));
                    }
                    Ok(reply)
                },
            )
            .await;
        let reply = match reply {
            Ok(reply) => reply,
            Err(mut failure) => {
                failure.recovery = received_identity;
                if let Some(Ok(known)) = checked {
                    failure.outcome_known = known;
                }
                if context.recovery_read && failure.grpc_code == Some(5) {
                    failure.outcome_known = false;
                }
                return Err(failure.into());
            }
        };
        let known = checked
            .unwrap_or_else(|| Err(RpcFailure::local(FailureKind::InvalidResponse)))
            .map_err(|failure| {
                model::ClientFailure::from(
                    failure.received(&received_identity, reply.audit.as_ref()),
                )
            })?;
        let (audit_ack, audit_status) = metadata::audit(reply.audit);
        let response = model::ClientResponse {
            value: reply.value.into(),
            metadata: model::ResponseMetadata {
                identity: received_identity.into(),
                outcome: if known {
                    model::OutcomeKnowledge::OBSERVED
                } else {
                    model::OutcomeKnowledge::UNKNOWN
                },
                audit_ack,
                audit_status,
            },
        };
        if Instant::now() >= context.deadline {
            return Err(model::ClientFailure {
                category: model::FailureCategory::DEADLINE,
                message: "bounded RPC failure: Deadline".into(),
                dispatched: true,
                outcome: response.metadata.outcome,
                identity: response.metadata.identity,
                audit_ack: response.metadata.audit_ack,
                audit_status: response.metadata.audit_status,
                ..Default::default()
            });
        }
        Ok(response)
    }
}
