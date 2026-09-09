use super::{publication::Target, Clock, Result};
use latent_artifacts::content_digest;
use latent_wire::invocation::{proto, InvocationServiceClient};
use serde_json::{json, Value};
use std::time::Duration;
use tonic::transport::Channel;
pub(super) const MEDIA: &str = "application/vnd.latent.wit-values.v1+json";

#[derive(Clone)]
pub(super) struct Offer {
    pub ordinal: u64,
    pub command_ordinal: u64,
    pub phase: String,
    pub phase_kind: String,
    pub index: u32,
    pub id: String,
    pub target: Target,
    pub function: String,
    pub payload: Value,
    pub expected: Option<Value>,
    pub grant: proto::ResourceBudget,
    pub expected_code: Option<&'static str>,
    pub scheduled: u128,
}
pub(super) fn grant(kind: &str) -> proto::ResourceBudget {
    let (cpu, memory, wall, logs) = match kind {
        "F" => (50_000, 16_777_216, 1000, 16384),
        "M" => (10_000_000_000, 4_194_304, 1000, 16384),
        "D" => (10_000_000_000, 16_777_216, 50, 16384),
        "H" => (10_000_000_000, 16_777_216, 5000, 16384),
        "R" => (100_000_000, 8_388_608, 1000, 4096),
        "C" => (10_000_000_000, 8_388_608, 1000, 4096),
        _ => (10_000_000_000, 16_777_216, 1000, 16384),
    };
    proto::ResourceBudget {
        cpu_fuel: cpu,
        memory_bytes: memory,
        wall_time_limit_millis: Some(wall),
        log_bytes: logs,
        ..Default::default()
    }
}
pub(super) fn budget(value: &proto::ResourceBudget) -> Value {
    json!({"cpu_fuel":value.cpu_fuel.to_string(),"memory_bytes":value.memory_bytes.to_string(),"wall_time_limit_millis":value.wall_time_limit_millis.map(|n|n.to_string()),"log_bytes":value.log_bytes.to_string(),"reserved_dimensions_zero":value.child_calls==0 && value.outbound_requests==0 && value.state_read_bytes==0 && value.state_write_bytes==0 && value.blob_read_bytes==0 && value.blob_write_bytes==0 && value.effect_count==0})
}
pub(super) fn auth<T>(value: T, tenant: &str, timeout: Duration) -> Result<tonic::Request<T>> {
    let credential = match tenant {
        "engine-a" => "Bearer engine-credential-a-0000000000000000",
        "engine-b" => "Bearer engine-credential-b-0000000000000000",
        _ => return Err("engine credential tenant".into()),
    };
    let mut request = tonic::Request::new(value);
    request
        .metadata_mut()
        .insert("authorization", credential.parse()?);
    request.set_timeout(timeout);
    Ok(request)
}
pub(super) async fn invoke(channel: Channel, clock: Clock, offer: Offer) -> Result<Value> {
    let deadline = offer
        .scheduled
        .checked_add(5_000_000_000)
        .ok_or("engine deadline overflow")?;
    let absolute = (clock.unix_nanos + deadline).div_ceil(1_000_000);
    let marker = if offer.target.tenant == "engine-a" {
        "a"
    } else {
        "b"
    };
    let payload = serde_json::to_vec(&offer.payload)?;
    let mut row = json!({"kind":"invoke","ordinal":offer.ordinal.to_string(),"command_ordinal":offer.command_ordinal.to_string(),"phase":offer.phase,"phase_kind":offer.phase_kind,"index":offer.index.to_string(),"activation_id":offer.id,
        "target":{"tenant":offer.target.tenant,"service":offer.target.service,"contract":offer.target.contract,"function":offer.function},"release_digest":offer.target.release_digest,"route_generation":"8",
        "request":{"payload":{"utf8":std::str::from_utf8(&payload)?,"sha256":content_digest(&payload).0,"bytes":payload.len().to_string()},"budget":budget(&offer.grant),"root":format!("engine-root-{marker}"),"parent":format!("engine-parent-{marker}"),"metadata":{"guest.marker":marker,"internal.secret":format!("private-{marker}")}},
        "scheduled_nanos":offer.scheduled.to_string(),"deadline_nanos":deadline.to_string(),"deadline_unix_millis":absolute.to_string(),"absolute_deadline_quantization_nanos":(absolute*1_000_000-clock.unix_nanos-deadline).to_string(),"dispatch_nanos":Value::Null,"dispatch_lag_nanos":Value::Null,"grpc_timeout_header":Value::Null,"rpc_received":false,"response":Value::Null,"valid_response":false});
    let dispatch = clock.elapsed();
    if dispatch >= deadline {
        row["outcome"] = json!("client-deadline-before-dispatch");
    } else {
        let request = proto::InvokeRequest {
            activation_id: Some(offer.id.clone()),
            root_activation_id: Some(format!("engine-root-{marker}")),
            parent_activation_id: Some(format!("engine-parent-{marker}")),
            target: Some(proto::InvocationTarget {
                tenant: offer.target.tenant.clone(),
                service: offer.target.service.clone(),
                contract: offer.target.contract.clone(),
                function: offer.function.clone(),
                route: None,
            }),
            payload,
            media_type: MEDIA.into(),
            deadline_unix_millis: Some(u64::try_from(absolute)?),
            budget: Some(offer.grant),
            metadata: std::collections::HashMap::from([
                ("guest.marker".into(), marker.into()),
                ("internal.secret".into(), format!("private-{marker}")),
            ]),
            ..Default::default()
        };
        let request = auth(
            request,
            &offer.target.tenant,
            Duration::from_nanos(u64::try_from(deadline - dispatch)?),
        )?;
        row["dispatch_nanos"] = json!(dispatch.to_string());
        row["dispatch_lag_nanos"] = json!((dispatch - offer.scheduled).to_string());
        row["grpc_timeout_header"] = json!(request
            .metadata()
            .get("grpc-timeout")
            .ok_or("engine timeout missing")?
            .to_str()?);
        let result = tokio::time::timeout_at(
            tokio::time::Instant::from_std(
                clock.origin + Duration::from_nanos(u64::try_from(deadline)?),
            ),
            InvocationServiceClient::new(channel).invoke(request),
        )
        .await;
        // Completion is sampled before payload validation, logs, timings or status.
        row["completed_nanos"] = json!(clock.elapsed().to_string());
        match result {
            Ok(Ok(value)) => response(&offer, &mut row, &value.into_inner()),
            Ok(Err(error)) => {
                row["outcome"] = json!("transport-failure");
                row["grpc_code"] = json!(error.code() as i32);
            }
            Err(_) => row["outcome"] = json!("client-timeout"),
        }
    }
    if row["completed_nanos"].is_null() {
        row["completed_nanos"] = json!(clock.elapsed().to_string());
    }
    let completed = row["completed_nanos"]
        .as_str()
        .ok_or("engine completion")?
        .parse::<u128>()?;
    row["overshoot_nanos"] = json!(completed.saturating_sub(deadline).to_string());
    Ok(row)
}
fn response(offer: &Offer, row: &mut Value, response: &proto::InvokeResponse) {
    let mut details = Value::Null;
    let (outcome, code, semantic, payload) = match &response.result {
        Some(proto::invoke_response::Result::Success(value)) => {
            let parsed = serde_json::from_slice::<Value>(&value.payload).ok();
            let valid = value.media_type == MEDIA
                && parsed.is_some()
                && offer
                    .expected
                    .as_ref()
                    .is_none_or(|expected| parsed.as_ref() == Some(expected))
                && offer.expected_code.is_none();
            (
                "success",
                None,
                valid,
                json!({"value":parsed,"utf8":std::str::from_utf8(&value.payload).ok(),"sha256":content_digest(&value.payload).0,"bytes":value.payload.len().to_string(),"media_type":value.media_type}),
            )
        }
        Some(proto::invoke_response::Result::PlatformFailure(error)) => {
            details = json!(error
                .detail_items
                .iter()
                .map(|item| json!({"kind":item.kind,"fields":item.fields}))
                .collect::<Vec<_>>());
            (
                "platform-failure",
                Some(error.code.clone()),
                offer.expected_code == Some(error.code.as_str()),
                Value::Null,
            )
        }
        Some(proto::invoke_response::Result::DeclaredError(_)) => {
            ("declared-error", None, false, Value::Null)
        }
        None => ("invalid-response", None, false, Value::Null),
    };
    let consumption = super::super::cold::call::consumption(response.consumption.as_ref());
    let within = response.consumption.as_ref().is_some_and(|v| {
        v.cpu_fuel > 0
            && v.cpu_fuel <= offer.grant.cpu_fuel
            && v.peak_memory_bytes > 0
            && v.peak_memory_bytes <= offer.grant.memory_bytes
            && v.log_bytes <= offer.grant.log_bytes
            && v.child_calls == 0
            && v.outbound_requests == 0
            && v.state_read_bytes == 0
            && v.state_write_bytes == 0
            && v.blob_read_bytes == 0
            && v.blob_write_bytes == 0
            && v.effect_count == 0
    });
    row["rpc_received"] = json!(true);
    row["outcome"] = json!(outcome);
    row["valid_response"] = json!(
        semantic
            && within
            && response.activation_id == offer.id
            && response.release_digest == offer.target.release_digest
            && response.route_generation == 8
            && !response.revision_id.is_empty()
    );
    row["response"] = json!({"activation_id":response.activation_id,"release_digest":response.release_digest,"revision_id":response.revision_id,"route_generation":response.route_generation.to_string(),"code":code,"details":details,"payload":payload,"consumption":consumption});
}
