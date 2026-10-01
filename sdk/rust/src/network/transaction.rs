//! Additive Phase 4 operations on the stateless client's existing owner/channel.

mod codec;
mod conversions;
mod model_shapes;
mod requests;
mod responses;
mod wire_schemas;

#[cfg(test)]
mod test_peer;
#[cfg(test)]
mod tests;

use super::{channel::CallChannel, profile::response_audit, FailureKind, RpcClient, RpcFailure};
use crate::{management, transaction as model};
use codec::{BoundedCodec, Schema};
use latent_rpc::{control::v1 as control, phase4, transaction::v1 as transaction};
use model_shapes::ModelShape;
use prost::Message;
use requests::Context;
use responses::NativeReply;
use tokio::time::Instant;
use tonic::{Request, Response, Status};

// The fixed original call lease covers the graph, preserved preconditions and
// durable observation even when HTTP/2 cancellation outlives the caller future.
const RETAINED_CONTEXT_BYTES: usize = 384 * 1024;

macro_rules! operation {
    ($method:ident, $variant:ident, $request:ident, $response:ident, $module:ident, $service:literal, $schema:ident) => {
        fn $method(
            &self,
            request: model::$request,
            options: management::CallOptions,
        ) -> model::ClientFuture<'_, model::$response> {
            let started = Instant::now();
            Box::pin(async move {
                request.validate_shape().map_err(|error| {
                    requests::local_failure(error, model::RecoveryIdentity::default())
                })?;
                let wire: $module::$request = request.try_into().map_err(|error| {
                    requests::local_failure(error, model::RecoveryIdentity::default())
                })?;
                let native = phase4::Request::$variant(Box::new(wire));
                let context = requests::prepare(&native, self, started, &options)?;
                let phase4::Request::$variant(wire) = native else {
                    unreachable!()
                };
                self.transaction_call::<$module::$request, $module::$response, model::$response>(
                    *wire,
                    context,
                    &wire_schemas::$schema,
                    concat!($service, "/", stringify!($variant)),
                )
                .await
            })
        }
    };
}

impl model::TransactionClient for RpcClient {
    operation!(
        invoke_command,
        InvokeCommand,
        InvokeCommandRequest,
        InvokeCommandResponse,
        transaction,
        "/latent.transaction.v1.TransactionService",
        LATENT_TRANSACTION_V1_INVOKECOMMANDRESPONSE
    );
    operation!(
        query,
        Query,
        QueryRequest,
        QueryResponse,
        transaction,
        "/latent.transaction.v1.TransactionService",
        LATENT_TRANSACTION_V1_QUERYRESPONSE
    );
    operation!(
        lookup_command,
        LookupCommand,
        LookupCommandRequest,
        LookupCommandResponse,
        transaction,
        "/latent.transaction.v1.TransactionService",
        LATENT_TRANSACTION_V1_LOOKUPCOMMANDRESPONSE
    );
    operation!(
        lookup_commit,
        LookupCommit,
        LookupCommitRequest,
        LookupCommitResponse,
        transaction,
        "/latent.transaction.v1.TransactionService",
        LATENT_TRANSACTION_V1_LOOKUPCOMMITRESPONSE
    );
    operation!(
        get_effect,
        GetEffect,
        GetEffectRequest,
        GetEffectResponse,
        transaction,
        "/latent.transaction.v1.TransactionService",
        LATENT_TRANSACTION_V1_GETEFFECTRESPONSE
    );
    operation!(
        list_effect_history,
        ListEffectHistory,
        ListEffectHistoryRequest,
        ListEffectHistoryResponse,
        transaction,
        "/latent.transaction.v1.TransactionService",
        LATENT_TRANSACTION_V1_LISTEFFECTHISTORYRESPONSE
    );
    operation!(
        cancel_command,
        CancelCommand,
        CancelCommandRequest,
        CancelCommandResponse,
        transaction,
        "/latent.transaction.v1.TransactionService",
        LATENT_TRANSACTION_V1_CANCELCOMMANDRESPONSE
    );
    operation!(
        mutate_namespace,
        MutateNamespace,
        MutateNamespaceRequest,
        MutateNamespaceResponse,
        control,
        "/latent.control.v1.StateService",
        LATENT_CONTROL_V1_MUTATENAMESPACERESPONSE
    );
    operation!(
        inspect_namespace,
        InspectNamespace,
        InspectNamespaceRequest,
        InspectNamespaceResponse,
        control,
        "/latent.control.v1.StateService",
        LATENT_CONTROL_V1_INSPECTNAMESPACERESPONSE
    );
    operation!(
        select_entity,
        SelectEntity,
        SelectEntityRequest,
        SelectEntityResponse,
        control,
        "/latent.control.v1.StateService",
        LATENT_CONTROL_V1_SELECTENTITYRESPONSE
    );
    operation!(
        mutate_state,
        MutateState,
        MutateStateRequest,
        MutateStateResponse,
        control,
        "/latent.control.v1.StateService",
        LATENT_CONTROL_V1_MUTATESTATERESPONSE
    );
    operation!(
        plan_effect_mutation,
        PlanEffectMutation,
        PlanEffectMutationRequest,
        PlanEffectMutationResponse,
        control,
        "/latent.control.v1.StateService",
        LATENT_CONTROL_V1_PLANEFFECTMUTATIONRESPONSE
    );
    operation!(
        get_state_operation_receipt,
        GetStateOperationReceipt,
        GetStateOperationReceiptRequest,
        GetStateOperationReceiptResponse,
        control,
        "/latent.control.v1.StateService",
        LATENT_CONTROL_V1_GETSTATEOPERATIONRECEIPTRESPONSE
    );
    operation!(
        inspect_dispatcher,
        InspectDispatcher,
        InspectDispatcherRequest,
        InspectDispatcherResponse,
        control,
        "/latent.control.v1.DispatcherService",
        LATENT_CONTROL_V1_INSPECTDISPATCHERRESPONSE
    );
    operation!(
        control_dispatcher,
        ControlDispatcher,
        ControlDispatcherRequest,
        ControlDispatcherResponse,
        control,
        "/latent.control.v1.DispatcherService",
        LATENT_CONTROL_V1_CONTROLDISPATCHERRESPONSE
    );
    operation!(
        get_dispatcher_operation,
        GetDispatcherOperation,
        GetDispatcherOperationRequest,
        GetDispatcherOperationResponse,
        control,
        "/latent.control.v1.DispatcherService",
        LATENT_CONTROL_V1_GETDISPATCHEROPERATIONRESPONSE
    );
}

async fn unary<Input, Wire>(
    channel: CallChannel,
    request: Request<Input>,
    context: &Context,
    schema: &'static Schema,
    path: &'static str,
) -> Result<Response<Wire>, Status>
where
    Input: Message + Send + 'static,
    Wire: Message + Default + Send + 'static,
{
    let mut client = tonic::client::Grpc::new(channel)
        .max_encoding_message_size(context.maximum_request)
        .max_decoding_message_size(context.maximum_response);
    client
        .ready()
        .await
        .map_err(|_| Status::unavailable("bounded channel unavailable"))?;
    client
        .unary(
            request,
            http::uri::PathAndQuery::from_static(path),
            BoundedCodec::<Input, Wire>::new(schema, context.maximum_response),
        )
        .await
}

impl RpcClient {
    async fn transaction_call<Input, Wire, Output>(
        &self,
        request: Input,
        context: Context,
        schema: &'static Schema,
        path: &'static str,
    ) -> Result<model::ClientResponse<Output>, model::ClientFailure>
    where
        Input: Message + Send + 'static,
        Wire: Message + NativeReply + Default + Send + 'static,
        Output: From<Wire>,
    {
        let mut checked = None;
        let mut observed = None;
        let mut unsupported_audit = None;
        let mut identity = context.identity.clone();
        let reply = self
            .unary_with_reservation(
                request,
                context.deadline,
                context.transport_identity(),
                codec::GRAPH_BYTES + RETAINED_CONTEXT_BYTES,
                |channel, request| async {
                    let reply = unary::<Input, Wire>(channel, request, &context, schema, path)
                        .await
                        .map_err(|status| {
                            if !status.details().is_empty()
                                && codec::preflight(
                                    &wire_schemas::LATENT_CONTROL_V1_PLATFORMERROR,
                                    status.details(),
                                    8192,
                                )
                                .is_err()
                            {
                                Status::data_loss("invalid bounded platform details")
                            } else {
                                status
                            }
                        })?;
                    let (metadata, value, extensions) = reply.into_parts();
                    let (value, validation, observation, bad_audit) =
                        value.check(&context.association);
                    checked = Some(validation);
                    unsupported_audit = bad_audit;
                    // Observation is produced only after the complete associated
                    // durable record validates, before its independent audit value.
                    responses::extend_identity(&mut identity, observation.as_ref());
                    observed = observation;
                    Ok(Response::from_parts(metadata, value, extensions))
                },
            )
            .await;
        let reply = match reply {
            Ok(reply) => reply,
            Err(mut error) => {
                // A gRPC status/cancellation describes transport, never durable
                // business abort. Only a validated record supplies that proof.
                error.outcome_known = observed.as_ref().is_some_and(responses::known);
                if error.grpc_code == Some(tonic::Code::DataLoss as i32) {
                    error.kind = FailureKind::InvalidResponse;
                }
                return Err(model::ClientFailure {
                    transport: Box::new(error.into()),
                    identity: Box::new(identity),
                    observed,
                });
            }
        };
        if checked != Some(Ok(())) {
            return Err(responses::invalid_failure(
                &context,
                reply.audit.as_ref(),
                unsupported_audit,
                identity,
                observed,
            ));
        }
        let (audit_ack, audit_status, audit_attempt_sequence) = response_audit(reply.audit);
        let known = observed.as_ref().is_some_and(responses::known);
        let metadata = management::ResponseMetadata {
            identity: context.transport_identity().into(),
            outcome: if known {
                management::OutcomeKnowledge::OBSERVED
            } else {
                management::OutcomeKnowledge::UNKNOWN
            },
            audit_ack,
            audit_status,
            audit_attempt_sequence,
        };
        if Instant::now() >= context.deadline {
            return Err(model::ClientFailure {
                transport: Box::new(management::ClientFailure {
                    category: management::FailureCategory::DEADLINE,
                    message: "bounded RPC failure: Deadline".into(),
                    dispatched: true,
                    outcome: metadata.outcome,
                    identity: metadata.identity,
                    audit_ack: metadata.audit_ack,
                    audit_status: metadata.audit_status,
                    audit_attempt_sequence: metadata.audit_attempt_sequence,
                    ..Default::default()
                }),
                identity: Box::new(identity),
                observed,
            });
        }
        Ok(model::ClientResponse {
            value: reply.value.into(),
            metadata: model::ResponseMetadata {
                transport: metadata,
                identity,
            },
        })
    }
}
