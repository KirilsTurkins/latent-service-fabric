macro_rules! call {
    ($session:ident, $client:ident, $method:ident, $request:expr) => {{
        let mut client = $client::new($session.channel())
            .max_decoding_message_size($session.max_response_bytes())
            .max_encoding_message_size($session.max_request_bytes());
        let request = $session.request($request)?;
        let response = $session.call(client.$method(request)).await?;
        crate::management::phase2::projection::checked(
            response.get_ref(),
            $session.max_response_bytes(),
        )?;
        response.into_inner()
    }};
}
mod audit;
mod deployment;
mod release;
mod rollout;
use super::invalid_input;
use crate::{client::Session, error::Failure, operation::Operation, output::Outcome};
pub(in crate::management) async fn execute(
    operation: Operation,
    session: &Session,
) -> Result<Outcome, Failure> {
    match operation {
        Operation::GetReleaseLifecycle(_)
        | Operation::LookupReleaseReceipt(_)
        | Operation::ChangeReleaseLifecycle(_)
        | Operation::RenewReleaseEvidence(_)
        | Operation::PublishRelease(_) => release::execute(operation, session).await,
        Operation::ApplyDeployment(_)
        | Operation::DeleteDeployment(_)
        | Operation::GetDeployment(_)
        | Operation::LookupDeploymentReceipt(_) => deployment::execute(operation, session).await,
        Operation::StartRollout(_)
        | Operation::ChangeRollout(_)
        | Operation::GetRollout(_)
        | Operation::ListRollouts(_)
        | Operation::LookupRolloutReceipt(_)
        | Operation::EvaluateRollout(_) => rollout::execute(operation, session).await,
        Operation::QueryAudit(request) => audit::query(request, session).await,
        _ => Err(invalid_input()),
    }
}
