use std::time::Duration;

use latent_core::ActivationId;
use latent_wire::invocation::{proto, InvocationServiceClient};
use serde_json::{json, Value};
use tokio::task::JoinSet;

use super::super::{evidence, node::Node, writer::Writer};
use super::{call, observation, plan::Plan, Result};

fn retained_valid(row: &Value) -> bool {
    if row["valid_response"] == false {
        return false;
    }
    if row["rpc_received"] != true {
        return true;
    }
    let Some(consumption) = row["response"].get("consumption") else {
        return false;
    };
    if row["outcome"] == "success" {
        consumption.is_object()
            && row["retained_status"]["activation_id"] == row["activation_id"]
            && row["retained_status"]["terminal_state"] == "completed"
            && row["retained_status"]["outcome"] == "success"
            && &row["retained_status"]["consumption"] == consumption
    } else {
        row["retained_status"]["grpc_code"] == 5
            || (&row["retained_status"]["consumption"] == consumption
                && row["retained_status"]["code"] == row["response"]["code"])
    }
}

fn record(node: &Node, writer: &mut Writer, mut row: Value) -> Result<bool> {
    let valid = retained_valid(&row);
    if let Some(id) = row["activation_id"]
        .as_str()
        .filter(|_| row["kind"] == "invoke")
    {
        row["backend_timing"] = node
            .owner
            .backend
            .take_invocation_timing(&ActivationId(id.into()))
            .map_or(Value::Null, evidence::timing);
    }
    row["retained_valid"] = json!(valid);
    writer.sample(&row)?;
    Ok(valid)
}

pub(super) async fn sequential(
    node: &mut Node,
    writer: &mut Writer,
    clock: call::Clock,
    phase: &str,
    count: u32,
    release: &str,
) -> Result<()> {
    for index in 0..count {
        node.command(true)?;
        node.command(false)?;
        let mut row = call::invoke(
            node.channel(),
            clock,
            phase.into(),
            index,
            0,
            clock.elapsed(),
            format!("cold-{phase}-{index:04}"),
            release.into(),
            false,
        )
        .await?;
        call::retain(node.channel(), clock, &mut row).await?;
        let success = row["outcome"] == "success";
        if !record(node, writer, row)? || !success {
            return Err("cold baseline or recovery response failed".into());
        }
    }
    Ok(())
}

pub(super) async fn burst(
    node: &mut Node,
    writer: &mut Writer,
    clock: call::Clock,
    plan: &Plan,
    phase: &'static str,
    cold_keys: &[u32],
    releases: &[String],
    cancel: bool,
) -> Result<()> {
    // Complete the large snapshot and its file write before anchoring offers.
    writer.sample(&json!({"kind":"phase-start","phase":phase,
        "observer":observation::snapshot(&node.owner.backend.preparation_observer(),clock)?,
        "node":node.sample(phase)?}))?;
    let anchor_recorded = clock.elapsed();
    let origin = anchor_recorded + 10_000_000;
    let cold_due = origin + plan.cold_offset().as_nanos();
    writer.sample(&json!({"kind":"phase-anchor","phase":phase,"recorded_nanos":anchor_recorded.to_string(),
        "offer_lead_nanos":"10000000","origin_nanos":origin.to_string(),"cold_due_nanos":cold_due.to_string()}))?;
    if clock.elapsed() >= origin {
        return Err("cold schedule anchor write exceeded lead".into());
    }
    let mut offers = Vec::with_capacity(plan.stream() as usize + cold_keys.len());
    for index in 0..plan.stream() {
        offers.push((origin + u128::from(index) * 2_000_000, 0, index, true));
    }
    for (index, key) in cold_keys.iter().enumerate() {
        offers.push((cold_due, *key, u32::try_from(index)?, false));
    }
    offers.sort_by_key(|&(due, key, index, _)| (due, key == 0, index));
    let mut tasks = JoinSet::new();
    let mut warm_active = 0;
    let mut valid = true;
    // Only one fixed burst is retained, bounded by its declared offers + two
    // control records. Status reads cannot pause the offered warm stream.
    let mut pending = Vec::with_capacity(offers.len() + 2);
    let mut task_error = None;
    // Exactly one responsiveness request per burst, independently scheduled.
    node.command(false)?;
    let channel = node.channel();
    tasks.spawn(async move {
        tokio::time::sleep_until((clock.origin+Duration::from_nanos(u64::try_from(cold_due+2_000_000)?)).into()).await;
        let started = clock.elapsed();
        let id = format!("cold-{phase}-cold-0000");
        let status = InvocationServiceClient::new(channel).get_activation(call::auth(
            proto::GetActivationRequest{activation_id:id.clone()},Duration::from_secs(5))?).await;
        Ok::<_,Box<dyn std::error::Error+Send+Sync>>((json!({"kind":"status-probe","phase":phase,
            "activation_id":id,"started_nanos":started.to_string(),"finished_nanos":clock.elapsed().to_string(),
            "response":call::status(status)}),false))
    });
    if cancel {
        for _ in 0..4 {
            node.command(false)?;
        }
        let observer = node.owner.backend.preparation_observer();
        let channel = node.channel();
        let release = releases[7].clone();
        tasks.spawn(async move {
            let trigger = observation::compilation(observer,release,clock).await?;
            let mut responses = Vec::with_capacity(4);
            for index in 0..4 {
                let id = format!("cold-{phase}-cold-{index:04}");
                let started = clock.elapsed();
                let response = InvocationServiceClient::new(channel.clone()).cancel(call::auth(
                    proto::CancelRequest{activation_id:id.clone(),reason:"fixed cold comparison cancellation".into()},Duration::from_secs(5))?).await;
                let response = match response { Ok(response)=> {let response=response.into_inner();
                    json!({"grpc_code":0,"disposition":response.disposition,"terminal_state":response.terminal_state})},
                    Err(error)=>json!({"grpc_code":error.code() as i32}) };
                responses.push(json!({"activation_id":id,"started_nanos":started.to_string(),
                    "finished_nanos":clock.elapsed().to_string(),"response":response}));
            }
            Ok((json!({"kind":"cancellation","phase":phase,"trigger":trigger,"commands":responses}),false))
        });
    }
    for (due, key, index, warm) in offers {
        tokio::time::sleep_until((clock.origin + Duration::from_nanos(u64::try_from(due)?)).into())
            .await;
        while let Some(result) = tasks.try_join_next() {
            accept(result, &mut pending, &mut warm_active, &mut task_error);
        }
        node.command(true)?;
        node.command(false)?;
        let overload = warm && warm_active >= 16;
        if warm && !overload {
            warm_active += 1;
        }
        let channel = node.channel();
        let release = releases[key as usize].clone();
        let id = format!(
            "cold-{phase}-{}-{index:04}",
            if warm { "warm" } else { "cold" }
        );
        if overload {
            pending.push(
                call::invoke(
                    channel,
                    clock,
                    phase.into(),
                    index,
                    key,
                    due,
                    id,
                    release,
                    true,
                )
                .await?,
            );
        } else {
            tasks.spawn(async move {
                Ok((
                    call::invoke(
                        channel,
                        clock,
                        phase.into(),
                        index,
                        key,
                        due,
                        id,
                        release,
                        false,
                    )
                    .await?,
                    warm,
                ))
            });
        }
    }
    while let Some(result) = tasks.join_next().await {
        accept(result, &mut pending, &mut warm_active, &mut task_error);
    }
    for mut row in pending {
        if row["kind"] == "invoke" {
            call::retain(node.channel(), clock, &mut row).await?;
        }
        valid &= record(node, writer, row)?;
    }
    let drained = observation::drain(&node.owner.backend.preparation_observer(), clock).await?;
    let sample = node.sample(phase)?;
    super::super::super::soak::assert_idle(&sample)?;
    writer.sample(
        &json!({"kind":"phase-end","phase":phase,"finished_nanos":clock.elapsed().to_string(),
        "observer":drained,"node":sample}),
    )?;
    if !valid {
        return Err("cold retained response association failed".into());
    }
    if let Some(error) = task_error {
        return Err(error);
    }
    Ok(())
}

fn accept(
    result: std::result::Result<Result<(Value, bool)>, tokio::task::JoinError>,
    pending: &mut Vec<Value>,
    warm_active: &mut usize,
    error: &mut Option<Box<dyn std::error::Error + Send + Sync>>,
) {
    match result {
        Ok(Ok((row, warm))) => {
            if warm {
                *warm_active -= 1;
            }
            pending.push(row);
        }
        Ok(Err(value)) => {
            if error.is_none() {
                *error = Some(value);
            }
        }
        Err(value) => {
            if error.is_none() {
                *error = Some(value.into());
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn retained_success_cannot_borrow_another_identity_or_accounting() {
        let mut row = json!({"kind":"invoke","activation_id":"first","rpc_received":true,
            "valid_response":true,"outcome":"success","response":{"consumption":{"cpu_fuel":"10"}},
            "retained_status":{"activation_id":"first","terminal_state":"completed","outcome":"success",
                "consumption":{"cpu_fuel":"10"}}});
        assert!(retained_valid(&row));
        row["retained_status"]["activation_id"] = json!("second");
        assert!(!retained_valid(&row));
        row["retained_status"]["activation_id"] = json!("first");
        row["retained_status"]["consumption"]["cpu_fuel"] = json!("9");
        assert!(!retained_valid(&row));
        row["retained_status"]["consumption"] = Value::Null;
        row["response"]["consumption"] = Value::Null;
        assert!(!retained_valid(&row));
    }
}
