use super::{
    budget,
    cold::call::{auth, Clock},
    Node, Result, Writer,
};
use latent_core::{
    ActivationPhase, DeadlineDiagnosticObservation as Event, DeadlineDiagnosticObserver,
};
use latent_telemetry::TelemetryRecord;
use latent_wire::invocation::{proto, InvocationServiceClient};
use serde_json::{json, Value};
use std::time::Duration;

pub(super) fn phase(
    observer: &DeadlineDiagnosticObserver,
    id: &str,
    terminal: bool,
) -> Option<u64> {
    let snapshot = observer.snapshot();
    let token = snapshot
        .identities
        .iter()
        .find(|row| row.activation_id.as_deref() == Some(id))?
        .token;
    snapshot
        .records
        .iter()
        .find(|row| {
            row.token == token
                && if terminal {
                    matches!(row.observation, Event::TerminalWinner { .. })
                } else {
                    matches!(
                        row.observation,
                        Event::LifecyclePhase {
                            phase: ActivationPhase::Running,
                            ..
                        }
                    )
                }
        })
        .map(|row| row.sequence)
}

pub(super) fn running(observer: &DeadlineDiagnosticObserver, id: &str, clock: Clock) -> Value {
    phase(observer, id, false).map_or(Value::Null, |sequence| {
        json!({
        "observed_nanos":clock.elapsed().to_string(),"phase_record_sequence":sequence.to_string()})
    })
}

pub(super) async fn acknowledgement(
    observer: &DeadlineDiagnosticObserver,
    id: &str,
    clock: Clock,
) -> Value {
    let began = clock.elapsed();
    let mut sequence = None;
    // The handoff allowance is200ms. This independent250ms observation window
    // does not renew cleanup or guest execution; it only waits for publication.
    let deadline = tokio::time::Instant::now() + Duration::from_millis(250);
    for _ in 0..256 {
        sequence = phase(observer, id, true);
        if sequence.is_some() || tokio::time::Instant::now() >= deadline {
            break;
        }
        tokio::time::sleep_until(
            (tokio::time::Instant::now() + Duration::from_millis(1)).min(deadline),
        )
        .await;
    }
    json!({"started_nanos":began.to_string(),"finished_nanos":clock.elapsed().to_string(),
        "terminal_sequence":sequence.map(|value|value.to_string()),"maximum_millis":"250"})
}

pub(super) async fn status(
    node: &mut Node,
    id: &str,
    clock: Clock,
    ordinal: u64,
    writer: &mut Writer,
) -> Result<(Value, u128)> {
    node.command(false)?;
    let started = clock.elapsed();
    let response = super::cold::call::status(
        InvocationServiceClient::new(node.channel())
            .get_activation(auth(
                proto::GetActivationRequest {
                    activation_id: id.to_owned(),
                },
                Duration::from_secs(5),
            )?)
            .await,
    );
    let finished = clock.elapsed();
    writer.sample(&json!({"kind":"command","ordinal":ordinal.to_string(),"operation":"status","target":id,
        "started_nanos":started.to_string(),"finished_nanos":finished.to_string(),"response":response,"trigger":Value::Null}))?;
    Ok((response, finished))
}

pub(super) async fn cancel(
    node: &mut Node,
    id: &str,
    clock: Clock,
    ordinal: u64,
    trigger: &Value,
    writer: &mut Writer,
) -> Result<Value> {
    node.command(false)?;
    let started = clock.elapsed();
    let response = InvocationServiceClient::new(node.channel())
        .cancel(auth(
            proto::CancelRequest {
                activation_id: id.to_owned(),
                reason: "recovery positive cancellation".into(),
            },
            Duration::from_secs(5),
        )?)
        .await;
    let finished = clock.elapsed();
    let response = match response {
        Ok(response) => {
            let response = response.into_inner();
            json!({"grpc_code":0,"disposition":response.disposition,"terminal_state":response.terminal_state})
        }
        Err(error) => json!({"grpc_code":error.code() as i32}),
    };
    writer.sample(&json!({"kind":"command","ordinal":ordinal.to_string(),"operation":"cancel","target":id,
        "started_nanos":started.to_string(),"finished_nanos":finished.to_string(),"response":response,"trigger":trigger}))?;
    Ok(response)
}

pub(super) async fn cleanup_log(node: &Node, id: &str) -> Result<Value> {
    tokio::time::timeout(Duration::from_secs(1), node.owner.telemetry.flush())
        .await
        .map_err(|_| "recovery telemetry flush deadline")?
        .map_err(super::super::super::platform)?;
    let mut rows = Vec::new();
    for record in node.owner.sink.records() {
        if let TelemetryRecord::Log(log) = record {
            if log.attributes.get("activation_id").map(String::as_str) == Some(id)
                && log.attributes.get("stage").map(String::as_str) == Some("cleanup")
            {
                rows.push(json!({"body":log.body,"attributes":log.attributes,
                    "observed_at_unix_millis":log.observed_at_unix_millis.to_string()}));
            }
        }
    }
    if rows.len() > 1 {
        return Err("duplicate recovery cleanup disposition".into());
    }
    Ok(rows.pop().unwrap_or(Value::Null))
}

pub(super) fn checkpoint(
    node: &Node,
    clock: Clock,
    waits: &latent_core::DeadlineWaitObserver,
    ordinal: u32,
    writer: &mut Writer,
) -> Result<Value> {
    let observed = clock.elapsed();
    let sample = node.sample("recovery-after-offer")?;
    let cleanup = node.owner.cleanup_snapshot();
    writer.sample(&json!({"kind":"checkpoint","ordinal":ordinal.to_string(),"observed_nanos":observed.to_string(),
        "node":sample,"cleanup":cleanup,"waits":budget::observation::waits(waits)}))?;
    Ok(sample)
}
