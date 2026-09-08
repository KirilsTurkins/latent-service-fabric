//! One bounded invocation, status read, or explicit cancellation.
mod bounds;
mod budget;
mod prepare;
mod response;
#[cfg(test)]
mod tests;

use latent_wire::invocation::{proto, InvocationServiceClient};

use crate::{
    args, client::Session, config::ResolvedConfig, error::Failure, operation::Operation,
    output::Outcome,
};

pub fn prepare(command: &args::Command, config: &ResolvedConfig) -> Result<Operation, Failure> {
    prepare::operation(command, config)
}

pub async fn execute(operation: Operation, session: &Session) -> Result<Outcome, Failure> {
    let mut client = InvocationServiceClient::new(session.channel())
        .max_decoding_message_size(session.max_response_bytes())
        .max_encoding_message_size(session.max_request_bytes());
    match operation {
        Operation::Invoke(request) => {
            let requested = request.activation_id.clone();
            let result = session
                .call(client.invoke(session.request(request)?))
                .await?
                .into_inner();
            response::invocation(result, requested.as_deref(), session.max_response_bytes())
        }
        Operation::Cancel(request) => {
            let id = request.activation_id.clone();
            let result = session
                .call(client.cancel(session.request(request)?))
                .await?
                .into_inner();
            response::cancellation(result, &id, session.max_response_bytes())
        }
        Operation::GetActivation(request) => {
            let id = request.activation_id.clone();
            let result = session
                .call(client.get_activation(session.request(request)?))
                .await?
                .into_inner();
            response::status(result, &id, session.max_response_bytes())
        }
        _ => Err(Failure::local(
            "invalid-operation",
            "Expected an invocation command.",
        )),
    }
}

fn invalid() -> Failure {
    Failure::local("invalid-invocation", "Invalid invocation arguments.")
}
fn protocol() -> Failure {
    Failure::protocol(
        "invalid-invocation-response",
        "The node returned an invalid invocation response.",
    )
}
