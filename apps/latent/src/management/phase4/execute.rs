use super::{invalid, projection};
use crate::{client::Session, error::Failure, output::Outcome};
use latent_rpc::{
    control::v1::{
        self as c, dispatcher_service_client::DispatcherServiceClient,
        state_service_client::StateServiceClient,
    },
    phase4::{self, Request, Response},
    transaction::v1::{self as t, transaction_service_client::TransactionServiceClient},
};

macro_rules! call {
    ($session:ident,$client:ident,$method:ident,$request:ident) => {{
        let mut client = $client::new($session.channel())
            .max_decoding_message_size(
                $session
                    .max_response_bytes()
                    .min(phase4::MAX_RESPONSE_BYTES),
            )
            .max_encoding_message_size($session.max_request_bytes().min(phase4::MAX_REQUEST_BYTES));
        Response::from(
            $session
                .call(client.$method($session.request(*$request)?))
                .await?
                .into_inner(),
        )
    }};
}
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
    Ok(match request {
        Request::InspectDispatcher(value) => {
            call!(session, DispatcherServiceClient, inspect_dispatcher, value)
        }
        Request::ControlDispatcher(value) => {
            call!(session, DispatcherServiceClient, control_dispatcher, value)
        }
        Request::GetDispatcherOperation(value) => call!(
            session,
            DispatcherServiceClient,
            get_dispatcher_operation,
            value
        ),
        Request::InspectNamespace(value) => {
            call!(session, StateServiceClient, inspect_namespace, value)
        }
        Request::MutateNamespace(value) => {
            call!(session, StateServiceClient, mutate_namespace, value)
        }
        Request::SelectEntity(value) => call!(session, StateServiceClient, select_entity, value),
        Request::MutateState(value) => call!(session, StateServiceClient, mutate_state, value),
        Request::PlanEffectMutation(value) => {
            call!(session, StateServiceClient, plan_effect_mutation, value)
        }
        Request::GetStateOperationReceipt(value) => call!(
            session,
            StateServiceClient,
            get_state_operation_receipt,
            value
        ),
        Request::InvokeCommand(value) => {
            call!(session, TransactionServiceClient, invoke_command, value)
        }
        Request::Query(value) => call!(session, TransactionServiceClient, query, value),
        Request::LookupCommand(value) => {
            call!(session, TransactionServiceClient, lookup_command, value)
        }
        Request::LookupCommit(value) => {
            call!(session, TransactionServiceClient, lookup_commit, value)
        }
        Request::GetEffect(value) => call!(session, TransactionServiceClient, get_effect, value),
        Request::ListEffectHistory(value) => call!(
            session,
            TransactionServiceClient,
            list_effect_history,
            value
        ),
        Request::CancelCommand(value) => {
            call!(session, TransactionServiceClient, cancel_command, value)
        }
    })
}
fn project_outcome(response: &Response) -> Outcome {
    let data = projection::response(response);
    let mut outcome = match response {
        Response::LookupCommand(value) => {
            command_outcome(value.command.as_ref().expect("validated command"), data)
        }
        Response::LookupCommit(value) => {
            command_outcome(value.command.as_ref().expect("validated command"), data)
        }
        Response::InvokeCommand(value) => {
            command_outcome(value.command.as_ref().expect("validated command"), data)
        }
        Response::MutateNamespace(value) => state_outcome(
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
        _ => Outcome::success(data),
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
    outcome.outcome_known = matches!(
        t::CommandOutcome::try_from(command.outcome),
        Ok(t::CommandOutcome::Committed | t::CommandOutcome::Rejected | t::CommandOutcome::Aborted)
    );
    outcome
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
