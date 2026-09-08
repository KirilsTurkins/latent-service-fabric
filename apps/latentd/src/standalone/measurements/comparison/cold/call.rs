use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use latent_artifacts::content_digest;
use latent_wire::invocation::{proto, InvocationServiceClient};
use serde_json::{json, Value};
use tonic::transport::Channel;

use super::{Result, INPUT};

#[derive(Clone, Copy)]
pub(super) struct Clock {
    pub origin: Instant,
    pub unix_nanos: u128,
    pub uncertainty_nanos: u128,
}

impl Clock {
    pub fn new() -> Result<Self> {
        let origin = Instant::now();
        let unix_nanos = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
        Ok(Self {
            origin,
            unix_nanos,
            uncertainty_nanos: origin.elapsed().as_nanos(),
        })
    }
    pub fn elapsed(self) -> u128 {
        self.origin.elapsed().as_nanos()
    }
    pub fn record(self) -> Value {
        json!({"unix_origin_nanos":self.unix_nanos.to_string(),
        "clock_anchor_uncertainty_nanos":self.uncertainty_nanos.to_string()})
    }
}

pub(super) fn auth<T>(value: T, timeout: Duration) -> Result<tonic::Request<T>> {
    let mut request = tonic::Request::new(value);
    request.metadata_mut().insert(
        "authorization",
        "Bearer comparison-examples-000000000000000".parse()?,
    );
    request.set_timeout(timeout);
    Ok(request)
}

pub(super) fn consumption(value: Option<&proto::BudgetConsumption>) -> Value {
    value.map_or(Value::Null, |value| json!({"cpu_fuel":value.cpu_fuel.to_string(),
        "peak_memory_bytes":value.peak_memory_bytes.to_string(),"wall_time_micros":value.wall_time_micros.to_string(),
        "log_bytes":value.log_bytes.to_string(),"child_calls":value.child_calls.to_string(),
        "outbound_requests":value.outbound_requests.to_string(),"state_read_bytes":value.state_read_bytes.to_string(),
        "state_write_bytes":value.state_write_bytes.to_string(),"blob_read_bytes":value.blob_read_bytes.to_string(),
        "blob_write_bytes":value.blob_write_bytes.to_string(),"effect_count":value.effect_count.to_string()}))
}

pub(super) fn status(
    value: std::result::Result<tonic::Response<proto::ActivationStatus>, tonic::Status>,
) -> Value {
    match value {
        Ok(value) => {
            let value = value.into_inner();
            let (outcome, code) = match &value.terminal_outcome {
                Some(proto::activation_status::TerminalOutcome::Succeeded(_)) => ("success", None),
                Some(proto::activation_status::TerminalOutcome::PlatformFailure(error)) => {
                    ("platform-failure", Some(error.code.clone()))
                }
                Some(proto::activation_status::TerminalOutcome::DeclaredError(_)) => {
                    ("declared-error", None)
                }
                None => ("pending", None),
            };
            json!({"grpc_code":0,"activation_id":value.activation_id,"phase":value.phase,
                "terminal_state":value.terminal_state,"outcome":outcome,"code":code,
                "metadata":value.metadata,"consumption":consumption(value.final_consumption.as_ref())})
        }
        Err(error) => json!({"grpc_code":error.code() as i32}),
    }
}

pub(super) struct InvokeOptions {
    pub phase: String,
    pub index: u32,
    pub key: u32,
    pub scheduled: u128,
    pub id: String,
    pub release: String,
    pub overload: bool,
}

#[expect(
    clippy::too_many_lines,
    reason = "Keep request construction, response validation and the final observation timestamp inside the unchanged measured boundary."
)]
pub(super) async fn invoke(
    channel: Channel,
    clock: Clock,
    options: InvokeOptions,
) -> Result<Value> {
    let InvokeOptions {
        phase,
        index,
        key,
        scheduled,
        id,
        release,
        overload,
    } = options;
    let deadline = scheduled + 1_000_000_000;
    let absolute = (clock.unix_nanos + deadline).div_ceil(1_000_000);
    let mut row = json!({"kind":"invoke","phase":phase,"index":index.to_string(),"key":key.to_string(),
        "activation_id":id,"release_digest":release,"scheduled_nanos":scheduled.to_string(),
        "deadline_nanos":deadline.to_string(),"deadline_unix_millis":absolute.to_string(),
        "absolute_deadline_quantization_nanos":(absolute*1_000_000-clock.unix_nanos-deadline).to_string(),
        "dispatch_nanos":Value::Null,"dispatch_lag_nanos":Value::Null,"grpc_timeout_header":Value::Null,
        "rpc_received":false,"response":Value::Null});
    let dispatch = clock.elapsed();
    if overload || dispatch >= deadline {
        row["outcome"] = json!(if overload {
            "client-overload"
        } else {
            "client-deadline-before-dispatch"
        });
    } else {
        let payload = serde_json::to_vec(&json!([INPUT]))?;
        let request = proto::InvokeRequest {
            activation_id: Some(id.clone()),
            target: Some(proto::InvocationTarget {
                tenant: "examples".into(),
                service: format!("cold-key-{key}"),
                contract: "examples:echo/api@0.1.0".into(),
                function: "echo".into(),
                route: None,
            }),
            payload,
            media_type: super::super::super::fixtures::MEDIA.into(),
            deadline_unix_millis: Some(u64::try_from(absolute)?),
            budget: Some(proto::ResourceBudget {
                cpu_fuel: 10_000_000_000,
                memory_bytes: 16_777_216,
                wall_time_limit_millis: Some(1000),
                log_bytes: 16384,
                ..Default::default()
            }),
            ..Default::default()
        };
        let request = auth(
            request,
            Duration::from_nanos(u64::try_from(deadline - dispatch)?),
        )?;
        row["dispatch_nanos"] = json!(dispatch.to_string());
        row["dispatch_lag_nanos"] = json!((dispatch - scheduled).to_string());
        row["grpc_timeout_header"] = json!(request
            .metadata()
            .get("grpc-timeout")
            .ok_or("cold timeout header missing")?
            .to_str()?);
        let result = tokio::time::timeout(
            Duration::from_secs(5),
            InvocationServiceClient::new(channel.clone()).invoke(request),
        )
        .await;
        match result {
            Ok(Ok(response)) => {
                row["rpc_received"] = json!(true);
                let response = response.into_inner();
                let (outcome, code, semantic) = match &response.result {
                    Some(proto::invoke_response::Result::Success(success)) => (
                        "success",
                        None,
                        success.media_type == super::super::super::fixtures::MEDIA
                            && serde_json::from_slice::<Value>(&success.payload).ok()
                                == Some(json!([{"ok":INPUT}])),
                    ),
                    Some(proto::invoke_response::Result::PlatformFailure(error)) => {
                        ("platform-failure", Some(error.code.clone()), true)
                    }
                    Some(proto::invoke_response::Result::DeclaredError(_)) => {
                        ("declared-error", None, false)
                    }
                    None => ("invalid-response", None, false),
                };
                row["outcome"] = json!(outcome);
                row["valid_response"] = json!(
                    semantic
                        && response.activation_id == id
                        && (outcome != "success"
                            || (response.release_digest == release
                                && response.route_generation == 8
                                && !response.revision_id.is_empty()
                                && response.consumption.as_ref().is_some_and(|value| value
                                    .cpu_fuel
                                    > 0
                                    && value.cpu_fuel < 10_000_000_000
                                    && value.peak_memory_bytes > 0
                                    && value.peak_memory_bytes <= 16_777_216
                                    && value.log_bytes > 0
                                    && value.log_bytes <= 16384
                                    && value.wall_time_micros <= 1_000_000)))
                );
                let payload = match &response.result {
                    Some(proto::invoke_response::Result::Success(value)) => {
                        json!({"sha256":content_digest(&value.payload).0,"bytes":value.payload.len().to_string(),"media_type":value.media_type})
                    }
                    _ => Value::Null,
                };
                row["response"] = json!({"activation_id":response.activation_id,"release_digest":response.release_digest,
                    "revision_id":response.revision_id,"route_generation":response.route_generation.to_string(),
                    "code":code,"payload":payload,"consumption":consumption(response.consumption.as_ref())});
            }
            Ok(Err(error)) => {
                row["outcome"] = json!("transport-failure");
                row["grpc_code"] = json!(error.code() as i32);
            }
            Err(_) => row["outcome"] = json!("client-timeout"),
        }
    }
    let completed = clock.elapsed();
    row["completed_nanos"] = json!(completed.to_string());
    row["overshoot_nanos"] = json!(completed.saturating_sub(deadline).to_string());
    Ok(row)
}

pub(super) async fn retain(channel: Channel, clock: Clock, row: &mut Value) -> Result<()> {
    let id = row["activation_id"]
        .as_str()
        .ok_or("cold activation identity missing")?
        .to_owned();
    let retained = InvocationServiceClient::new(channel)
        .get_activation(auth(
            proto::GetActivationRequest { activation_id: id },
            Duration::from_secs(5),
        )?)
        .await;
    row["retained_status"] = status(retained);
    row["retained_observed_nanos"] = json!(clock.elapsed().to_string());
    Ok(())
}
