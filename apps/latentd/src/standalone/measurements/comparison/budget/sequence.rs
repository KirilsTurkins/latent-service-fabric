use std::time::Duration;

use latent_core::{
    ActivationPhase, DeadlineDiagnosticObservation as Event, DeadlineDiagnosticObserver,
    DeadlineWaitObserver,
};
use latent_scheduler::CellClass;
use latent_wire::invocation::{proto, InvocationServiceClient};
use serde_json::{json, Value};

use super::{
    call::{self, Offer},
    cold::call::{auth, Clock},
    delayed, observation, Node, Result, Writer,
};

#[derive(Default)]
pub(super) struct State {
    pub controls: u64,
    pub offers: Vec<Value>,
}

struct Job(Option<tokio::task::JoinHandle<Result<Value>>>);
impl Job {
    fn start(node: &mut Node, clock: Clock, offer: Offer) -> Result<Self> {
        node.command(true)?;
        Ok(Self(Some(tokio::spawn(call::invoke(
            node.channel(),
            clock,
            offer,
        )))))
    }
    fn finished(&self) -> bool {
        self.0
            .as_ref()
            .is_none_or(tokio::task::JoinHandle::is_finished)
    }
    async fn finish(mut self) -> Result<Value> {
        // Retain the handle in the abort guard across suspension. Taking it
        // before awaiting would detach the task if this future were cancelled.
        let result = self.0.as_mut().expect("owned invoke").await;
        self.0.take();
        result?
    }
}
impl Drop for Job {
    fn drop(&mut self) {
        if let Some(job) = self.0.take() {
            job.abort();
        }
    }
}

fn event(observer: &DeadlineDiagnosticObserver, id: &str, terminal: bool) -> Option<u64> {
    let snapshot = observer.snapshot();
    let token = snapshot
        .identities
        .iter()
        .find(|identity| identity.activation_id.as_deref() == Some(id))?
        .token;
    snapshot
        .records
        .iter()
        .find(|record| {
            record.token == token
                && if terminal {
                    matches!(record.observation, Event::TerminalWinner { .. })
                } else {
                    matches!(
                        record.observation,
                        Event::LifecyclePhase {
                            phase: ActivationPhase::Running,
                            ..
                        }
                    )
                }
        })
        .map(|record| record.sequence)
}

async fn running(
    observer: &DeadlineDiagnosticObserver,
    id: &str,
    job: &Job,
    clock: Clock,
) -> Value {
    for _ in 0..128 {
        if let Some(sequence) = event(observer, id, false) {
            return json!({"observed_nanos":clock.elapsed().to_string(),"phase_record_sequence":sequence.to_string()});
        }
        if job.finished() {
            break;
        }
        tokio::time::sleep(Duration::from_millis(1)).await;
    }
    Value::Null
}

fn offer(
    ordinal: u32,
    case: &'static str,
    budget_millis: u64,
    function: &'static str,
    node: &Node,
) -> Offer {
    Offer {
        ordinal,
        case,
        budget_millis,
        function,
        release: node.fixture.release_digest.clone(),
    }
}

impl State {
    fn command(&mut self, node: &mut Node) -> Result<u64> {
        if self.controls >= 128 {
            return Err("budget diagnostic command cap".into());
        }
        node.command(false)?;
        let ordinal = self.controls;
        self.controls += 1;
        Ok(ordinal)
    }

    async fn retain(
        &mut self,
        node: &mut Node,
        clock: Clock,
        observer: &DeadlineDiagnosticObserver,
        mut row: Value,
        writer: &mut Writer,
    ) -> Result<()> {
        let id = row["activation_id"]
            .as_str()
            .ok_or("offer identity")?
            .to_owned();
        if row["diagnostic_token"].is_null() {
            row["diagnostic_token"] = json!(observer
                .token_for_activation(&id)
                .map(|token| token.id().to_string()));
        }
        // Allow an already-interrupted owner to publish before the single status RPC.
        for _ in 0..64 {
            if event(observer, &id, true).is_some() || observer.token_for_activation(&id).is_none()
            {
                break;
            }
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
        let ordinal = self.command(node)?;
        let started = clock.elapsed();
        let response = super::cold::call::status(
            InvocationServiceClient::new(node.channel())
                .get_activation(auth(
                    proto::GetActivationRequest {
                        activation_id: id.clone(),
                    },
                    Duration::from_secs(5),
                )?)
                .await,
        );
        let finished = clock.elapsed();
        writer.sample(&json!({"kind":"command","ordinal":ordinal.to_string(),"operation":"status","target":id,
            "started_nanos":started.to_string(),"finished_nanos":finished.to_string(),"response":response,"trigger":Value::Null}))?;
        row["retained_status"] = response;
        row["retained_observed_nanos"] = json!(finished.to_string());
        if self.offers.len() >= 23 {
            return Err("diagnostic offer storage cap".into());
        }
        self.offers.push(row);
        Ok(())
    }

    async fn cancel(
        &mut self,
        node: &mut Node,
        clock: Clock,
        id: &str,
        trigger: Value,
        writer: &mut Writer,
    ) -> Result<Value> {
        let ordinal = self.command(node)?;
        let started = clock.elapsed();
        let result = InvocationServiceClient::new(node.channel())
            .cancel(auth(
                proto::CancelRequest {
                    activation_id: id.to_owned(),
                    reason: "budget diagnostic cancellation".into(),
                },
                Duration::from_secs(5),
            )?)
            .await;
        let finished = clock.elapsed();
        let response = match result {
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
}

pub(super) fn checkpoint(
    node: &Node,
    clock: Clock,
    waits: &DeadlineWaitObserver,
    writer: &mut Writer,
    label: &str,
) -> Result<()> {
    writer.sample(
        &json!({"kind":"checkpoint","label":label,"observed_nanos":clock.elapsed().to_string(),
        "waits":observation::waits(waits),"node":node.sample(label)?}),
    )
}

#[expect(
    clippy::too_many_lines,
    reason = "The fixed 23 offers and their bounded cleanup remain in one auditable sequence."
)]
pub(super) async fn run(
    node: &mut Node,
    clock: Clock,
    observer: &DeadlineDiagnosticObserver,
    waits: &DeadlineWaitObserver,
    writer: &mut Writer,
    state: &mut State,
) -> Result<()> {
    let first = offer(0, "prewarm", 1000, "identify", node);
    let row = Job::start(node, clock, first)?.finish().await?;
    if row["outcome"] != "success" || row["valid_response"] != true {
        return Err("generic diagnostic prewarm failed".into());
    }
    state.retain(node, clock, observer, row, writer).await?;
    checkpoint(node, clock, waits, writer, "after-prewarm")?;
    let mut holders = Vec::with_capacity(4);
    for ordinal in 1..=4 {
        let request = offer(ordinal, "holder", 1000, "spin", node);
        let id = request.id();
        let job = Job::start(node, clock, request)?;
        let trigger = running(observer, &id, &job, clock).await;
        if trigger.is_null() {
            return Err("holder did not reach Running".into());
        }
        holders.push((id, job, trigger));
    }
    for (index, budget) in [1, 2, 5, 10].into_iter().enumerate() {
        let request = offer(
            5 + u32::try_from(index)?,
            "queued",
            budget,
            "identify",
            node,
        );
        let job = Job::start(node, clock, request)?;
        let mut witness = Value::Null;
        for _ in 0..128 {
            let started = clock.elapsed();
            let snapshot = node.owner.scheduler.observations(CellClass::Standard);
            let finished = clock.elapsed();
            if snapshot.queue_depth == 1
                && snapshot.active_leases == 4
                && holders
                    .iter()
                    .all(|(id, job, _)| !job.finished() && event(observer, id, true).is_none())
            {
                witness = json!({"started_nanos":started.to_string(),"finished_nanos":finished.to_string(),
                    "queue_depth":snapshot.queue_depth,"active_leases":snapshot.active_leases,
                    "holder_ids":holders.iter().map(|(id,_,_)|id).collect::<Vec<_>>()});
                break;
            }
            if job.finished() {
                break;
            }
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
        let mut row = job.finish().await?;
        row["queue_witness"] = witness;
        state.retain(node, clock, observer, row, writer).await?;
    }
    for (id, job, trigger) in holders {
        state.cancel(node, clock, &id, trigger, writer).await?;
        state
            .retain(node, clock, observer, job.finish().await?, writer)
            .await?;
    }
    checkpoint(node, clock, waits, writer, "after-queued")?;
    for (index, budget) in [1, 2, 5, 10].into_iter().enumerate() {
        let request = offer(
            9 + u32::try_from(index)?,
            "delayed-body",
            budget,
            "identify",
            node,
        );
        node.command(true)?;
        let row = delayed::invoke(node.channel(), clock, request, observer).await?;
        state.retain(node, clock, observer, row, writer).await?;
    }
    checkpoint(node, clock, waits, writer, "after-delayed-body")?;
    for (index, budget) in [1, 2, 5, 10].into_iter().enumerate() {
        let request = offer(13 + u32::try_from(index)?, "runaway", budget, "spin", node);
        let row = Job::start(node, clock, request)?.finish().await?;
        state.retain(node, clock, observer, row, writer).await?;
    }
    checkpoint(node, clock, waits, writer, "after-runaway")?;
    for (index, budget) in [1, 2, 5, 10, 1000].into_iter().enumerate() {
        let request = offer(
            17 + u32::try_from(index)?,
            if budget == 1000 {
                "positive-cancel"
            } else {
                "cancel"
            },
            budget,
            "spin",
            node,
        );
        let id = request.id();
        let job = Job::start(node, clock, request)?;
        let trigger = running(observer, &id, &job, clock).await;
        let response = state
            .cancel(node, clock, &id, trigger.clone(), writer)
            .await?;
        if budget == 1000
            && (trigger.is_null()
                || response["disposition"] != proto::CancelDisposition::Accepted as i32)
        {
            return Err("positive running cancellation was not accepted".into());
        }
        state
            .retain(node, clock, observer, job.finish().await?, writer)
            .await?;
    }
    checkpoint(node, clock, waits, writer, "after-cancellation")?;
    let last = offer(22, "recovery", 1000, "identify", node);
    let row = Job::start(node, clock, last)?.finish().await?;
    if row["outcome"] != "success" || row["valid_response"] != true {
        return Err("generic diagnostic recovery failed".into());
    }
    state.retain(node, clock, observer, row, writer).await?;
    checkpoint(node, clock, waits, writer, "after-recovery")?;
    Ok(())
}
