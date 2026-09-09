use std::time::Instant;

use latent_core::{
    ActivationPhase, ActivationTerminalState, DeadlineDiagnosticDecision,
    DeadlineDiagnosticObservation, DeadlineDiagnosticObserver, DeadlineWaitObserver,
    EffectiveDeadline, ResourceBudget,
};
use serde_json::{json, Value};

use super::super::cold::call::Clock;
use super::Result;

pub(super) fn diagnostic(observer: &DeadlineDiagnosticObserver, clock: Clock) -> Result<Value> {
    let began = clock.elapsed();
    let snapshot = observer.snapshot();
    let finished = clock.elapsed();
    let identities = snapshot.identities.iter().map(|identity| {
        json!({"token":identity.token.id().to_string(),"activation_id":identity.activation_id})
    }).collect::<Vec<_>>();
    let records = snapshot
        .records
        .iter()
        .map(|record| {
            Ok(
                json!({"sequence":record.sequence.to_string(),"token":record.token.id().to_string(),
            "observation":observation(&record.observation,clock)?}),
            )
        })
        .collect::<Result<Vec<_>>>()?;
    Ok(json!({"collector_started_nanos":began.to_string(),
        "collector_finished_nanos":finished.to_string(),"origin_nanos":at(snapshot.origin,clock)?,
        "overflowed":snapshot.overflowed,"identities":identities,"records":records}))
}

pub(super) fn waits(observer: &DeadlineWaitObserver) -> Value {
    let value = observer.snapshot();
    json!({"supported":value.supported,"armed":value.armed.to_string(),
        "completed":value.completed.to_string(),"dropped":value.dropped.to_string(),
        "live":value.live.to_string(),"maximum_live":value.maximum_live.to_string(),
        "rechecks":value.rechecks.to_string(),"overflowed":value.overflowed})
}

fn observation(value: &DeadlineDiagnosticObservation, clock: Clock) -> Result<Value> {
    use DeadlineDiagnosticObservation as Event;
    let (observed_at, mut record) = match value {
        Event::Ingress {
            observed_at,
            expires_at,
            deadline_unix_millis,
        } => (
            observed_at,
            json!({"kind":"ingress","expires_at_nanos":optional_at(*expires_at,clock)?,
                "deadline_unix_millis":decimal(*deadline_unix_millis)}),
        ),
        Event::BodyDecoded {
            observed_at,
            request_deadline_unix_millis,
            request_wall_time_limit_millis,
        } => (
            observed_at,
            json!({"kind":"body-decoded",
                "request_deadline_unix_millis":decimal(*request_deadline_unix_millis),
                "request_wall_time_limit_millis":decimal(*request_wall_time_limit_millis)}),
        ),
        Event::AdmissionCheck {
            observed_at,
            deadline: selected,
            remaining,
            required,
            decision: result,
        } => (
            observed_at,
            json!({"kind":"admission-check","deadline":deadline(selected,clock)?,
                "remaining_nanos":remaining.map(|value|value.as_nanos().to_string()),
                "required_nanos":required.map(|value|value.as_nanos().to_string()),
                "decision":decision(*result),"platform_code":platform_code(*result)}),
        ),
        Event::AdmittedLedger {
            observed_at,
            deadline: selected,
            budget: granted,
        } => (
            observed_at,
            json!({"kind":"admitted-ledger","deadline":deadline(selected,clock)?,"budget":budget(granted)}),
        ),
        Event::ExecutionDeadline {
            observed_at,
            deadline: selected,
            budget: granted,
        } => (
            observed_at,
            json!({"kind":"execution-deadline","deadline":deadline(selected,clock)?,"budget":budget(granted)}),
        ),
        Event::TerminalDecision {
            observed_at,
            expires_at,
            decision: result,
        } => (
            observed_at,
            json!({"kind":"terminal-decision","expires_at_nanos":optional_at(*expires_at,clock)?,
                "decision":decision(*result),"platform_code":platform_code(*result)}),
        ),
        Event::LifecyclePhase {
            observed_at,
            phase: value,
        } => (
            observed_at,
            json!({"kind":"lifecycle-phase","phase":phase(*value)?}),
        ),
        Event::TerminalWinner {
            observed_at,
            terminal_state,
        } => (
            observed_at,
            json!({"kind":"terminal-winner","terminal_state":terminal(*terminal_state)?}),
        ),
    };
    record["observed_at_nanos"] = Value::String(at(*observed_at, clock)?);
    Ok(record)
}

fn at(value: Instant, clock: Clock) -> Result<String> {
    value
        .checked_duration_since(clock.origin)
        .map(|duration| duration.as_nanos().to_string())
        .ok_or_else(|| "budget diagnostic timestamp predates collector clock".into())
}

fn optional_at(value: Option<Instant>, clock: Clock) -> Result<Option<String>> {
    value.map(|value| at(value, clock)).transpose()
}

fn decimal(value: Option<u64>) -> Option<String> {
    value.map(|value| value.to_string())
}

fn deadline(value: &EffectiveDeadline, clock: Clock) -> Result<Value> {
    Ok(
        json!({"admitted_at_nanos":at(value.admitted_at_monotonic(),clock)?,
        "admitted_at_unix_millis":value.admitted_at_unix_millis().to_string(),
        "expires_at_nanos":optional_at(value.monotonic(),clock)?,"unix_millis":decimal(value.unix_millis())}),
    )
}

fn budget(value: &ResourceBudget) -> Value {
    json!({"cpu_fuel":value.cpu_fuel.to_string(),"memory_bytes":value.memory_bytes.to_string(),
        "wall_time_limit_millis":decimal(value.wall_time_limit_millis),
        "log_bytes":value.log_bytes.to_string(),
        "reserved_dimensions_zero": value.child_calls == 0 && value.outbound_requests == 0
            && value.state_read_bytes == 0 && value.state_write_bytes == 0
            && value.blob_read_bytes == 0 && value.blob_write_bytes == 0 && value.effect_count == 0})
}

fn decision(value: DeadlineDiagnosticDecision) -> &'static str {
    match value {
        DeadlineDiagnosticDecision::Accepted => "accepted",
        DeadlineDiagnosticDecision::Completed => "completed",
        DeadlineDiagnosticDecision::Cancelled => "cancelled",
        DeadlineDiagnosticDecision::DeadlineExceeded => "deadline-exceeded",
        DeadlineDiagnosticDecision::QueueInfeasible => "queue-infeasible",
        DeadlineDiagnosticDecision::LoadStale => "load-stale",
        DeadlineDiagnosticDecision::QueueEstimateOverflow => "queue-estimate-overflow",
        DeadlineDiagnosticDecision::MissingDeadline => "missing-deadline",
        DeadlineDiagnosticDecision::Rejected(_) => "rejected",
    }
}

fn platform_code(value: DeadlineDiagnosticDecision) -> Option<&'static str> {
    match value {
        DeadlineDiagnosticDecision::Rejected(code) => Some(code.wire_code()),
        _ => None,
    }
}

fn phase(value: ActivationPhase) -> Result<&'static str> {
    Ok(match value {
        ActivationPhase::Received => "received",
        ActivationPhase::Resolved => "resolved",
        ActivationPhase::Admitted => "admitted",
        ActivationPhase::Queued => "queued",
        ActivationPhase::Materializing => "materializing",
        ActivationPhase::Running => "running",
        ActivationPhase::Suspended => "suspended",
        ActivationPhase::PreparingCommit => "preparing-commit",
        ActivationPhase::Committed => "committed",
        ActivationPhase::EffectsPending => "effects-pending",
        _ => return Err("unsupported budget diagnostic lifecycle phase".into()),
    })
}

fn terminal(value: ActivationTerminalState) -> Result<&'static str> {
    Ok(match value {
        ActivationTerminalState::Completed => "completed",
        ActivationTerminalState::Rejected => "rejected",
        ActivationTerminalState::Cancelled => "cancelled",
        ActivationTerminalState::DeadlineExceeded => "deadline-exceeded",
        ActivationTerminalState::ResourceExhausted => "resource-exhausted",
        ActivationTerminalState::GuestTrap => "guest-trap",
        ActivationTerminalState::StateConflict => "state-conflict",
        ActivationTerminalState::DependencyFailed => "dependency-failed",
        ActivationTerminalState::PlatformFailed => "platform-failed",
        _ => return Err("unsupported budget diagnostic terminal state".into()),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    #[test]
    fn exact_and_missing_timestamps_survive_projection_and_pre_origin_fails() {
        let origin = Instant::now();
        let clock = Clock {
            origin,
            unix_nanos: 0,
            uncertainty_nanos: 0,
        };
        let observer = DeadlineDiagnosticObserver::new(origin);
        let token = observer
            .begin(DeadlineDiagnosticObservation::Ingress {
                observed_at: origin + Duration::from_nanos(731),
                expires_at: None,
                deadline_unix_millis: None,
            })
            .unwrap();
        assert!(observer.bind(token, "diagnostic"));
        let value = diagnostic(&observer, clock).unwrap();
        assert_eq!(value["origin_nanos"], "0");
        assert_eq!(
            value["records"][0]["observation"]["observed_at_nanos"],
            "731"
        );
        assert!(value["records"][0]["observation"]["expires_at_nanos"].is_null());
        let later = Clock {
            origin: origin + Duration::from_millis(1),
            ..clock
        };
        assert!(diagnostic(&observer, later).is_err());
    }
}
