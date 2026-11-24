use super::{invalid, projection};
use crate::{client::Session, error::Failure, output::Outcome};
use latent_rpc::{
    control::v1::{
        self as c, dispatcher_service_client::DispatcherServiceClient,
        state_service_client::StateServiceClient,
    },
    invocation::v1::{self as i, invoke_response},
    phase4::{self, Request, Response},
    transaction::v1::{self as t, transaction_service_client::TransactionServiceClient},
};

pub async fn execute(request: Request, session: &Session) -> Result<Outcome, Failure> {
    request.validate().map_err(|_| invalid())?;
    let association = request.association();
    let response = dispatch(request, session).await?;
    response
        .validate_association(&association)
        .map_err(|_| super::super::invalid_response())?;
    if response.encoded_len() > session.max_response_bytes() {
        return Err(super::super::invalid_response());
    }
    Ok(project_outcome(&response))
}
async fn dispatch(request: Request, session: &Session) -> Result<Response, Failure> {
    let limit = match &request {
        Request::InvokeCommand(_) | Request::Query(_) => std::time::Duration::MAX,
        _ => latent_wire::phase4::MAX_MANAGEMENT_TIMEOUT,
    };
    macro_rules! call {
        ($client:ident, $method:ident, $request:ident) => {{
            let mut client = $client::new(session.channel())
                .max_decoding_message_size(
                    session.max_response_bytes().min(phase4::MAX_RESPONSE_BYTES),
                )
                .max_encoding_message_size(
                    session.max_request_bytes().min(phase4::MAX_REQUEST_BYTES),
                );
            Response::from(
                session
                    .call(client.$method(session.request_with_timeout_limit(*$request, limit)?))
                    .await?
                    .into_inner(),
            )
        }};
    }
    Ok(match request {
        Request::InspectDispatcher(value) => {
            call!(DispatcherServiceClient, inspect_dispatcher, value)
        }
        Request::ControlDispatcher(value) => {
            call!(DispatcherServiceClient, control_dispatcher, value)
        }
        Request::GetDispatcherOperation(value) => {
            call!(DispatcherServiceClient, get_dispatcher_operation, value)
        }
        Request::InspectNamespace(value) => {
            call!(StateServiceClient, inspect_namespace, value)
        }
        Request::MutateNamespace(value) => {
            call!(StateServiceClient, mutate_namespace, value)
        }
        Request::SelectEntity(value) => {
            call!(StateServiceClient, select_entity, value)
        }
        Request::MutateState(value) => {
            call!(StateServiceClient, mutate_state, value)
        }
        Request::PlanEffectMutation(value) => {
            call!(StateServiceClient, plan_effect_mutation, value)
        }
        Request::GetStateOperationReceipt(value) => {
            call!(StateServiceClient, get_state_operation_receipt, value)
        }
        Request::InvokeCommand(value) => {
            call!(TransactionServiceClient, invoke_command, value)
        }
        Request::Query(value) => call!(TransactionServiceClient, query, value),
        Request::LookupCommand(value) => {
            call!(TransactionServiceClient, lookup_command, value)
        }
        Request::LookupCommit(value) => {
            call!(TransactionServiceClient, lookup_commit, value)
        }
        Request::GetEffect(value) => {
            call!(TransactionServiceClient, get_effect, value)
        }
        Request::ListEffectHistory(value) => {
            call!(TransactionServiceClient, list_effect_history, value)
        }
        Request::CancelCommand(value) => {
            call!(TransactionServiceClient, cancel_command, value)
        }
    })
}
pub(super) fn project_outcome(response: &Response) -> Outcome {
    let data = projection::response(response);
    let mut outcome = match response {
        Response::LookupCommand(value) => {
            command_outcome(value.command.as_ref().expect("validated command"), data)
        }
        Response::LookupCommit(value) => {
            command_outcome(value.command.as_ref().expect("validated command"), data)
        }
        Response::InvokeCommand(value) => {
            let mut outcome = invocation_outcome(
                value.invocation.as_ref().expect("validated invocation"),
                data,
            );
            outcome.outcome_known =
                command_is_known(value.command.as_ref().expect("validated command"));
            outcome
        }
        Response::Query(value) => invocation_outcome(
            value.invocation.as_ref().expect("validated invocation"),
            data,
        ),
        Response::MutateNamespace(value) => state_outcome(
            value
                .receipt
                .as_ref()
                .expect("validated receipt")
                .disposition,
            data,
        ),
        Response::ControlDispatcher(value) => state_outcome(
            value
                .receipt
                .as_ref()
                .expect("validated receipt")
                .disposition,
            data,
        ),
        Response::GetDispatcherOperation(value) => state_outcome(
            value
                .receipt
                .as_ref()
                .expect("validated receipt")
                .disposition,
            data,
        ),
        Response::MutateState(value) => state_outcome(
            value
                .receipt
                .as_ref()
                .expect("validated receipt")
                .disposition,
            data,
        ),
        Response::GetStateOperationReceipt(value) => state_outcome(
            value.namespace_receipt.as_ref().map_or_else(
                || {
                    value
                        .receipt
                        .as_ref()
                        .expect("validated receipt")
                        .disposition
                },
                |v| v.disposition,
            ),
            data,
        ),
        Response::InspectDispatcher(_)
        | Response::InspectNamespace(_)
        | Response::SelectEntity(_)
        | Response::PlanEffectMutation(_)
        | Response::GetEffect(_)
        | Response::ListEffectHistory(_)
        | Response::CancelCommand(_) => Outcome::success(data),
    };
    if let Response::CancelCommand(value) = response {
        outcome.outcome_known = matches!(
            t::CommandCancelDisposition::try_from(value.disposition),
            Ok(t::CommandCancelDisposition::AlreadyCommitted
                | t::CommandCancelDisposition::AlreadyTerminal)
        );
    }
    outcome
}
pub(super) fn command_outcome(command: &t::CommandInspection, data: serde_json::Value) -> Outcome {
    let mut outcome = if command.outcome == t::CommandOutcome::Rejected as i32 {
        Outcome::domain_error(data)
    } else {
        Outcome::success(data)
    };
    outcome.outcome_known = command_is_known(command);
    outcome
}

fn command_is_known(command: &t::CommandInspection) -> bool {
    matches!(
        t::CommandOutcome::try_from(command.outcome),
        Ok(t::CommandOutcome::Committed | t::CommandOutcome::Rejected | t::CommandOutcome::Aborted)
    )
}

fn invocation_outcome(invocation: &i::InvokeResponse, data: serde_json::Value) -> Outcome {
    match invocation.result.as_ref().expect("validated result") {
        invoke_response::Result::Success(_) => Outcome::success(data),
        invoke_response::Result::DeclaredError(_) => Outcome::domain_error(data),
        invoke_response::Result::PlatformFailure(error) => {
            let error = latent_wire::invocation::platform_error_from_proto(error.clone())
                .expect("validated platform error");
            Outcome::platform_failure(data, &error)
        }
    }
}
pub(super) fn state_outcome(disposition: i32, data: serde_json::Value) -> Outcome {
    let disposition =
        c::StateOperationDisposition::try_from(disposition).expect("validated disposition");
    let mut outcome = if matches!(
        disposition,
        c::StateOperationDisposition::Conflict | c::StateOperationDisposition::Rejected
    ) {
        Outcome::domain_error(data)
    } else {
        Outcome::success(data)
    };
    outcome.outcome_known = matches!(
        disposition,
        c::StateOperationDisposition::Committed
            | c::StateOperationDisposition::Conflict
            | c::StateOperationDisposition::Rejected
    );
    outcome
}
