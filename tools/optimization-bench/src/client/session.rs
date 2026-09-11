mod control;
mod inventory;
mod output;
mod phase;
mod plan;
#[cfg(test)]
mod tests;

use std::{
    io::Write,
    path::PathBuf,
    time::{Duration, Instant},
};

use serde_json::{json, Value};
use tonic::{
    metadata::{Ascii, MetadataValue},
    transport::{Channel, Endpoint},
};

use super::{nanos, read, record::digest, Result};
use plan::{Group, Plan, Target, PREFIX};

struct Live {
    group: Group,
    targets: Vec<Target>,
    channels: Vec<Channel>,
    deadline: Instant,
}

impl Live {
    fn inventory(
        &self,
        authorization: &MetadataValue<Ascii>,
        started: Instant,
        runtime: &tokio::runtime::Runtime,
        barrier: &str,
    ) -> Result<Value> {
        if self.group.arm == "lsf" {
            runtime.block_on(inventory_call(
                &self.channels[0],
                authorization,
                started,
                self.deadline,
                barrier,
            ))
        } else {
            Ok(
                json!({"status":"passed","barrier":barrier,"rpc_calls":0,"inventory":null,
                "reason":"native-no-management-api","channel_index":null,
                "started_nanos":nanos(started.elapsed()).to_string(),"finished_nanos":nanos(started.elapsed()).to_string()}),
            )
        }
    }
}

struct Session {
    commands: u32,
    groups: u32,
    phases: u32,
    management_calls: u32,
    attempts: phase::State,
    live: Option<Live>,
    finish_command: Option<Value>,
}

impl Session {
    fn begin_group(
        &mut self,
        group: Group,
        targets: Vec<Target>,
        started: Instant,
        session_deadline: Instant,
        runtime: &tokio::runtime::Runtime,
    ) -> Result<(Value, Option<&'static str>)> {
        plan::targets(group, &targets)?;
        let deadline = (Instant::now() + Duration::from_mins(5)).min(session_deadline);
        let (channels, connections, failure) =
            runtime.block_on(connect(&targets, started, deadline));
        let channel_count = channels.len();
        self.live = Some(Live {
            group,
            targets,
            channels,
            deadline,
        });
        self.attempts.first_response = false;
        Ok((
            json!({"status":if failure.is_none(){"passed"}else{"failed"},
            "reason":failure,"connections":connections,"independent_channels":channel_count}),
            failure,
        ))
    }

    fn finish(&mut self, input: &control::Input, plan: &Plan, receipt: Value) -> Result<()> {
        input.finished()?;
        if self.groups != 6
            || self.phases != 30
            || self.attempts.offers != u64::from(plan.offers())
            || self.management_calls != 9
            || self.live.is_some()
        {
            return Err("session-incomplete-population");
        }
        self.commands += 1;
        self.finish_command = Some(receipt);
        Ok(())
    }
}

pub(super) fn run() -> Result<()> {
    let started = Instant::now();
    let (plan_path, output_path) = arguments()?;
    let bytes = read(&plan_path, 64 * 1024)?;
    let plan: Plan = serde_json::from_slice(&bytes).map_err(|_| "session-plan-json")?;
    plan.validate()?;
    let plan_digest = digest(&bytes);
    let token = read(&plan.token_file, 4096)?;
    let token = std::str::from_utf8(&token)
        .map_err(|_| "invalid-token")?
        .trim_end_matches(['\r', '\n']);
    if token.is_empty() || !token.bytes().all(|byte| (33..=126).contains(&byte)) {
        return Err("invalid-token");
    }
    let mut authorization =
        MetadataValue::try_from(format!("Bearer {token}")).map_err(|_| "invalid-token")?;
    authorization.set_sensitive(true);
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .max_blocking_threads(1)
        .enable_all()
        .build()
        .map_err(|_| "session-runtime-create")?;
    let mut output = output::Output::new(output_path, plan_digest.clone(), started)?;
    let mut state = Session {
        commands: 0,
        groups: 0,
        phases: 0,
        management_calls: 0,
        attempts: phase::State {
            offers: 0,
            first_response: false,
        },
        live: None,
        finish_command: None,
    };
    let result = execute(
        &plan,
        &plan_digest,
        started,
        &authorization,
        &runtime,
        &mut output,
        &mut state,
    );
    // All phase calls drain their owned JoinSet before returning. Connection
    // handles are released before dropping and joining the owned Tokio runtime.
    drop(state.live.take());
    drop(runtime);
    if let Err(reason) = result {
        let _ = output.event("failed", Some(state.commands), &json!({"reason":reason,
            "offers":state.attempts.offers.to_string(),"active_tasks":0,"channels":0,"runtime_dropped":true}));
    }
    let summary = json!({"schema":format!("{PREFIX}summary.v1"),"status":if result.is_ok(){"complete"}else{"failed"},
        "reason":result.err(),"plan_sha256":plan_digest,"process_id":std::process::id(),
        "commands_completed":state.commands.to_string(),"groups_completed":state.groups.to_string(),
        "phases_completed":state.phases.to_string(),"offers":state.attempts.offers.to_string(),
        "management_calls":state.management_calls.to_string(),"active_tasks_at_completion":0,
        "channels_at_completion":0,"runtime_dropped":true,"session_elapsed_nanos":nanos(started.elapsed()).to_string(),
        "attempts":output.attempt_ref(),"finish_command":state.finish_command});
    let reference = output.summary(&summary)?;
    let ack = json!({"schema":format!("{PREFIX}ack.v1"),"event":if result.is_ok(){"complete"}else{"failed"},
        "command_ordinal":if result.is_ok(){Some(60)}else{None},"process_id":std::process::id(),
        "plan_sha256":plan_digest,"summary":reference});
    let bytes = output::encode(&ack, 4096)?;
    let mut stdout = std::io::stdout().lock();
    stdout
        .write_all(&bytes)
        .and_then(|()| stdout.flush())
        .map_err(|_| "session-final-ack")?;
    drop(stdout);
    std::thread::sleep(Duration::from_millis(100));
    result
}

fn arguments() -> Result<(PathBuf, PathBuf)> {
    let mut args = std::env::args_os().skip(1);
    let (mut plan, mut output) = (None, None);
    while let Some(flag) = args.next() {
        let value = args.next().ok_or("usage: --session PLAN --output DIR")?;
        let slot = if flag == "--session" {
            &mut plan
        } else if flag == "--output" {
            &mut output
        } else {
            return Err("unknown-session-argument");
        };
        if slot.replace(PathBuf::from(value)).is_some() {
            return Err("duplicate-session-argument");
        }
    }
    Ok((
        plan.ok_or("missing-session-plan")?,
        output.ok_or("missing-session-output")?,
    ))
}

fn execute(
    plan: &Plan,
    digest_value: &str,
    started: Instant,
    authorization: &MetadataValue<Ascii>,
    runtime: &tokio::runtime::Runtime,
    output: &mut output::Output,
    state: &mut Session,
) -> Result<()> {
    let groups = plan.groups();
    let sequence = control::sequence(plan);
    let session_deadline = started + Duration::from_mins(30);
    output.event("ready", None, &ready(plan, &groups))?;
    let mut input = control::Input::default();
    for (ordinal, expected) in sequence.iter().enumerate() {
        let ordinal = u32::try_from(ordinal).map_err(|_| "session-command-count")?;
        let deadline = state
            .live
            .as_ref()
            .map_or(session_deadline, |live| live.deadline.min(session_deadline));
        let (command, bytes) = input.command(deadline)?;
        command.validate(expected, ordinal, digest_value)?;
        let receipt = json!({"command":command,"command_bytes":bytes.len().to_string(),"command_sha256":digest(&bytes)});
        let mut payload = receipt
            .as_object()
            .ok_or("session-command-projection")?
            .clone();
        let event = match command.operation.as_str() {
            "begin-group" => {
                let group = groups[command.group.ok_or("session-group")? as usize];
                let targets = command.targets.ok_or("session-targets")?;
                let (result, failure) =
                    state.begin_group(group, targets, started, session_deadline, runtime)?;
                payload.insert("result".into(), result);
                if let Some(reason) = failure {
                    output.event("group-ready", Some(ordinal), &Value::Object(payload))?;
                    state.commands += 1;
                    return Err(reason);
                }
                "group-ready"
            }
            "inventory" => {
                let live = state.live.as_ref().ok_or("session-group-not-live")?;
                let barrier = command.barrier.as_deref().ok_or("session-barrier")?;
                if live.group.arm == "lsf" {
                    state.management_calls += 1;
                }
                let result = live.inventory(authorization, started, runtime, barrier)?;
                let passed = result["status"] == "passed";
                payload.insert("result".into(), result);
                output.event("inventory", Some(ordinal), &Value::Object(payload))?;
                state.commands += 1;
                if !passed {
                    return Err("session-inventory-failed");
                }
                continue;
            }
            "phase" => {
                let live = state.live.as_ref().ok_or("session-group-not-live")?;
                let phase = plan.phases(live.group)[command.phase.ok_or("session-phase")? as usize];
                let result = runtime.block_on(phase::run(
                    phase::Inputs {
                        plan,
                        group: live.group,
                        phase,
                        targets: &live.targets,
                        channels: &live.channels,
                        authorization,
                        command: ordinal,
                        session_started: started,
                        deadline: live.deadline.min(session_deadline),
                    },
                    output,
                    &mut state.attempts,
                ))?;
                let passed = result["status"] == "passed";
                payload.insert("result".into(), result);
                output.event("phase-complete", Some(ordinal), &Value::Object(payload))?;
                state.phases += 1;
                state.commands += 1;
                if !passed {
                    return Err("session-phase-failed");
                }
                continue;
            }
            "finish-group" => {
                let live = state.live.take().ok_or("session-group-not-live")?;
                let channels = live.channels.len();
                drop(live);
                state.groups += 1;
                payload.insert(
                    "result".into(),
                    json!({"status":"passed","channels_dropped":channels,"active_tasks":0}),
                );
                "group-finished"
            }
            "finish" => {
                return state.finish(&input, plan, receipt);
            }
            _ => return Err("session-unknown-command"),
        };
        output.event(event, Some(ordinal), &Value::Object(payload))?;
        state.commands += 1;
    }
    Err("session-missing-finish")
}

fn ready(plan: &Plan, groups: &[Group]) -> Value {
    json!({"plan":{"schema":plan.schema,"run_id":plan.run_id,
        "profile":plan.profile,"pair":plan.pair},"groups":groups.iter().map(|group| {
            json!({"ordinal":group.index,"arm":group.arm,"density":group.density,
                "phases":plan.phases(*group).iter().map(|phase|json!({"ordinal":phase.index,"name":phase.name,
                    "kind":phase.kind,"function":phase.function,"offers":phase.offers,"concurrency":phase.concurrency,
                    "payload":if phase.function=="compute"{json!([17,10000])}else{json!(["optimization-reference-v1"])}})).collect::<Vec<_>>()})
        }).collect::<Vec<_>>(),"logical_offers":plan.offers().to_string(),"commands":61,
        "runtime_workers":2,"maximum_channels":32,"maximum_output_bytes":plan::MAXIMUM_BYTES.to_string(),
        "maximum_command_bytes":plan::MAXIMUM_COMMAND,"group_timeout_seconds":300,"session_timeout_seconds":1800})
}

async fn connect(
    targets: &[Target],
    origin: Instant,
    deadline: Instant,
) -> (Vec<Channel>, Vec<Value>, Option<&'static str>) {
    let mut channels = Vec::with_capacity(targets.len());
    let mut receipts = Vec::with_capacity(targets.len());
    for (index, target) in targets.iter().enumerate() {
        let begin = nanos(origin.elapsed());
        let bound = deadline
            .saturating_duration_since(Instant::now())
            .min(Duration::from_secs(5));
        let result = match Endpoint::from_shared(target.endpoint.clone()) {
            Ok(endpoint) => tokio::time::timeout(
                bound,
                endpoint
                    .connect_timeout(Duration::from_secs(5))
                    .buffer_size(4)
                    .http2_max_header_list_size(16 * 1024)
                    .http2_header_table_size(4096)
                    .max_frame_size(16 * 1024)
                    .connect(),
            )
            .await
            .map_err(|_| "session-connect-timeout")
            .and_then(|result| result.map_err(|_| "session-connect-failed")),
            Err(_) => Err("session-invalid-endpoint"),
        };
        let failure = result.as_ref().err().copied();
        receipts.push(json!({"target_index":index,"owner_ref":target.owner_ref,"app_process_id":target.app_process_id,
            "endpoint":target.endpoint,"started_nanos":begin.to_string(),"finished_nanos":nanos(origin.elapsed()).to_string(),
            "status":if failure.is_none(){"connected"}else{"failed"},"reason":failure}));
        match result {
            Ok(channel) => channels.push(channel),
            Err(reason) => return (channels, receipts, Some(reason)),
        }
    }
    (channels, receipts, None)
}

async fn inventory_call(
    channel: &Channel,
    authorization: &MetadataValue<Ascii>,
    origin: Instant,
    deadline: Instant,
    barrier: &str,
) -> Result<Value> {
    use latent_wire::management::proto;
    let begin = nanos(origin.elapsed());
    let mut client = proto::node_service_client::NodeServiceClient::new(channel.clone())
        .max_decoding_message_size(2 * 1024 * 1024)
        .max_encoding_message_size(2 * 1024 * 1024);
    let mut request = tonic::Request::new(proto::GetNodeRequest {
        node_id: "optimization-node".into(),
    });
    request
        .metadata_mut()
        .insert("authorization", authorization.clone());
    request.set_timeout(Duration::from_secs(5));
    let bound = deadline
        .saturating_duration_since(Instant::now())
        .min(Duration::from_secs(5));
    let response = tokio::time::timeout(bound, client.get_node(request)).await;
    let finished = nanos(origin.elapsed());
    let mut result = json!({"status":"failed","barrier":barrier,"rpc_calls":1,"inventory":null,
        "reason":null,"channel_index":0,"started_nanos":begin.to_string(),"finished_nanos":finished.to_string()});
    match response {
        Ok(Ok(response)) => {
            match response
                .into_inner()
                .inventory
                .and_then(|value| inventory::project(value).ok())
            {
                Some(value) if value["node"]["id"] == "optimization-node" => {
                    result["status"] = json!("passed");
                    result["inventory"] = value;
                }
                _ => result["reason"] = json!("session-invalid-inventory"),
            }
        }
        Ok(Err(status)) => result["reason"] = json!(format!("grpc-{}", status.code() as i32)),
        Err(_) => result["reason"] = json!("session-inventory-timeout"),
    }
    Ok(result)
}
