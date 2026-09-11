use latent_wire::invocation::proto::{self, invoke_response::Result as Outcome};
use serde_json::{json, Value};

use super::{Case, Result};

pub(super) fn response(
    case: Case,
    id: &str,
    response: &proto::InvokeResponse,
) -> Result<&'static str> {
    let consumed = response
        .consumption
        .as_ref()
        .ok_or("missing response consumption")?;
    if !matches!(case, Case::Cancel | Case::Deadline | Case::Malformed)
        && (consumed.cpu_fuel == 0 || consumed.peak_memory_bytes == 0)
    {
        return Err("guest never executed".into());
    }
    match (case, response.result.as_ref()) {
        (Case::Domain, Some(Outcome::DeclaredError(error))) => {
            if error.code != "declared-error"
                || serde_json::from_slice::<Value>(&error.payload)?
                    != json!([{"err":{"case":"named","value":"denied"}}])
            {
                return Err("incorrect declared error".into());
            }
            Ok("declared-error")
        }
        (
            Case::Trap
            | Case::Fuel
            | Case::Memory
            | Case::Deadline
            | Case::Cancel
            | Case::Malformed,
            Some(Outcome::PlatformFailure(error)),
        ) => {
            let code = match case {
                Case::Malformed => "invalid-argument",
                Case::Trap => "guest-trap",
                Case::Fuel | Case::Memory => "resource-exhausted",
                Case::Deadline => "deadline-exceeded",
                _ => "cancelled",
            };
            if error.code != code {
                return Err("incorrect platform failure".into());
            }
            if matches!(case, Case::Fuel) && consumed.cpu_fuel > 50_000 {
                return Err("fuel accounting exceeds grant".into());
            }
            if matches!(case, Case::Memory) && consumed.peak_memory_bytes > 4 * 1024 * 1024 {
                return Err("memory accounting exceeds grant".into());
            }
            Ok(code)
        }
        (_, Some(Outcome::Success(success))) => {
            let value: Value = serde_json::from_slice(&success.payload)?;
            match case {
                Case::Success if value == json!([5]) => {}
                Case::Echo if value == json!([{"ok":"phase0 warm echo"}]) => {}
                Case::FirstEcho if value == json!([{"ok":"phase0 retained first echo"}]) => {}
                Case::FreshStore if value == json!([1]) => {}
                Case::LogDenied
                    if value[0]["outcome"] == json!({"err":{"case":"budget-exhausted"}})
                        && consumed.log_bytes == 0 => {}
                Case::LogAccepted
                    if value[0]["outcome"] == json!({"ok":true})
                        && consumed.log_bytes > 0
                        && consumed.log_bytes <= 4096
                        && value[0]["after"]
                            .as_str()
                            .and_then(|v| v.parse::<u64>().ok())
                            == Some(4096 - consumed.log_bytes) => {}
                Case::Context
                    if value[0]["activation"] == id
                        && value[0]["root"] == id
                        && value[0]["metadata"] == json!([["guest.visible", id]])
                        && value[0]["principal"]["claims"] == json!([])
                        && value[0]["trace"]["baggage"] == json!([])
                        && !value.to_string().contains("measurement-private-context") => {}
                _ => return Err("incorrect successful guest result".into()),
            }
            Ok("success")
        }
        _ => Err("incorrect guest outcome class".into()),
    }
}
