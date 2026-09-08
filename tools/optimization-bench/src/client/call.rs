use std::sync::Arc;
use std::time::{Duration, Instant};

use latent_wire::invocation::proto;
use serde_json::{json, Value};
use tonic::{
    metadata::{Ascii, MetadataValue},
    transport::Channel,
};

use super::{
    nanos,
    plan::{Plan, Prepared},
    record::{digest, Attempt},
};

pub(super) const MEDIA: &str = "application/vnd.latent.wit-values.v1+json";

pub(super) struct Context {
    pub plan: Plan,
    pub prepared: Prepared,
    pub channel: Channel,
    pub authorization: MetadataValue<Ascii>,
}

pub(super) struct Offer {
    pub phase: &'static str,
    pub index: u32,
    pub origin: Instant,
    pub scheduled: u64,
    pub absolute_deadline: u64,
    pub deadline: u64,
    pub quantization: u64,
}

impl Offer {
    pub fn row(&self, plan: &Plan, outcome: &'static str) -> Attempt {
        let completed = nanos(self.origin.elapsed());
        Attempt {
            schema: "latent.optimization.attempt.v1",
            phase: self.phase,
            index: self.index.to_string(),
            batch: (self.index / plan.batch_size).to_string(),
            activation_id: format!("{}-{}-{}", plan.run_id, self.phase, self.index),
            service: plan.services[self.index as usize % plan.services.len()].clone(),
            scheduled_nanos: self.scheduled.to_string(),
            dispatch_nanos: None,
            completed_nanos: completed.to_string(),
            dispatch_lag_nanos: None,
            request_deadline_unix_millis: self.absolute_deadline.to_string(),
            deadline_nanos: self.deadline.to_string(),
            absolute_deadline_quantization_nanos: self.quantization.to_string(),
            grpc_timeout_header: None,
            grpc_timeout_nanos: None,
            overshoot_nanos: completed.saturating_sub(self.deadline).to_string(),
            latency_nanos: None,
            outcome,
            code: None,
            semantic_match: None,
            rpc_received: false,
            response: None,
        }
    }
}

pub(super) async fn invoke(context: Arc<Context>, offer: Offer) -> Attempt {
    let mut row = offer.row(&context.plan, "client-deadline-before-dispatch");
    let value = proto::InvokeRequest {
        activation_id: Some(row.activation_id.clone()),
        target: Some(proto::InvocationTarget {
            tenant: context.plan.tenant.clone(),
            service: row.service.clone(),
            contract: context.plan.contract.clone(),
            function: context.plan.function.clone(),
            route: context.plan.route.clone(),
        }),
        payload: context.prepared.payload.clone(),
        media_type: MEDIA.into(),
        deadline_unix_millis: Some(offer.absolute_deadline),
        budget: Some(proto::ResourceBudget {
            cpu_fuel: context.plan.cpu_fuel,
            memory_bytes: context.plan.memory_bytes,
            log_bytes: context.plan.log_bytes,
            wall_time_limit_millis: Some(context.plan.budget_millis),
            ..Default::default()
        }),
        ..Default::default()
    };
    let mut request = tonic::Request::new(value);
    request
        .metadata_mut()
        .insert("authorization", context.authorization.clone());
    let mut client =
        proto::invocation_service_client::InvocationServiceClient::new(context.channel.clone())
            .max_decoding_message_size(2 * 1024 * 1024)
            .max_encoding_message_size(2 * 1024 * 1024);
    let dispatch = nanos(offer.origin.elapsed());
    if dispatch >= offer.deadline {
        return offer.row(&context.plan, "client-deadline-before-dispatch");
    }
    row.dispatch_nanos = Some(dispatch.to_string());
    row.dispatch_lag_nanos = Some(dispatch.saturating_sub(offer.scheduled).to_string());
    request.set_timeout(Duration::from_nanos(offer.deadline - dispatch));
    let (header, timeout) = encoded_timeout(&request);
    row.grpc_timeout_header = Some(header);
    row.grpc_timeout_nanos = Some(timeout.to_string());
    let response = tokio::time::timeout(
        Duration::from_millis(context.plan.response_timeout_millis),
        client.invoke(request),
    )
    .await;
    let completed = nanos(offer.origin.elapsed());
    row.completed_nanos = completed.to_string();
    row.latency_nanos = Some(completed.saturating_sub(dispatch).to_string());
    row.overshoot_nanos = completed.saturating_sub(offer.deadline).to_string();
    match response {
        Ok(Ok(response)) => classify(
            &mut row,
            response.into_inner(),
            &context.prepared.expected,
            context.plan.arm == "native",
        ),
        Ok(Err(status)) => {
            row.outcome = "transport-failure";
            row.code = Some(format!("grpc-{}", status.code() as i32));
        }
        Err(_) => {
            row.outcome = "client-timeout";
            row.code = Some("response-observation-timeout".into());
        }
    }
    row
}

fn classify(row: &mut Attempt, response: proto::InvokeResponse, expected: &[u8], native: bool) {
    row.rpc_received = true;
    row.outcome = "invalid-response";
    let bounded = response.activation_id.len() <= 512
        && response.revision_id.len() <= 512
        && response.release_digest.len() <= 128;
    if !bounded {
        row.code = Some("response-identity-bound".into());
        return;
    }
    row.response = Some(
        json!({"activation_id":response.activation_id,"revision_id":response.revision_id,
        "release_digest":response.release_digest,"route_generation":response.route_generation.to_string(),
        "consumption":response.consumption.as_ref().map(consumption),"media_type":null,"payload_sha256":null,"payload_bytes":null}),
    );
    if response.activation_id != row.activation_id || (!native && response.consumption.is_none()) {
        row.code = Some("response-association".into());
        return;
    }
    match response.result {
        Some(proto::invoke_response::Result::Success(value)) => {
            payload(row, &value.payload, &value.media_type);
            let matched = value.media_type == MEDIA && value.payload == expected;
            row.semantic_match = Some(matched);
            row.outcome = if matched {
                "success"
            } else {
                "invalid-response"
            };
            if !matched {
                row.code = Some("semantic-mismatch".into());
            }
        }
        Some(proto::invoke_response::Result::DeclaredError(value)) => {
            payload(row, &value.payload, &value.media_type);
            row.outcome = "declared-error";
            row.code = Some("declared-error".into());
        }
        Some(proto::invoke_response::Result::PlatformFailure(value)) => {
            if platform_code(&value.code) {
                row.outcome = "platform-failure";
                row.code = Some(value.code);
            } else {
                row.code = Some("invalid-platform-code".into());
            }
        }
        None => {
            row.code = Some("missing-result".into());
        }
    }
}

fn encoded_timeout<T>(request: &tonic::Request<T>) -> (String, u64) {
    let header = request
        .metadata()
        .get("grpc-timeout")
        .expect("tonic timeout header")
        .to_str()
        .expect("ASCII timeout");
    let (number, unit) = header.split_at(header.len() - 1);
    let multiplier = match unit {
        "n" => 1,
        "u" => 1000,
        "m" => 1_000_000,
        "S" => 1_000_000_000,
        "M" => 60_000_000_000,
        "H" => 3_600_000_000_000,
        _ => unreachable!("tonic timeout unit"),
    };
    (
        header.to_owned(),
        number.parse::<u64>().expect("tonic timeout integer") * multiplier,
    )
}

fn payload(row: &mut Attempt, bytes: &[u8], media: &str) {
    let response = row.response.as_mut().expect("response projection");
    response["media_type"] = if media.len() <= 128 {
        json!(media)
    } else {
        Value::Null
    };
    response["payload_sha256"] = digest(bytes).into();
    response["payload_bytes"] = bytes.len().to_string().into();
}

fn platform_code(code: &str) -> bool {
    matches!(
        code,
        "invalid-argument"
            | "not-found"
            | "already-exists"
            | "permission-denied"
            | "unauthenticated"
            | "resource-exhausted"
            | "deadline-exceeded"
            | "cancelled"
            | "unavailable"
            | "internal"
            | "state-conflict"
            | "incompatible-contract"
            | "corrupt-artifact"
            | "route-unavailable"
            | "dependency-failed"
            | "guest-trap"
            | "admission-rejected"
    )
}

fn consumption(value: &proto::BudgetConsumption) -> Value {
    json!({"cpu_fuel":value.cpu_fuel.to_string(),"peak_memory_bytes":value.peak_memory_bytes.to_string(),
        "wall_time_micros":value.wall_time_micros.to_string(),"child_calls":value.child_calls.to_string(),
        "outbound_requests":value.outbound_requests.to_string(),"state_read_bytes":value.state_read_bytes.to_string(),
        "state_write_bytes":value.state_write_bytes.to_string(),"blob_read_bytes":value.blob_read_bytes.to_string(),
        "blob_write_bytes":value.blob_write_bytes.to_string(),"log_bytes":value.log_bytes.to_string(),"effect_count":value.effect_count.to_string()})
}

#[cfg(test)]
mod tests;
