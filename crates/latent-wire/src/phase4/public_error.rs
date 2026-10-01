//! Retained technical failures never replay private engine/provider diagnostics.
use crate::invocation::{sanitize_platform_error, InvocationLimits};
use latent_rpc::{invocation::v1 as i, phase4::Response, transaction::v1 as t};
use tonic::Status;

pub(super) fn sanitize(response: &mut Response, limits: &InvocationLimits) -> Result<(), Status> {
    let command = match response {
        Response::LookupCommand(value) => value.command.as_mut(),
        Response::LookupCommit(value) => value.command.as_mut(),
        Response::InvokeCommand(value) => {
            invocation(value.invocation.as_mut(), limits)?;
            value.command.as_mut()
        }
        Response::CancelCommand(value) => value.command.as_mut(),
        Response::Query(value) => {
            invocation(value.invocation.as_mut(), limits)?;
            None
        }
        _ => None,
    };
    if let Some(command) = command {
        command.retained_result = match command.retained_result.take() {
            Some(t::command_inspection::RetainedResult::TechnicalFailure(value)) => Some(
                t::command_inspection::RetainedResult::TechnicalFailure(clean(value, limits)?),
            ),
            original => original,
        };
        if let Some(value) = command.cleanup_failure.take() {
            command.cleanup_failure = Some(clean(value, limits)?);
        }
    }
    Ok(())
}
fn invocation(
    value: Option<&mut i::InvokeResponse>,
    limits: &InvocationLimits,
) -> Result<(), Status> {
    if let Some(value) = value {
        value.result = match value.result.take() {
            Some(i::invoke_response::Result::PlatformFailure(error)) => Some(
                i::invoke_response::Result::PlatformFailure(clean(error, limits)?),
            ),
            original => original,
        };
    }
    Ok(())
}
fn clean(value: i::PlatformError, limits: &InvocationLimits) -> Result<i::PlatformError, Status> {
    sanitize_platform_error(value, limits)
        .map_err(|()| Status::internal("invalid Phase 4 platform failure"))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn technical_cleanup_diagnostics_are_redacted_without_changing_durable_outcome() {
        let mut response = Response::from(t::LookupCommandResponse {
            command: Some(t::CommandInspection {
                outcome: t::CommandOutcome::Committed as i32,
                metadata_durable: true,
                application_state_committed: true,
                cleanup_failure: Some(i::PlatformError {
                    code: "internal".into(),
                    message: "/private/store key=secret".into(),
                    detail_items: vec![i::ErrorDetail {
                        kind: "engine-debug".into(),
                        fields: [("path".into(), "/private/store".into())].into(),
                    }],
                    retryable: false,
                }),
                ..Default::default()
            }),
        });
        sanitize(&mut response, &InvocationLimits::default()).unwrap();
        let Response::LookupCommand(value) = response else {
            panic!("lookup");
        };
        let command = value.command.unwrap();
        assert_eq!(command.outcome, t::CommandOutcome::Committed as i32);
        assert!(command.application_state_committed);
        let failure = command.cleanup_failure.unwrap();
        assert!(!failure.message.contains("secret"));
        assert!(failure.detail_items.is_empty());
    }
    #[test]
    fn business_rejection_and_success_payloads_remain_original_application_values() {
        let rejection = i::DeclaredError {
            code: "account-blocked".into(),
            message: "original business rejection".into(),
            payload: vec![0, 255],
            ..Default::default()
        };
        let mut response = Response::from(t::LookupCommandResponse {
            command: Some(t::CommandInspection {
                retained_result: Some(t::command_inspection::RetainedResult::BusinessRejection(
                    rejection.clone(),
                )),
                ..Default::default()
            }),
        });
        sanitize(&mut response, &InvocationLimits::default()).unwrap();
        let Response::LookupCommand(value) = response else {
            panic!("lookup");
        };
        assert_eq!(
            value.command.unwrap().retained_result,
            Some(t::command_inspection::RetainedResult::BusinessRejection(
                rejection
            ))
        );
        let success = i::Success {
            payload: vec![1, 0, 255],
            media_type: "application/octet-stream".into(),
            ..Default::default()
        };
        let mut response = Response::from(t::QueryResponse {
            invocation: Some(i::InvokeResponse {
                result: Some(i::invoke_response::Result::Success(success.clone())),
                ..Default::default()
            }),
            ..Default::default()
        });
        sanitize(&mut response, &InvocationLimits::default()).unwrap();
        let Response::Query(value) = response else {
            panic!("query");
        };
        assert_eq!(
            value.invocation.unwrap().result,
            Some(i::invoke_response::Result::Success(success))
        );
    }
}
