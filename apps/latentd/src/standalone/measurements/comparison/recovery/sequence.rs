use super::{
    budget::call::{self, Offer},
    cold::call::Clock,
    evidence, plan, Node, Result, Writer,
};
use latent_core::{DeadlineDiagnosticObserver, DeadlineWaitObserver};
use latent_wire::invocation::{proto, InvocationServiceClient};
use serde_json::{json, Value};
use std::time::Duration;
use tokio::task::JoinHandle;

type Reply = std::result::Result<tonic::Response<proto::InvokeResponse>, tonic::Status>;

struct Job(Option<JoinHandle<Reply>>);
impl Job {
    fn start(
        channel: tonic::transport::Channel,
        request: tonic::Request<proto::InvokeRequest>,
    ) -> Self {
        Self(Some(tokio::spawn(async move {
            InvocationServiceClient::new(channel).invoke(request).await
        })))
    }
    fn finished(&self) -> bool {
        self.0.as_ref().is_none_or(JoinHandle::is_finished)
    }
    async fn result(&mut self) -> Result<Reply> {
        let result = self.0.as_mut().expect("owned recovery call").await;
        self.0.take();
        Ok(result?)
    }
    async fn disconnect(&mut self, clock: Clock) -> Result<(Value, Option<Reply>)> {
        let started = clock.elapsed();
        let task = self.0.as_mut().expect("owned recovery call");
        task.abort();
        let result = task.await;
        let finished = clock.elapsed();
        self.0.take();
        // A completed response can race abort. Retain it explicitly instead of
        // pretending every abort request destroyed a still-pending RPC.
        Ok(match result {
            Err(error) if error.is_cancelled() => (
                json!({"requested_nanos":started.to_string(),"joined_nanos":finished.to_string(),"aborted":true}),
                None,
            ),
            Ok(response) => (
                json!({"requested_nanos":started.to_string(),"joined_nanos":finished.to_string(),"aborted":false}),
                Some(response),
            ),
            Err(error) => return Err(error.into()),
        })
    }
}
impl Drop for Job {
    fn drop(&mut self) {
        if let Some(task) = self.0.take() {
            task.abort();
        }
    }
}

#[derive(Default)]
pub(super) struct State {
    pub offers: Vec<Value>,
    pub controls: u64,
    pub recovery_healthy: bool,
}

async fn trigger(
    job: &Job,
    observer: &DeadlineDiagnosticObserver,
    id: &str,
    clock: Clock,
) -> Value {
    let deadline = tokio::time::Instant::now() + Duration::from_millis(250);
    for _ in 0..256 {
        let found = evidence::running(observer, id, clock);
        if !found.is_null() {
            return found;
        }
        if job.finished() || tokio::time::Instant::now() >= deadline {
            break;
        }
        tokio::time::sleep(Duration::from_millis(1)).await;
    }
    Value::Null
}

async fn call_one(
    node: &mut Node,
    clock: Clock,
    observer: &DeadlineDiagnosticObserver,
    case: plan::Case,
    offer: &Offer,
    controls: &mut u64,
    writer: &mut Writer,
) -> Result<Value> {
    let (request, mut row) = call::request(offer, clock)?;
    row["round"] = json!(case.round.to_string());
    row["running_witness"] = Value::Null;
    row["disconnect"] = Value::Null;
    row["cancel_response"] = Value::Null;
    let mut job = Job::start(node.channel(), request);
    if case.name == "disconnect" {
        let scheduled = row["scheduled_nanos"]
            .as_str()
            .ok_or("recovery schedule")?
            .parse::<u128>()?
            + u128::from(case.budget) * 500_000;
        row["disconnect_scheduled_nanos"] = json!(scheduled.to_string());
        let target = tokio::time::Instant::from_std(clock.origin)
            + Duration::from_nanos(u64::try_from(scheduled)?);
        tokio::select! {
            biased;
            response=job.result() => return Ok(call::response(offer,clock,row,response?)),
            ()=tokio::time::sleep_until(target) => {}
        }
        row["running_witness"] = evidence::running(observer, &offer.id(), clock);
    } else {
        row["disconnect_scheduled_nanos"] = Value::Null;
        if matches!(case.name, "running-disconnect" | "positive-cancel") {
            row["running_witness"] = trigger(&job, observer, &offer.id(), clock).await;
            if case.name == "positive-cancel" {
                row["cancel_response"] = evidence::cancel(
                    node,
                    &offer.id(),
                    clock,
                    *controls,
                    &row["running_witness"],
                    writer,
                )
                .await?;
                *controls += 1;
            }
        }
    }
    if matches!(case.name, "disconnect" | "running-disconnect") && !job.finished() {
        let (disconnect, response) = job.disconnect(clock).await?;
        row["disconnect"] = disconnect;
        if let Some(response) = response {
            return Ok(call::response(offer, clock, row, response));
        }
        row["outcome"] = json!("client-disconnected");
        row["valid_response"] = json!(false);
        let completed = clock.elapsed();
        let deadline = row["deadline_nanos"]
            .as_str()
            .ok_or("recovery deadline")?
            .parse::<u128>()?;
        row["completed_nanos"] = json!(completed.to_string());
        row["overshoot_nanos"] = json!(completed.saturating_sub(deadline).to_string());
        Ok(row)
    } else {
        Ok(call::response(offer, clock, row, job.result().await?))
    }
}

pub(super) async fn run(
    node: &mut Node,
    clock: Clock,
    observer: &DeadlineDiagnosticObserver,
    waits: &DeadlineWaitObserver,
    writer: &mut Writer,
    state: &mut State,
) -> Result<()> {
    state.recovery_healthy = true;
    for (index, case) in plan::cases().into_iter().enumerate() {
        let ordinal = u32::try_from(index)?;
        let offer = Offer {
            ordinal,
            case: case.name,
            budget_millis: case.budget,
            function: case.function,
            release: node.fixture.release_digest.clone(),
        };
        node.command(true)?;
        // Retain a bounded failure marker before any dispatch. Normal transport
        // errors become complete rows; a collector panic/error cannot erase an
        // attempt already counted by the node command owner.
        state.offers.push(json!({"kind":"invoke","ordinal":ordinal.to_string(),"case":case.name,
            "activation_id":offer.id(),"budget_millis":case.budget.to_string(),"round":case.round.to_string(),
            "function":case.function,"outcome":"collector-incomplete","started_nanos":clock.elapsed().to_string()}));
        let mut row = call_one(
            node,
            clock,
            observer,
            case,
            &offer,
            &mut state.controls,
            writer,
        )
        .await?;
        state.offers[index] = row.clone();
        row["running_witness_final"] = evidence::running(observer, &offer.id(), clock);
        row["acknowledgement"] = evidence::acknowledgement(observer, &offer.id(), clock).await;
        row["diagnostic_token"] = json!(observer
            .token_for_activation(&offer.id())
            .map(|token| token.id().to_string()));
        let (status, status_observed_at) =
            evidence::status(node, &offer.id(), clock, state.controls, writer).await?;
        state.controls += 1;
        row["retained_status"] = status;
        row["retained_observed_nanos"] = json!(status_observed_at.to_string());
        row["cleanup_log"] = evidence::cleanup_log(node, &offer.id()).await?;
        let sample = evidence::checkpoint(node, clock, waits, ordinal, writer)?;
        if case.function == "identify" {
            let cells = sample["inventory"]["cellCapacity"]
                .as_array()
                .ok_or("recovery cell inventory")?;
            state.recovery_healthy &= row["outcome"] == "success"
                && row["valid_response"] == true
                && cells.iter().all(|cell| {
                    cell["quarantined"] == 0
                        && cell["active"] == 0
                        && cell["available"] == cell["total"]
                });
        }
        if case.name == "running-disconnect" {
            state.recovery_healthy &=
                !row["running_witness"].is_null() && row["disconnect"]["aborted"] == true;
        }
        if case.name == "positive-cancel" {
            state.recovery_healthy &=
                !row["running_witness"].is_null() && row["cancel_response"]["disposition"] == 1;
        }
        state.offers[index] = row;
    }
    Ok(())
}
