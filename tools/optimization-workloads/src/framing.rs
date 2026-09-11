use serde::de::DeserializeOwned;
use serde::Serialize;

use super::{compute, echo, transform, TransformValue, MAX_PAYLOAD_BYTES};

/// Executes a bounded canonical JSON argument frame and returns the result array.
/// Unknown functions, malformed frames and out-of-domain values are rejected.
/// Error text is fixed and does not contain payloads or serde diagnostics.
pub fn invoke(function: &str, payload: &[u8]) -> Result<Vec<u8>, String> {
    if payload.len() > MAX_PAYLOAD_BYTES {
        return Err("optimization-payload-limit".to_owned());
    }
    match function {
        "echo" => {
            let (message,): (String,) = decode(payload)?;
            encode(&(echo(message).map_err(|error| error.to_string())?,))
        }
        "compute" => {
            let (seed, rounds): (u32, u32) = decode(payload)?;
            encode(&(compute(seed, rounds).map_err(|error| error.to_string())?,))
        }
        "transform" => {
            let (value,): (TransformValue,) = decode(payload)?;
            encode(&(transform(value).map_err(|error| error.to_string())?,))
        }
        _ => Err("optimization-unknown-function".to_owned()),
    }
}

fn decode<T: DeserializeOwned>(payload: &[u8]) -> Result<T, String> {
    serde_json::from_slice(payload).map_err(|_| "optimization-invalid-frame".to_owned())
}

fn encode<T: Serialize>(value: &T) -> Result<Vec<u8>, String> {
    let encoded =
        serde_json::to_vec(value).map_err(|_| "optimization-encoding-failed".to_owned())?;
    if encoded.len() > MAX_PAYLOAD_BYTES {
        return Err("optimization-result-limit".to_owned());
    }
    Ok(encoded)
}
