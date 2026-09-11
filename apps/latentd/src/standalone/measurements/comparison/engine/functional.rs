use super::{
    call::{self, Offer},
    fixture::DIRTY,
    observation,
    sequence::State,
    Clock, Node, Result, Writer,
};
use latent_core::{
    ActivationPhase, DeadlineDiagnosticObservation as Event, DeadlineDiagnosticObserver,
};
use latent_scheduler::CellClass;
use serde_json::{json, Value};
use std::time::Duration;

fn offer(state: &State, ordinal: u32, clock: Clock) -> Result<Offer> {
    let (target, function, payload, expected, grant, code) = match ordinal {
        1 | 2 => (
            if ordinal == 1 { 4 } else { 5 },
            "snapshot",
            json!([]),
            None,
            "G",
            None,
        ),
        3 | 4 => (
            if ordinal == 3 { 4 } else { 5 },
            "clocks",
            json!([]),
            None,
            "G",
            None,
        ),
        5 | 6 => {
            let m = if ordinal == 5 { "a" } else { "b" };
            (
                if ordinal == 5 { 4 } else { 5 },
                "log-probe",
                json!([format!("engine-log-{m}"),[{"name":"probe","value":m}]]),
                None,
                "G",
                None,
            )
        }
        7 | 8 | 12 | 14 | 16 | 24 => (
            if matches!(ordinal, 7 | 14) { 2 } else { 3 },
            "bump",
            json!([]),
            Some(json!([1])),
            "G",
            None,
        ),
        9 => (6, "run", json!(["trap"]), None, "R", Some("guest-trap")),
        10 | 18 => (
            if ordinal == 10 { 6 } else { 7 },
            "run",
            json!(["success"]),
            Some(json!([692_060_160])),
            "R",
            None,
        ),
        11 => (2, "spin", json!([]), None, "F", Some("resource-exhausted")),
        13 => (3, "grow", json!([]), None, "M", Some("resource-exhausted")),
        15 => (2, "spin", json!([]), None, "D", Some("deadline-exceeded")),
        17 => (7, "run", json!(["cancel"]), None, "C", Some("cancelled")),
        19..=22 => (
            if ordinal % 2 == 1 { 2 } else { 3 },
            "spin",
            json!([]),
            None,
            "H",
            Some("cancelled"),
        ),
        23 => (2, "identify", json!([]), Some(json!([11])), "G", None),
        _ => return Err("engine functional ordinal".into()),
    };
    Ok(Offer {
        ordinal: 0,
        command_ordinal: 0,
        phase: "functional".into(),
        phase_kind: "functional".into(),
        index: ordinal - 1,
        id: format!("engine-fn-{ordinal:02}"),
        target: state.targets[target].clone(),
        function: function.into(),
        payload,
        expected,
        grant: call::grant(grant),
        expected_code: code,
        scheduled: clock.elapsed(),
    })
}

pub(super) async fn run(
    state: &mut State,
    node: &mut Node,
    clock: Clock,
    observer: &DeadlineDiagnosticObserver,
    writer: &mut Writer,
) -> Result<()> {
    for ordinal in 1..=18 {
        let offer = offer(state, ordinal, clock)?;
        let index = state.start(node, clock, offer.clone())?;
        if ordinal == 15 {
            state.passed &= witness(
                state,
                node,
                clock,
                observer,
                &[(index, &offer)],
                "functional-running",
                writer,
            )
            .await?;
        }
        if ordinal == 17 {
            state.passed &= witness(
                state,
                node,
                clock,
                observer,
                &[(index, &offer)],
                "memory-dirty",
                writer,
            )
            .await?;
            state.cancel(node, clock, &offer, writer).await?;
        }
        state
            .finish(index, node, clock, &offer, observer, writer)
            .await?;
        idle(
            state,
            node,
            clock,
            &format!("functional-{ordinal:02}"),
            writer,
        )?;
    }
    let mut holders = Vec::with_capacity(4);
    for ordinal in 19..=22 {
        let offer = offer(state, ordinal, clock)?;
        let index = state.start(node, clock, offer.clone())?;
        holders.push((index, offer));
    }
    let refs = holders
        .iter()
        .map(|(index, offer)| (*index, offer))
        .collect::<Vec<_>>();
    state.passed &= witness(state, node, clock, observer, &refs, "four-live", writer).await?;
    let queued = offer(state, 23, clock)?;
    let queued_index = state.start(node, clock, queued.clone())?;
    let mut refs = holders
        .iter()
        .map(|(index, offer)| (*index, offer))
        .collect::<Vec<_>>();
    refs.push((queued_index, &queued));
    state.passed &= witness(state, node, clock, observer, &refs, "fifth-queued", writer).await?;
    state.cancel(node, clock, &holders[0].1, writer).await?;
    state
        .finish(holders[0].0, node, clock, &holders[0].1, observer, writer)
        .await?;
    state
        .finish(queued_index, node, clock, &queued, observer, writer)
        .await?;
    let refs = holders[1..]
        .iter()
        .map(|(index, offer)| (*index, offer))
        .collect::<Vec<_>>();
    state.passed &= witness(state, node, clock, observer, &refs, "three-live", writer).await?;
    for (index, offer) in &holders[1..] {
        state.cancel(node, clock, offer, writer).await?;
        state
            .finish(*index, node, clock, offer, observer, writer)
            .await?;
    }
    idle(state, node, clock, "functional-holders-drained", writer)?;
    let final_offer = offer(state, 24, clock)?;
    let index = state.start(node, clock, final_offer.clone())?;
    state
        .finish(index, node, clock, &final_offer, observer, writer)
        .await?;
    idle(state, node, clock, "functional-final", writer)?;
    state.passed &= state.functional_logs == 10;
    Ok(())
}
fn idle(
    state: &mut State,
    node: &Node,
    clock: Clock,
    label: &str,
    writer: &mut Writer,
) -> Result<()> {
    let sample = node.sample(label)?;
    state.passed &= super::super::super::soak::assert_idle(&sample).is_ok();
    writer.sample(&json!({"kind":"proof","label":label,"observed_nanos":clock.elapsed().to_string(),"node":sample,"native":observation::native(node)}))
}

fn running(observer: &DeadlineDiagnosticObserver, id: &str) -> Option<u64> {
    let snapshot = observer.snapshot();
    let token = snapshot
        .identities
        .iter()
        .find(|v| v.activation_id.as_deref() == Some(id))?
        .token;
    snapshot
        .records
        .iter()
        .find(|r| {
            r.token == token
                && matches!(
                    r.observation,
                    Event::LifecyclePhase {
                        phase: ActivationPhase::Running,
                        ..
                    }
                )
        })
        .map(|r| r.sequence)
}
async fn witness(
    state: &State,
    node: &Node,
    clock: Clock,
    observer: &DeadlineDiagnosticObserver,
    jobs: &[(usize, &Offer)],
    label: &str,
    writer: &mut Writer,
) -> Result<bool> {
    let began = clock.elapsed();
    let maximum = if label == "fifth-queued" { 250 } else { 500 };
    let cutoff = tokio::time::Instant::now() + Duration::from_millis(maximum);
    let baseline = node.owner.backend.resource_snapshot().stores_created;
    let mut matched = false;
    let mut captured = Value::Null;
    for _ in 0..=maximum {
        let started = clock.elapsed();
        let native = node.owner.backend.resource_snapshot();
        let scheduler = node.owner.scheduler.observations(CellClass::Standard);
        let rows=jobs.iter().map(|(index,offer)|json!({"activation_id":offer.id,"pending":state.pending(*index),"running_sequence":running(observer,&offer.id).map(|n|n.to_string())})).collect::<Vec<_>>();
        let all_pending = rows.iter().all(|row| row["pending"] == true);
        let all_running = rows.iter().all(|row| !row["running_sequence"].is_null());
        let dirty = if label == "memory-dirty" {
            super::oracle::logs(node, &jobs[0].1.id)?
        } else {
            Vec::new()
        };
        matched = match label {
            "memory-dirty" => all_pending && dirty.iter().any(|v| v["record"]["message"] == DIRTY),
            "fifth-queued" => {
                all_pending
                    && scheduler.queue_depth == 1
                    && scheduler.active_leases == 4
                    && native.live_stores == 4
                    && native.live_component_instances == 4
                    && native.stores_created == baseline
            }
            _ => {
                all_pending
                    && all_running
                    && native.live_stores == jobs.len() as u64
                    && native.live_component_instances == jobs.len() as u64
                    && native.live_cancellation_probes == jobs.len() as u64
                    && scheduler.active_leases == u32::try_from(jobs.len())?
            }
        };
        captured = json!({"collector_started_nanos":started.to_string(),"collector_finished_nanos":clock.elapsed().to_string(),"jobs":rows,"native":observation::native_snapshot(&native),"scheduler":{"queue_depth":scheduler.queue_depth.to_string(),"active_leases":scheduler.active_leases.to_string()},"guest_logs":dirty,"baseline_stores_created":baseline.to_string()});
        if matched || !all_pending || tokio::time::Instant::now() >= cutoff {
            break;
        }
        tokio::time::sleep_until(
            (tokio::time::Instant::now() + Duration::from_millis(1)).min(cutoff),
        )
        .await;
    }
    writer.sample(&json!({"kind":"proof","label":label,"started_nanos":began.to_string(),"finished_nanos":clock.elapsed().to_string(),"maximum_millis":maximum.to_string(),"matched":matched,"observation":captured}))?;
    Ok(matched)
}
