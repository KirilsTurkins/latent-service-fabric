use std::collections::BTreeMap;
use std::io::Write;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};
use tokio::task::JoinSet;
use tonic::{metadata::MetadataValue, transport::Endpoint};

use super::{
    call::{self, Context, Offer},
    nanos,
    output::Output,
    plan::{Plan, Prepared, Schedule},
    record::{digest, Attempt, Counts},
    unix_millis, Result,
};

const OBSERVATION_HOLD_MILLIS: u64 = 100;

pub(super) async fn run(
    plan: Plan,
    prepared: Prepared,
    token: &str,
    output_path: PathBuf,
    plan_digest: String,
    started: Instant,
    started_unix: u64,
) -> Result<()> {
    let mut output = Output::new(output_path, plan.maximum_output_bytes)?;
    let endpoint = Endpoint::from_shared(plan.endpoint.clone())
        .map_err(|_| "invalid-endpoint")?
        .connect_timeout(Duration::from_millis(plan.connect_timeout_millis))
        .buffer_size(plan.concurrency as usize)
        .http2_max_header_list_size(16 * 1024)
        .http2_header_table_size(4096)
        .max_frame_size(16 * 1024);
    let connect_started = Instant::now();
    let channel = tokio::time::timeout(
        Duration::from_millis(plan.connect_timeout_millis),
        endpoint.connect(),
    )
    .await
    .map_err(|_| "connection-timeout")?
    .map_err(|_| "connection-failed")?;
    let connect_nanos = nanos(connect_started.elapsed());
    let mut authorization =
        MetadataValue::try_from(format!("Bearer {token}")).map_err(|_| "invalid-token")?;
    authorization.set_sensitive(true);
    let readiness = json!({
        "schema":"latent.optimization.client-readiness.v1","run_id":plan.run_id,"arm":plan.arm,
        "client_process_id":std::process::id(),"server_process_id":plan.server_process_id,
        "runtime_workers":plan.runtime_workers,"maximum_in_flight":plan.concurrency,
        "observation_hold_millis":OBSERVATION_HOLD_MILLIS,
        "started_unix_millis":started_unix.to_string(),"connected_unix_millis":unix_millis()?.to_string(),
        "connect_nanos":connect_nanos.to_string(),"startup_to_ready_nanos":nanos(started.elapsed()).to_string(),
        "plan_sha256":plan_digest,"public_plan":prepared.public_plan,
        "request_sha256":digest(&prepared.payload),"request_bytes":prepared.payload.len().to_string(),
        "expected_output_sha256":digest(&prepared.expected),"expected_output_bytes":prepared.expected.len().to_string()
    });
    output.document("readiness.json", &readiness)?;
    signal(&json!({"event":"ready","run_id":plan.run_id,"process_id":std::process::id()}))?;
    let context = Arc::new(Context {
        plan,
        prepared,
        channel,
        authorization,
    });
    let mut first_response = true;
    let warmup = phase(
        Arc::clone(&context),
        "warmup",
        context.plan.warmup_attempts,
        Schedule::ClosedLoop,
        &mut output,
        &mut first_response,
        started,
    )
    .await?;
    let measured = phase(
        Arc::clone(&context),
        "measured",
        context.plan.measured_attempts,
        context.plan.schedule,
        &mut output,
        &mut first_response,
        started,
    )
    .await?;
    output.finish()?;
    let summary = json!({
        "schema":"latent.optimization.client-summary.v1","status":"complete","readiness":readiness,
        "warmup":warmup,"measured":measured,"client_elapsed_nanos":nanos(started.elapsed()).to_string(),
        "active_tasks_at_completion":0,"observation_hold_millis":OBSERVATION_HOLD_MILLIS
    });
    output.document("summary.json", &summary)?;
    // All reported phase/RPC/client intervals are finalized before this fixed
    // observer window. The parent can sample the still-live client without
    // inserting filesystem probes or artificial waits into an attempt.
    signal(
        &json!({"event":"measurement-complete","run_id":context.plan.run_id,"process_id":std::process::id()}),
    )?;
    tokio::time::sleep(Duration::from_millis(OBSERVATION_HOLD_MILLIS)).await;
    Ok(())
}

struct Anchor {
    instant: Instant,
    unix_nanos: u128,
    uncertainty: u64,
}
impl Anchor {
    fn sample() -> Result<Self> {
        let before = Instant::now();
        let unix_nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| "wall-clock-unavailable")?
            .as_nanos();
        let instant = Instant::now();
        Ok(Self {
            instant,
            unix_nanos,
            uncertainty: nanos(instant.duration_since(before)),
        })
    }
    fn offer(&self, phase: &'static str, index: u32, scheduled: u64, budget: u64) -> Result<Offer> {
        let relative = scheduled
            .checked_add(budget.checked_mul(1_000_000).ok_or("deadline-overflow")?)
            .ok_or("deadline-overflow")?;
        let exact_wall = self.unix_nanos + u128::from(relative);
        let absolute = exact_wall.div_ceil(1_000_000);
        Ok(Offer {
            phase,
            index,
            origin: self.instant,
            scheduled,
            absolute_deadline: u64::try_from(absolute).map_err(|_| "deadline-overflow")?,
            deadline: relative,
            quantization: u64::try_from(absolute * 1_000_000 - exact_wall)
                .map_err(|_| "deadline-overflow")?,
        })
    }
}

struct PhaseRecords {
    counts: Counts,
    batches: BTreeMap<u32, Counts>,
}
impl PhaseRecords {
    fn accept(
        &mut self,
        row: &Attempt,
        output: &mut Output,
        first: &mut bool,
        client_started: Instant,
        anchor: &Anchor,
    ) -> Result<()> {
        if *first && row.rpc_received {
            signal(
                &json!({"event":"first-response","activation_id":row.activation_id,
                "phase":row.phase,"index":row.index,"outcome":row.outcome,
                "client_elapsed_nanos":(nanos(anchor.instant.duration_since(client_started)) + row.completed_nanos.parse::<u64>().expect("collector timestamp")).to_string()}),
            )?;
            *first = false;
        }
        self.counts.observe(row);
        self.batches
            .entry(row.batch.parse().expect("collector batch"))
            .or_default()
            .observe(row);
        output.attempt(row)
    }
    fn value(self, anchor: &Anchor, elapsed: u64) -> Value {
        json!({"origin_unix_nanos":anchor.unix_nanos.to_string(),
            "clock_anchor_uncertainty_nanos":anchor.uncertainty.to_string(),
            "phase_elapsed_nanos":elapsed.to_string(),"counts":self.counts.value(),
            "batches":self.batches.into_iter().map(|(index,counts)|json!({"index":index.to_string(),"counts":counts.value()})).collect::<Vec<_>>()})
    }
}

async fn phase(
    context: Arc<Context>,
    name: &'static str,
    count: u32,
    schedule: Schedule,
    output: &mut Output,
    first: &mut bool,
    client_started: Instant,
) -> Result<Value> {
    let anchor = Anchor::sample()?;
    let mut records = PhaseRecords {
        counts: Counts::default(),
        batches: BTreeMap::new(),
    };
    let mut pending = JoinSet::new();
    for index in 0..count {
        // Reap already-completed tasks before deciding whether an arrival is overloaded.
        while let Some(result) = pending.try_join_next() {
            let row = result.map_err(|_| "invocation-task-failed")?;
            records.accept(&row, output, first, client_started, &anchor)?;
        }
        let scheduled = match schedule {
            Schedule::ClosedLoop => {
                if pending.len() >= context.plan.concurrency as usize {
                    let row = pending
                        .join_next()
                        .await
                        .ok_or("missing-invocation-task")?
                        .map_err(|_| "invocation-task-failed")?;
                    records.accept(&row, output, first, client_started, &anchor)?;
                }
                nanos(anchor.instant.elapsed())
            }
            Schedule::Scheduled { interval_nanos } => {
                let scheduled = u64::from(index) * interval_nanos;
                drain_until(
                    &mut pending,
                    anchor.instant + Duration::from_nanos(scheduled),
                    &mut records,
                    output,
                    first,
                    client_started,
                    &anchor,
                )
                .await?;
                scheduled
            }
        };
        let offer = anchor.offer(name, index, scheduled, context.plan.budget_millis)?;
        let outcome = undispatched(
            nanos(anchor.instant.elapsed()),
            offer.deadline,
            pending.len(),
            context.plan.concurrency,
        );
        if let Some(outcome) = outcome {
            records.accept(
                &offer.row(&context.plan, outcome),
                output,
                first,
                client_started,
                &anchor,
            )?;
        } else {
            pending.spawn(call::invoke(Arc::clone(&context), offer));
        }
    }
    while let Some(result) = pending.join_next().await {
        records.accept(
            &result.map_err(|_| "invocation-task-failed")?,
            output,
            first,
            client_started,
            &anchor,
        )?;
    }
    Ok(records.value(&anchor, nanos(anchor.instant.elapsed())))
}

async fn drain_until(
    pending: &mut JoinSet<Attempt>,
    due: Instant,
    records: &mut PhaseRecords,
    output: &mut Output,
    first: &mut bool,
    client_started: Instant,
    anchor: &Anchor,
) -> Result<()> {
    loop {
        // A ready completion must release its bounded task slot before a simultaneous arrival.
        while let Some(result) = pending.try_join_next() {
            records.accept(
                &result.map_err(|_| "invocation-task-failed")?,
                output,
                first,
                client_started,
                anchor,
            )?;
        }
        if Instant::now() >= due {
            return Ok(());
        }
        tokio::select! {
            biased;
            result = pending.join_next(), if !pending.is_empty() => {
                let row = result.ok_or("missing-invocation-task")?.map_err(|_| "invocation-task-failed")?;
                records.accept(&row,output,first,client_started,anchor)?;
            }
            () = tokio::time::sleep_until(tokio::time::Instant::from_std(due)) => {}
        }
    }
}

fn undispatched(now: u64, deadline: u64, pending: usize, capacity: u32) -> Option<&'static str> {
    if now >= deadline {
        Some("client-deadline-before-dispatch")
    } else if pending >= capacity as usize {
        Some("client-overload")
    } else {
        None
    }
}

fn signal(value: &Value) -> Result<()> {
    let mut bytes = serde_json::to_vec(value).map_err(|_| "signal-encoding-failed")?;
    if bytes.len() > 2048 {
        return Err("signal-byte-limit");
    }
    bytes.push(b'\n');
    let mut stdout = std::io::stdout().lock();
    stdout
        .write_all(&bytes)
        .map_err(|_| "signal-write-failed")?;
    stdout.flush().map_err(|_| "signal-flush-failed")
}

#[cfg(test)]
mod tests;
