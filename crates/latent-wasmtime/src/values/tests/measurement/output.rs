use std::io::Write;

use serde_json::{json, Value};

use super::{input::Input, ProbeResult};
use crate::preparation_observer::PreparationThreadIdentity;
use crate::values::ValueCodecLimits;

pub(super) fn event(
    input: &Input,
    identity: PreparationThreadIdentity,
    elapsed: u128,
    complete: bool,
) -> Value {
    json!({
        "schema": if complete { "latent.optimization.codec-complete.v1" } else { "latent.optimization.codec-ready.v1" },
        "event": if complete { "measurement-complete" } else { "ready" },
        "process_id": std::process::id(), "plan_sha256": input.plan_sha256,
        "identity_sha256": input.identity_sha256, "family": input.plan.family,
        "mode": input.plan.mode, "repetition": input.plan.repetition, "variant": input.plan.variant,
        "thread_identity": identity, "observation_hold_millis": 100,
        "elapsed_nanos": elapsed.to_string(),
    })
}

pub(super) fn emit(value: &Value) -> ProbeResult<()> {
    let bytes = serde_json::to_vec(value)?;
    if bytes.len() > 16_384 {
        return Err("codec event exceeds bound".into());
    }
    let mut output = std::io::stdout().lock();
    output.write_all(b"\n")?;
    output.write_all(&bytes)?;
    output.write_all(b"\n")?;
    output.flush()?;
    Ok(())
}

pub(super) fn nanos(value: rustix::time::Timespec) -> ProbeResult<u128> {
    let seconds = u128::try_from(value.tv_sec)?;
    let nanos = u128::try_from(value.tv_nsec)?;
    if nanos >= 1_000_000_000 {
        return Err("invalid codec CPU clock nanos".into());
    }
    Ok(seconds * 1_000_000_000 + nanos)
}

pub(super) fn limits(value: ValueCodecLimits) -> Value {
    json!({
        "max_input_bytes": value.max_input_bytes.to_string(), "max_output_bytes": value.max_output_bytes.to_string(),
        "max_depth": value.max_depth.to_string(), "max_nodes": value.max_nodes.to_string(),
        "max_string_bytes": value.max_string_bytes.to_string(), "max_collection_items": value.max_collection_items.to_string(),
        "max_type_nodes": value.max_type_nodes.to_string(), "max_type_name_bytes": value.max_type_name_bytes.to_string(),
        "max_lifted_bytes": value.max_lifted_bytes.to_string(), "max_decoded_value_bytes": value.max_decoded_value_bytes.to_string(),
    })
}
