use std::time::Instant;

use serde_json::{json, Value};
use wasmtime::component::Val;

use crate::values::{
    decode_params, decode_params_diagnostic, decode_params_legacy, encode_result, DecodePath,
    EncodedResult, ValueCodecLimits, MEDIA_TYPE,
};

use super::{fixtures::Fixture, ProbeResult};

pub(super) fn verify(
    fixture: &Fixture,
    limits: ValueCodecLimits,
    origin: Instant,
) -> ProbeResult<(Vec<Val>, Value)> {
    let started = origin.elapsed().as_nanos();
    let legacy = decode_params_legacy(&fixture.types, &fixture.input, MEDIA_TYPE, limits)
        .map_err(|error| format!("legacy fixture rejected: {error:?}"))?;
    canonical(fixture, &legacy, limits)?;
    let active = decode_params(&fixture.types, &fixture.input, MEDIA_TYPE, limits)
        .map_err(|error| format!("active fixture rejected: {error:?}"))?;
    canonical(fixture, &active, limits)?;
    let (diagnostic, path) =
        decode_params_diagnostic(&fixture.types, &fixture.input, MEDIA_TYPE, limits);
    let diagnostic =
        diagnostic.map_err(|error| format!("diagnostic fixture rejected: {error:?}"))?;
    canonical(fixture, &diagnostic, limits)?;
    let path = match path {
        DecodePath::LegacyOnly => "legacy-only",
        DecodePath::TypedSuccess => "typed-success",
        _ => return Err("valid fixture took a rejected decoder path".into()),
    };
    if legacy.len() != fixture.types.len()
        || active.len() != legacy.len()
        || diagnostic.len() != legacy.len()
    {
        return Err("preflight arity mismatch".into());
    }
    drop(active);
    drop(diagnostic);
    // Both arms borrow this legacy-produced, deeply validated encoding input.
    // Its capacity provenance therefore does not change with the active decoder.
    Ok((
        legacy,
        json!({
            "started_nanos": started.to_string(), "finished_nanos": origin.elapsed().as_nanos().to_string(),
            "decode_path": path, "legacy_equivalent": true, "canonical_output_matches": true,
            "decoded_arity": fixture.types.len().to_string(), "encoded_bytes": fixture.expected.len().to_string(),
            "decode_calls": "3", "encode_calls": "3",
        }),
    ))
}

fn canonical(fixture: &Fixture, values: &[Val], limits: ValueCodecLimits) -> ProbeResult<()> {
    let output = encode_result(&fixture.types, values, limits)
        .map_err(|error| format!("fixture encoding rejected: {error:?}"))?;
    match output {
        EncodedResult::Returned(bytes) if bytes == fixture.expected => Ok(()),
        _ => Err("fixture canonical output differs from independent bytes".into()),
    }
}
