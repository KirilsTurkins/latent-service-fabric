use std::time::Duration;

use latent_artifacts::content_digest;
use latent_wire::invocation::{proto, InvocationServiceClient};
use serde_json::{json, Value};
use tonic::transport::Channel;

use super::{
    cold::call::{auth, consumption, Clock},
    Result,
};

#[derive(Clone)]
pub(super) struct Offer {
    pub ordinal: u32,
    pub case: &'static str,
    pub budget_millis: u64,
    pub function: &'static str,
    pub release: String,
}

impl Offer {
    pub fn id(&self) -> String {
        format!(
            "budget-{:02}-{}-{}",
            self.ordinal, self.case, self.budget_millis
        )
    }
}

pub(super) fn payload(bytes: &[u8]) -> Value {
    json!({"sha256":content_digest(bytes).0,"bytes":bytes.len().to_string(),
        "media_type":super::super::super::fixtures::MEDIA})
}

pub(super) fn request(
    offer: &Offer,
    clock: Clock,
) -> Result<(tonic::Request<proto::InvokeRequest>, Value)> {
    let scheduled = clock.elapsed();
    // Keep the RPC owner alive while native interruption returns its cleanup
    // acknowledgement. Queue/body cases separately exercise short outer limits.
    let transport_budget_millis = if matches!(offer.case, "runaway" | "cancel") {
        1_000
    } else {
        offer.budget_millis
    };
    let deadline = scheduled + u128::from(transport_budget_millis) * 1_000_000;
    let absolute = (clock.unix_nanos + deadline).div_ceil(1_000_000);
    let mut row = json!({"kind":"invoke","ordinal":offer.ordinal.to_string(),"case":offer.case,
        "budget_millis":offer.budget_millis.to_string(),"function":offer.function,"activation_id":offer.id(),
        "transport_budget_millis":transport_budget_millis.to_string(),
        "release_digest":offer.release,"scheduled_nanos":scheduled.to_string(),"deadline_nanos":deadline.to_string(),
        "deadline_unix_millis":absolute.to_string(),
        "absolute_deadline_quantization_nanos":(absolute*1_000_000-clock.unix_nanos-deadline).to_string(),
        "request_payload":payload(b"[]"),"expected_payload":if offer.function == "identify" {payload(b"[11]")} else {Value::Null},
        "diagnostic_token":Value::Null,"body_gate":Value::Null,"rpc_received":false,"response":Value::Null});
    let dispatch = clock.elapsed();
    let remaining = deadline
        .checked_sub(dispatch)
        .ok_or("diagnostic deadline before dispatch")?;
    let request = auth(
        proto::InvokeRequest {
            activation_id: Some(offer.id()),
            target: Some(proto::InvocationTarget {
                tenant: "tests".into(),
                service: "measurement-generic".into(),
                contract: "tests:generic/values@0.1.0".into(),
                function: offer.function.into(),
                route: None,
            }),
            payload: b"[]".to_vec(),
            media_type: super::super::super::fixtures::MEDIA.into(),
            deadline_unix_millis: Some(u64::try_from(absolute)?),
            budget: Some(proto::ResourceBudget {
                cpu_fuel: 10_000_000_000,
                memory_bytes: 67_108_864,
                wall_time_limit_millis: Some(offer.budget_millis),
                log_bytes: 16384,
                ..Default::default()
            }),
            ..Default::default()
        },
        Duration::from_nanos(u64::try_from(remaining)?),
    )?;
    row["dispatch_nanos"] = json!(dispatch.to_string());
    row["dispatch_lag_nanos"] = json!((dispatch - scheduled).to_string());
    row["grpc_timeout_header"] = json!(request
        .metadata()
        .get("grpc-timeout")
        .ok_or("missing diagnostic timeout")?
        .to_str()?);
    Ok((request, row))
}

pub(super) fn response(
    offer: &Offer,
    clock: Clock,
    mut row: Value,
    result: std::result::Result<tonic::Response<proto::InvokeResponse>, tonic::Status>,
) -> Value {
    // Observe receipt before decoding, hashing and constructing evidence rows.
    let completed = clock.elapsed();
    match result {
        Ok(response) => {
            row["rpc_received"] = json!(true);
            let response = response.into_inner();
            let (outcome, code, valid, output) = match &response.result {
                Some(proto::invoke_response::Result::Success(value)) => (
                    "success",
                    None,
                    offer.function == "identify"
                        && value.media_type == super::super::super::fixtures::MEDIA
                        && serde_json::from_slice::<Value>(&value.payload).ok()
                            == Some(json!([11])),
                    payload(&value.payload),
                ),
                Some(proto::invoke_response::Result::PlatformFailure(error)) => (
                    "platform-failure",
                    Some(error.code.clone()),
                    true,
                    Value::Null,
                ),
                Some(proto::invoke_response::Result::DeclaredError(_)) => {
                    ("declared-error", None, false, Value::Null)
                }
                None => ("invalid-response", None, false, Value::Null),
            };
            row["outcome"] = json!(outcome);
            row["valid_response"] = json!(
                valid
                    && response.activation_id == offer.id()
                    && (outcome != "success"
                        || (response.release_digest == offer.release
                            && response.route_generation == 1
                            && !response.revision_id.is_empty()
                            && response
                                .consumption
                                .as_ref()
                                .is_some_and(|usage| usage.cpu_fuel > 0
                                    && usage.cpu_fuel <= 10_000_000_000
                                    && usage.peak_memory_bytes > 0
                                    && usage.peak_memory_bytes <= 67_108_864
                                    && usage.log_bytes <= 16384)))
            );
            row["response"] = json!({"activation_id":response.activation_id,"release_digest":response.release_digest,
                "revision_id":response.revision_id,"route_generation":response.route_generation.to_string(),
                "code":code,"payload":output,"consumption":consumption(response.consumption.as_ref())});
        }
        Err(error) => {
            row["outcome"] = json!("transport-failure");
            row["grpc_code"] = json!(error.code() as i32);
        }
    }
    let deadline = row["deadline_nanos"]
        .as_str()
        .expect("owned deadline")
        .parse::<u128>()
        .expect("decimal deadline");
    row["completed_nanos"] = json!(completed.to_string());
    row["overshoot_nanos"] = json!(completed.saturating_sub(deadline).to_string());
    row
}

pub(super) async fn invoke(channel: Channel, clock: Clock, offer: Offer) -> Result<Value> {
    let (request, row) = request(&offer, clock)?;
    let result = InvocationServiceClient::new(channel).invoke(request).await;
    Ok(response(&offer, clock, row, result))
}
