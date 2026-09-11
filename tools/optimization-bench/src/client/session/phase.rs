use std::{
    sync::Arc,
    time::{Instant, SystemTime, UNIX_EPOCH},
};

use serde_json::{json, Value};
use tokio::task::JoinSet;
use tonic::{
    metadata::{Ascii, MetadataValue},
    transport::Channel,
};

use super::{
    super::{
        call::{self, Context, Offer},
        record::{Attempt, Counts},
    },
    nanos,
    output::Output,
    plan::{Group, Phase, Plan, Target, PREFIX},
    Result,
};

pub struct Clock {
    origin: Instant,
    unix_nanos: u128,
    uncertainty: u64,
}

impl Clock {
    fn sample() -> Result<Self> {
        let before = Instant::now();
        let unix_nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| "wall-clock-unavailable")?
            .as_nanos();
        let origin = Instant::now();
        Ok(Self {
            origin,
            unix_nanos,
            uncertainty: nanos(origin.duration_since(before)),
        })
    }

    fn offer(&self, phase: Phase, index: u32) -> Result<Offer> {
        let scheduled = nanos(self.origin.elapsed());
        let deadline = scheduled
            .checked_add(1_000_000_000)
            .ok_or("deadline-overflow")?;
        let exact = self.unix_nanos + u128::from(deadline);
        let absolute = exact.div_ceil(1_000_000);
        Ok(Offer {
            phase: if phase.kind == "warmup" {
                "warmup"
            } else {
                "measured"
            },
            index,
            origin: self.origin,
            scheduled,
            absolute_deadline: u64::try_from(absolute).map_err(|_| "deadline-overflow")?,
            deadline,
            quantization: u64::try_from(absolute * 1_000_000 - exact)
                .map_err(|_| "deadline-overflow")?,
        })
    }
}

pub struct Inputs<'a> {
    pub plan: &'a Plan,
    pub group: Group,
    pub phase: Phase,
    pub targets: &'a [Target],
    pub channels: &'a [Channel],
    pub authorization: &'a MetadataValue<Ascii>,
    pub command: u32,
    pub session_started: Instant,
    pub deadline: Instant,
}

pub struct State {
    pub offers: u64,
    pub first_response: bool,
}

struct Completed {
    index: u32,
    target: usize,
    global: u64,
    row: Attempt,
}

pub async fn run(inputs: Inputs<'_>, output: &mut Output, state: &mut State) -> Result<Value> {
    let mut contexts = Vec::with_capacity(inputs.targets.len());
    for (target, channel) in inputs.targets.iter().zip(inputs.channels) {
        let plan = inputs.plan.invocation(inputs.group, inputs.phase, target);
        let prepared = plan.prepare()?;
        contexts.push(Arc::new(Context {
            plan,
            prepared,
            channel: channel.clone(),
            authorization: inputs.authorization.clone(),
        }));
    }
    let reference = &contexts[0];
    let request = json!({"tenant":reference.plan.tenant,"contract":reference.plan.contract,
        "function":reference.plan.function,"route":reference.plan.route,
        "cpu_fuel":reference.plan.cpu_fuel.to_string(),"memory_bytes":reference.plan.memory_bytes.to_string(),
        "log_bytes":reference.plan.log_bytes.to_string(),"budget_millis":reference.plan.budget_millis.to_string(),
        "response_timeout_millis":reference.plan.response_timeout_millis.to_string(),
        "payload_sha256":super::super::record::digest(&reference.prepared.payload),
        "payload_bytes":reference.prepared.payload.len().to_string(),
        "expected_output_sha256":super::super::record::digest(&reference.prepared.expected),
        "expected_output_bytes":reference.prepared.expected.len().to_string()});
    let clock = Clock::sample()?;
    let mut pending = JoinSet::new();
    let mut counts = Counts::default();
    let mut offered = 0;
    let mut error = None;
    while offered < inputs.phase.offers || !pending.is_empty() {
        if Instant::now() >= inputs.deadline {
            error.get_or_insert("session-phase-deadline");
        }
        while error.is_none()
            && offered < inputs.phase.offers
            && pending.len() < inputs.phase.concurrency as usize
        {
            let target = offered as usize % inputs.targets.len();
            let offer = match clock.offer(inputs.phase, offered) {
                Ok(offer) => offer,
                Err(reason) => {
                    error = Some(reason);
                    break;
                }
            };
            let context = Arc::clone(&contexts[target]);
            let index = offered;
            let global = state.offers;
            state.offers += 1;
            offered += 1;
            pending.spawn(async move {
                Completed {
                    index,
                    target,
                    global,
                    row: call::invoke(context, offer).await,
                }
            });
        }
        if pending.is_empty() {
            break;
        }
        match pending.join_next().await {
            Some(Ok(completed)) => {
                counts.observe(&completed.row);
                if let Err(reason) = accept(&inputs, &clock, &completed, output, state) {
                    error.get_or_insert(reason);
                }
            }
            Some(Err(_)) => {
                error.get_or_insert("session-invocation-task-failed");
            }
            None => {
                error.get_or_insert("session-invocation-task-missing");
            }
        }
    }
    // No return above this point owns an outstanding Invoke task. Every started
    // call retains its original 5s outer observation bound while draining.
    let phase_elapsed = nanos(clock.origin.elapsed());
    let complete = error.is_none() && counts.attempts == u64::from(inputs.phase.offers);
    Ok(
        json!({"status":if complete && counts.successful == counts.attempts {"passed"} else {"failed"},
        "reason":error.or(if counts.successful == counts.attempts {None} else {Some("session-phase-outcome")}),
        "phase":{"ordinal":inputs.phase.index,"name":inputs.phase.name,"kind":inputs.phase.kind,
            "function":inputs.phase.function,"offers":inputs.phase.offers,"concurrency":inputs.phase.concurrency},
        "origin_session_nanos":nanos(clock.origin.duration_since(inputs.session_started)).to_string(),
        "origin_unix_nanos":clock.unix_nanos.to_string(),"clock_anchor_uncertainty_nanos":clock.uncertainty.to_string(),
        "phase_elapsed_nanos":phase_elapsed.to_string(),"request":request,"counts":counts.value(),"active_tasks":0}),
    )
}

fn accept(
    inputs: &Inputs<'_>,
    clock: &Clock,
    completed: &Completed,
    output: &mut Output,
    state: &mut State,
) -> Result<()> {
    let target = &inputs.targets[completed.target];
    let envelope = json!({"schema":format!("{PREFIX}attempt.v1"),"pair":inputs.plan.pair,
        "group":inputs.group.index,"arm":inputs.group.arm,"density":inputs.group.density,
        "phase":inputs.phase.index,"phase_name":inputs.phase.name,"phase_kind":inputs.phase.kind,
        "global_ordinal":completed.global,"target_index":completed.target,"owner_ref":target.owner_ref,
        "app_process_id":target.app_process_id,"attempt":completed.row});
    output.attempt(&envelope)?;
    if !state.first_response && completed.row.rpc_received {
        state.first_response = true;
        let response_time = nanos(clock.origin.duration_since(inputs.session_started))
            .checked_add(
                completed
                    .row
                    .completed_nanos
                    .parse::<u64>()
                    .map_err(|_| "session-timestamp")?,
            )
            .ok_or("session-timestamp")?;
        output.event("first-response", Some(inputs.command), &json!({"group":inputs.group.index,
            "phase":inputs.phase.index,"index":completed.index,"global_ordinal":completed.global,
            "target_index":completed.target,"owner_ref":target.owner_ref,"app_process_id":target.app_process_id,
            "activation_id":completed.row.activation_id,"outcome":completed.row.outcome,
            "response_session_nanos":response_time.to_string()}))?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn first_phase_keeps_legacy_attempt_phase_and_deadline_arithmetic() {
        let clock = Clock::sample().unwrap();
        let phase = Phase {
            index: 0,
            name: "first",
            kind: "first",
            function: "echo",
            offers: 32,
            concurrency: 1,
        };
        let offer = clock.offer(phase, 17).unwrap();
        assert_eq!(offer.phase, "measured");
        assert_eq!(offer.index, 17);
        assert_eq!(offer.deadline - offer.scheduled, 1_000_000_000);
        assert!(offer.quantization < 1_000_000);
        assert_eq!(
            u128::from(offer.absolute_deadline) * 1_000_000,
            clock.unix_nanos + u128::from(offer.deadline) + u128::from(offer.quantization)
        );
        let warmup = clock
            .offer(
                Phase {
                    kind: "warmup",
                    ..phase
                },
                0,
            )
            .unwrap();
        assert_eq!(warmup.phase, "warmup");
    }
}
