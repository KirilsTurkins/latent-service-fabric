//! Bounded Phase 1 JSON framing over the component's authoritative value types.

mod decode;
mod encode;
mod parse;
mod signature;
mod typed;

use latent_core::{DeclaredError, PlatformError, PlatformErrorCode};
use wasmtime::component::{Type, Val};

pub(crate) use signature::validate_signature;

pub const MEDIA_TYPE: &str = "application/vnd.latent.wit-values.v1+json";

/// Independent payload, schema, input-value, and per-transfer lifting ceilings.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ValueCodecLimits {
    pub max_input_bytes: usize,
    pub max_output_bytes: usize,
    pub max_depth: usize,
    pub max_nodes: usize,
    pub max_string_bytes: usize,
    pub max_collection_items: usize,
    pub max_type_nodes: usize,
    pub max_type_name_bytes: usize,
    pub max_lifted_bytes: usize,
    pub max_decoded_value_bytes: usize,
}

impl Default for ValueCodecLimits {
    fn default() -> Self {
        Self {
            max_input_bytes: 1024 * 1024,
            max_output_bytes: 1024 * 1024,
            max_depth: 32,
            max_nodes: 16_384,
            max_string_bytes: 256 * 1024,
            max_collection_items: 4096,
            max_type_nodes: 4096,
            max_type_name_bytes: 256,
            max_lifted_bytes: 16 * 1024 * 1024,
            max_decoded_value_bytes: 16 * 1024 * 1024,
        }
    }
}

impl ValueCodecLimits {
    pub fn validate(&self) -> Result<(), PlatformError> {
        let bounds = [
            self.max_input_bytes,
            self.max_output_bytes,
            self.max_depth,
            self.max_nodes,
            self.max_string_bytes,
            self.max_collection_items,
            self.max_type_nodes,
            self.max_type_name_bytes,
            self.max_lifted_bytes,
            self.max_decoded_value_bytes,
        ];
        if self.max_depth > 64
            || bounds
                .iter()
                .any(|value| *value == 0 || *value > isize::MAX as usize)
        {
            return Err(failure(
                PlatformErrorCode::InvalidArgument,
                "invalid-value-codec-limits",
            ));
        }
        Ok(())
    }
}

pub(crate) enum EncodedResult {
    Returned(Vec<u8>),
    DeclaredError(DeclaredError),
}

pub(crate) fn decode_params(
    types: &[Type],
    payload: &[u8],
    media_type: &str,
    limits: ValueCodecLimits,
) -> Result<Vec<Val>, PlatformError> {
    decode_params_dispatch(types, payload, media_type, limits).0
}

// Local diagnostic metadata lets the explicit codec probe identify the path
// without a global observer or any per-call synchronization.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[allow(dead_code)]
pub(super) enum DecodePath {
    LegacyOnly,
    PreflightRejected,
    TypedSuccess,
    LegacyError,
    TypedRejectedLegacyAccepted,
}

fn decode_params_dispatch(
    types: &[Type],
    payload: &[u8],
    media_type: &str,
    limits: ValueCodecLimits,
) -> (Result<Vec<Val>, PlatformError>, DecodePath) {
    if let Err(error) = limits.validate() {
        return (Err(error), DecodePath::PreflightRejected);
    }
    if media_type != MEDIA_TYPE {
        return (
            Err(failure(
                PlatformErrorCode::InvalidArgument,
                "unsupported-invocation-media-type",
            )),
            DecodePath::PreflightRejected,
        );
    }
    if let Err(error) = parse::preflight(payload, limits) {
        return (Err(error), DecodePath::PreflightRejected);
    }
    match typed::params(types, payload, limits) {
        Ok(values) => (Ok(values), DecodePath::TypedSuccess),
        Err(error) => {
            // Partial typed values have already been dropped. The legacy path
            // preserves rejection precedence without retaining two value trees.
            drop(error);
            match decode_params_legacy(types, payload, media_type, limits) {
                Err(error) => (Err(error), DecodePath::LegacyError),
                Ok(values) => {
                    drop(values);
                    (
                        Err(failure(
                            PlatformErrorCode::Internal,
                            "typed-value-codec-compatibility-failure",
                        )),
                        DecodePath::TypedRejectedLegacyAccepted,
                    )
                }
            }
        }
    }
}

#[cfg(test)]
pub(super) fn decode_params_diagnostic(
    types: &[Type],
    payload: &[u8],
    media_type: &str,
    limits: ValueCodecLimits,
) -> (Result<Vec<Val>, PlatformError>, DecodePath) {
    decode_params_dispatch(types, payload, media_type, limits)
}

pub(super) fn decode_params_legacy(
    types: &[Type],
    payload: &[u8],
    media_type: &str,
    limits: ValueCodecLimits,
) -> Result<Vec<Val>, PlatformError> {
    limits.validate()?;
    if media_type != MEDIA_TYPE {
        return Err(failure(
            PlatformErrorCode::InvalidArgument,
            "unsupported-invocation-media-type",
        ));
    }
    decode::params(types, parse::parse(payload, limits)?, limits)
}

pub(crate) fn encode_result(
    types: &[Type],
    values: &[Val],
    limits: ValueCodecLimits,
) -> Result<EncodedResult, PlatformError> {
    limits.validate()?;
    let payload = encode::results(types, values, limits)?;
    if matches!((types, values), ([Type::Result(_)], [Val::Result(Err(_))])) {
        Ok(EncodedResult::DeclaredError(DeclaredError {
            code: "declared-error".to_owned(),
            message: "component returned a declared error".to_owned(),
            payload,
            media_type: MEDIA_TYPE.to_owned(),
            metadata: latent_core::Metadata::new(),
        }))
    } else {
        Ok(EncodedResult::Returned(payload))
    }
}

fn failure(code: PlatformErrorCode, reason: &str) -> PlatformError {
    crate::containment::platform_error(code, reason, false)
}

fn invalid_input() -> PlatformError {
    failure(
        PlatformErrorCode::InvalidArgument,
        "invalid-invocation-values",
    )
}

fn limit() -> PlatformError {
    failure(
        PlatformErrorCode::ResourceExhausted,
        "invocation-value-limit",
    )
}

fn invalid_result() -> PlatformError {
    failure(PlatformErrorCode::Internal, "invalid-component-result")
}

fn unsupported() -> PlatformError {
    failure(
        PlatformErrorCode::IncompatibleContract,
        "unsupported-component-value-type",
    )
}

fn charge(remaining: &mut usize, bytes: usize) -> Result<(), PlatformError> {
    *remaining = remaining.checked_sub(bytes).ok_or_else(limit)?;
    Ok(())
}

#[cfg(test)]
mod tests;
