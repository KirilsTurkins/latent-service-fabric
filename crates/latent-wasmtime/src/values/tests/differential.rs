//! Independent contract checks; the legacy implementation is the error oracle.

use super::*;

mod corpus;
mod limits;
mod ownership;
mod precedence;
mod scalars;
mod tagged;

fn equivalent(
    label: &str,
    signature: &[Type],
    bytes: &[u8],
    limits: ValueCodecLimits,
) -> Result<(), PlatformError> {
    equivalent_media(label, signature, bytes, MEDIA_TYPE, limits)
}

fn equivalent_media(
    label: &str,
    signature: &[Type],
    bytes: &[u8],
    media: &str,
    limits: ValueCodecLimits,
) -> Result<(), PlatformError> {
    let legacy = decode_params_legacy(signature, bytes, media, limits);
    let (observed, path) = decode_params_diagnostic(signature, bytes, media, limits);
    assert_ne!(
        path,
        DecodePath::TypedRejectedLegacyAccepted,
        "{label}: typed rejection must never hide a legacy success"
    );
    if legacy.is_ok() {
        assert_eq!(path, DecodePath::TypedSuccess, "{label}: successful path");
    } else {
        assert!(
            matches!(
                path,
                DecodePath::PreflightRejected | DecodePath::LegacyError
            ),
            "{label}: unexpected rejection path {path:?}"
        );
    }
    compare(label, signature, &legacy, &observed);
    let public = decode_params(signature, bytes, media, limits);
    compare(label, signature, &legacy, &public);
    legacy.map(drop)
}

fn compare(
    label: &str,
    signature: &[Type],
    legacy: &Result<Vec<Val>, PlatformError>,
    candidate: &Result<Vec<Val>, PlatformError>,
) {
    match (legacy, candidate) {
        (Ok(expected), Ok(actual)) => same_values(label, signature, expected, actual),
        (Err(expected), Err(actual)) => {
            assert_eq!(actual.code, expected.code, "{label}: error code");
            assert_eq!(actual.message, expected.message, "{label}: error message");
            assert_eq!(
                actual.retryable, expected.retryable,
                "{label}: retryability"
            );
        }
        (Ok(_), Err(error)) => panic!("{label}: accepted legacy input rejected: {error:?}"),
        (Err(error), Ok(_)) => panic!("{label}: rejected legacy input accepted: {error:?}"),
    }
}

fn same_values(label: &str, signature: &[Type], expected: &[Val], actual: &[Val]) {
    assert_eq!(actual.len(), expected.len(), "{label}: value arity");
    let limits = ValueCodecLimits {
        max_depth: 64,
        ..ValueCodecLimits::default()
    };
    let expected = encode_result(signature, expected, limits).expect("oracle canonical encoding");
    let actual = encode_result(signature, actual, limits).expect("candidate canonical encoding");
    // Canonical bytes preserve signed zero and normalize NaNs without comparing
    // NaN with itself. Avoid printing large payloads on a regression.
    match (expected, actual) {
        (EncodedResult::Returned(expected), EncodedResult::Returned(actual)) => {
            assert!(actual == expected, "{label}: different canonical values");
        }
        (EncodedResult::DeclaredError(expected), EncodedResult::DeclaredError(actual)) => {
            assert!(actual == expected, "{label}: different declared result");
        }
        _ => panic!("{label}: declared-error boundary changed"),
    }
}

fn rejected(
    label: &str,
    signature: &[Type],
    bytes: &[u8],
    limits: ValueCodecLimits,
    code: PlatformErrorCode,
    message: &str,
) {
    let error = equivalent(label, signature, bytes, limits).expect_err("contract rejection");
    assert_eq!(error.code, code, "{label}: independent expected code");
    assert_eq!(
        error.message, message,
        "{label}: independent expected reason"
    );
}

fn invalid(label: &str, signature: &[Type], bytes: &[u8]) {
    rejected(
        label,
        signature,
        bytes,
        ValueCodecLimits::default(),
        PlatformErrorCode::InvalidArgument,
        "invalid-invocation-values",
    );
}
