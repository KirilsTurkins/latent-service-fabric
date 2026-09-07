use latent_core::{BudgetConsumption, DeclaredError, Metadata, PlatformError, PlatformErrorCode};
use latent_executor::{ExecutionReport, ExecutionRequest, GuestOutcome, GuestTrap};
use wasmtime::component::{Type, Val};

use super::{ECHO_DOMAIN_ERROR_MEDIA_TYPE, ECHO_EXPORT, ECHO_SUCCESS_MEDIA_TYPE};
use crate::containment::platform_error;
use crate::values::{self, EncodedResult, ValueCodecLimits};

const EMPTY_MESSAGE_OUTPUT: &[u8] = br#"{"error":"empty-message"}"#;
const MESSAGE_TOO_LARGE_OUTPUT: &[u8] = br#"{"error":"message-too-large"}"#;

pub(super) fn request(
    mut request: ExecutionRequest,
    limits: ValueCodecLimits,
) -> Result<ExecutionRequest, PlatformError> {
    if request.activation.target.contract.0 != ECHO_EXPORT
        || request.activation.target.function.0 != "echo"
    {
        return Err(platform_error(
            PlatformErrorCode::InvalidArgument,
            "the Phase 0 backend supports only examples:echo/api@0.1.0#echo",
            false,
        ));
    }
    if request.activation.input_media_type != ECHO_SUCCESS_MEDIA_TYPE {
        return Err(platform_error(
            PlatformErrorCode::InvalidArgument,
            "the Phase 0 echo input media type must be UTF-8 text",
            false,
        ));
    }
    request.activation.input = encode_input(std::mem::take(&mut request.activation.input), limits)?;
    values::MEDIA_TYPE.clone_into(&mut request.activation.input_media_type);
    Ok(request)
}

pub(super) fn encode_input(
    input: Vec<u8>,
    limits: ValueCodecLimits,
) -> Result<Vec<u8>, PlatformError> {
    if input.len() > limits.max_input_bytes || input.len() > limits.max_string_bytes {
        return Err(value_limit());
    }
    let input = String::from_utf8(input).map_err(|_| {
        platform_error(
            PlatformErrorCode::InvalidArgument,
            "the Phase 0 echo input must be valid UTF-8",
            false,
        )
    })?;
    // Parameters and results share the positional JSON framing. Reuse the
    // bounded value encoder, but apply the input byte ceiling to this buffer.
    let limits = ValueCodecLimits {
        max_output_bytes: limits.max_input_bytes,
        ..limits
    };
    match values::encode_result(&[Type::String], &[Val::String(input)], limits)? {
        EncodedResult::Returned(payload) => Ok(payload),
        EncodedResult::DeclaredError(_) => Err(invalid_result()),
    }
}

pub(super) fn report(mut report: ExecutionReport, limits: ValueCodecLimits) -> ExecutionReport {
    report.outcome = report.outcome.map(|value| outcome(value, limits));
    report
}

pub(super) fn outcome(outcome: GuestOutcome, limits: ValueCodecLimits) -> GuestOutcome {
    match outcome {
        GuestOutcome::Returned {
            output,
            output_media_type,
            consumption,
        } => match success_output(&output, &output_media_type, limits) {
            Ok(output) => GuestOutcome::Returned {
                output,
                output_media_type: ECHO_SUCCESS_MEDIA_TYPE.to_owned(),
                consumption,
            },
            Err(error) => adaptation_trap(error, consumption),
        },
        GuestOutcome::DeclaredError { error, consumption } => match domain_error(&error, limits) {
            Ok(error) => GuestOutcome::DeclaredError { error, consumption },
            Err(error) => adaptation_trap(error, consumption),
        },
        unchanged => unchanged,
    }
}

fn success_output(
    payload: &[u8],
    media_type: &str,
    limits: ValueCodecLimits,
) -> Result<Vec<u8>, PlatformError> {
    if media_type != values::MEDIA_TYPE {
        return Err(invalid_result());
    }
    let EchoResult::Success(output) = decode_result(payload, limits)? else {
        return Err(invalid_result());
    };
    Ok(output.into_bytes())
}

fn domain_error(
    error: &DeclaredError,
    limits: ValueCodecLimits,
) -> Result<DeclaredError, PlatformError> {
    if error.media_type != values::MEDIA_TYPE || error.code != "declared-error" {
        return Err(invalid_result());
    }
    let EchoResult::Failure(variant) = decode_result(&error.payload, limits)? else {
        return Err(invalid_result());
    };
    match variant.case.as_str() {
        "empty-message" => Ok(echo_declared_error(
            "empty-message",
            "the echo message must not be empty",
            EMPTY_MESSAGE_OUTPUT,
        )),
        "message-too-large" => Ok(echo_declared_error(
            "message-too-large",
            "the echo message exceeds the declared byte limit",
            MESSAGE_TOO_LARGE_OUTPUT,
        )),
        _ => Err(invalid_result()),
    }
}

fn adaptation_trap(error: PlatformError, consumption: BudgetConsumption) -> GuestOutcome {
    GuestOutcome::Trapped {
        trap: GuestTrap {
            code: if error.code == PlatformErrorCode::ResourceExhausted {
                "result-limit-exceeded"
            } else {
                "invalid-component-result"
            }
            .to_owned(),
            message: error.message,
            guest_backtrace: Vec::new(),
            metadata: Metadata::from([(
                "result-codec-error".to_owned(),
                format!("{:?}", error.code),
            )]),
        },
        consumption,
    }
}

#[derive(serde::Deserialize)]
enum EchoResult {
    #[serde(rename = "ok")]
    Success(String),
    #[serde(rename = "err")]
    Failure(EchoErrorVariant),
}

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct EchoErrorVariant {
    case: String,
}

fn decode_result(payload: &[u8], limits: ValueCodecLimits) -> Result<EchoResult, PlatformError> {
    if payload.len() > limits.max_output_bytes {
        return Err(value_limit());
    }
    let [value]: [EchoResult; 1] = serde_json::from_slice(payload).map_err(|_| invalid_result())?;
    Ok(value)
}

pub(super) fn echo_declared_error(code: &str, message: &str, payload: &[u8]) -> DeclaredError {
    DeclaredError {
        code: code.to_owned(),
        message: message.to_owned(),
        payload: payload.to_vec(),
        media_type: ECHO_DOMAIN_ERROR_MEDIA_TYPE.to_owned(),
        metadata: Metadata::new(),
    }
}

fn invalid_result() -> PlatformError {
    platform_error(
        PlatformErrorCode::Internal,
        "invalid Phase 0 echo result framing",
        false,
    )
}

fn value_limit() -> PlatformError {
    platform_error(
        PlatformErrorCode::ResourceExhausted,
        "invocation-value-limit",
        false,
    )
}
