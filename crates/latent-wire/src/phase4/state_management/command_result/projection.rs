use super::{contract, invalid, missing, PlatformError};
use latent_commit::atomic::{CommandRecord, DurableResult, Outcome};
use latent_rpc::{invocation::v1 as i, transaction::v1 as t};

#[cfg(test)]
mod tests;

pub(super) fn response(
    request: &contract::Request,
    record: &CommandRecord,
    result: Option<&DurableResult>,
) -> Result<contract::Response, PlatformError> {
    let payload = matches!(request, contract::Request::LookupCommand(_));
    let mut command = crate::phase4::local_transaction::projection::inspection(
        record,
        result.filter(|_| payload),
        None,
    );
    if record.outcome() == Outcome::Pending {
        command.outcome = t::CommandOutcome::RecoveryRequired as i32;
    }
    match request {
        contract::Request::LookupCommand(_) => {
            command.retained_result = result
                .and_then(|result| result.value().map(|value| (result, value)))
                .map(|(result, value)| retained(record, result, value))
                .transpose()?;
            Ok(t::LookupCommandResponse {
                command: Some(command),
            }
            .into())
        }
        contract::Request::LookupCommit(value) => {
            if record.outcome() != Outcome::Committed
                || record.disposition_id().hex() != value.receipt_id
            {
                return Err(missing());
            }
            Ok(t::LookupCommitResponse {
                command: Some(command),
            }
            .into())
        }
        _ => Err(invalid()),
    }
}
fn retained(
    record: &CommandRecord,
    result: &DurableResult,
    value: &latent_core::transaction_contract::Value,
) -> Result<t::command_inspection::RetainedResult, PlatformError> {
    use t::command_inspection::RetainedResult as R;
    Ok(match result.outcome() {
        Outcome::Committed => R::Success(i::Success {
            payload: value.bytes.clone(),
            media_type: value.media_type.clone(),
            metadata: value.metadata.iter().cloned().collect(),
            committed_state_version: Some(super::super::response::hex(
                result.committed_view_token(),
            )),
            effect_ids: record.effect_ids().iter().map(|id| id.hex()).collect(),
        }),
        Outcome::Rejected => R::BusinessRejection(i::DeclaredError {
            code: result.code().ok_or_else(invalid)?.into(),
            message: String::new(),
            payload: value.bytes.clone(),
            media_type: value.media_type.clone(),
            metadata: value.metadata.iter().cloned().collect(),
        }),
        Outcome::Aborted => R::TechnicalFailure(i::PlatformError {
            code: crate::phase4::local_transaction::projection::retained_abort_code(result)
                .wire_code()
                .into(),
            message: "transaction result unavailable".into(),
            retryable: false,
            ..Default::default()
        }),
        Outcome::Pending => return Err(invalid()),
    })
}
