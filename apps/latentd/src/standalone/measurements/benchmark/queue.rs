use std::time::{Duration, Instant};

use latent_wire::invocation::proto;
use serde_json::json;
use tokio::sync::watch;

use super::super::soak::{finish, wait_running};
use super::scheduling;
use super::{
    write_batch, write_call, Case, MeasurementNode, MeasurementWriter, Observation, Result,
};

pub(super) async fn sample(
    node: &MeasurementNode,
    writer: &mut MeasurementWriter,
    index: u32,
) -> Result<()> {
    let first = format!("bench-queue-{index}-holder-0");
    let second = format!("bench-queue-{index}-holder-1");
    let ids = [
        format!("bench-queue-{index}-waiter-0"),
        format!("bench-queue-{index}-waiter-1"),
        format!("bench-queue-{index}-waiter-2"),
    ];
    let (release, ready) = watch::channel(false);
    let first_id = first.as_str();
    let second_id = second.as_str();
    // The control future owns the sender: failure before release closes the
    // channel and wakes every unsubmitted waiter instead of stranding the join.
    let control = async move {
        wait_running(node, "tests", first_id).await?;
        wait_running(node, "tests", second_id).await?;
        release.send(true)?;
        let observed = wait_queue(node).await?;
        for id in [first_id, second_id] {
            let cancelled = node
                .cancel("tests", id, "measurement queue release")
                .await?;
            if cancelled.disposition != proto::CancelDisposition::Accepted as i32 {
                return Err("queue holder cancellation was not accepted".into());
            }
        }
        Ok::<_, Box<dyn std::error::Error + Send + Sync>>(observed)
    };
    let scheduling_before = scheduling::snapshot(node);
    let started = Instant::now();
    let (first_result, second_result, left, middle, right, observed) = tokio::join!(
        invocation(node, Case::Cancel, &first, None),
        invocation(node, Case::Cancel, &second, None),
        invocation(node, Case::Echo, &ids[0], Some(ready.clone())),
        invocation(node, Case::Echo, &ids[1], Some(ready.clone())),
        invocation(node, Case::Echo, &ids[2], Some(ready)),
        control
    );
    let elapsed = started.elapsed();
    writer.write("benchmark-queue",&json!({"sample":index.to_string(),"active_before_release":"2","queued_before_release":"3","resources":observed?}))?;
    for observation in [first_result?, second_result?, left?, middle?, right?] {
        write_call(writer, "cancel_released_queue_rpc", index, &observation)?;
    }
    let scheduling = scheduling::complete(node, scheduling_before, 5)?;
    write_batch(
        writer,
        "cancel_released_queue_rpc",
        index,
        elapsed,
        5,
        2,
        &scheduling,
    )?;
    Ok(())
}

async fn invocation(
    node: &MeasurementNode,
    case: Case,
    id: &str,
    ready: Option<watch::Receiver<bool>>,
) -> Result<Observation> {
    if let Some(mut ready) = ready {
        ready.wait_for(|value| *value).await?;
    }
    let (fixture, request) = case.request(node, id);
    let started = Instant::now();
    let response = node.invoke(&fixture.tenant, request).await?;
    finish(
        node,
        case,
        id,
        &fixture.tenant,
        response,
        u64::try_from(started.elapsed().as_micros())?,
    )
    .await
}

async fn wait_queue(node: &MeasurementNode) -> Result<serde_json::Value> {
    let deadline = Instant::now() + Duration::from_secs(2);
    for _ in 0..200 {
        let sample = node.sample("queue-before-release")?;
        let cells = sample["inventory"]["cellCapacity"]
            .as_array()
            .ok_or("missing queue inventory")?;
        if cells.len() == 1 && cells[0]["active"] == 2 && cells[0]["queueDepth"] == 3 {
            return Ok(sample);
        }
        if Instant::now() >= deadline {
            break;
        }
        tokio::time::sleep(Duration::from_millis(1)).await;
    }
    Err("actual bounded queue occupancy was not observed".into())
}
