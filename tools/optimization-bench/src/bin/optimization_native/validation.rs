use std::time::{Duration, Instant};

use latent_optimization_workloads::{CONTRACT, MAX_PAYLOAD_BYTES, MEDIA_TYPE};
use latent_rpc::invocation::v1 as proto;
use prost::Message;
use tonic::{Request, Status};

use super::command::{MAXIMUM_IDENTIFIER_BYTES, MAXIMUM_MESSAGE_BYTES};

pub(super) fn authenticate<T>(request: &Request<T>, token: &str) -> Result<(), Status> {
    let mut values = request.metadata().get_all("authorization").iter();
    let supplied = values
        .next()
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.strip_prefix("Bearer "));
    if supplied != Some(token) || values.next().is_some() {
        return Err(Status::unauthenticated(
            "native reference credential required",
        ));
    }
    Ok(())
}

pub(super) fn request(
    value: &proto::InvokeRequest,
    tenant: &str,
    services: &[String],
) -> Result<(), Status> {
    if value.encoded_len() > MAXIMUM_MESSAGE_BYTES || value.payload.len() > MAX_PAYLOAD_BYTES {
        return Err(Status::resource_exhausted("native reference message limit"));
    }
    let target = value
        .target
        .as_ref()
        .ok_or_else(|| Status::invalid_argument("missing target"))?;
    if target.tenant != tenant {
        return Err(Status::permission_denied(
            "native reference tenant mismatch",
        ));
    }
    if !services.contains(&target.service) || target.contract != CONTRACT || target.route.is_some()
    {
        return Err(Status::not_found("native reference target not found"));
    }
    if !matches!(target.function.as_str(), "echo" | "compute" | "transform")
        || value.media_type != MEDIA_TYPE
    {
        return Err(Status::invalid_argument(
            "invalid native reference invocation",
        ));
    }
    for identifier in [
        &value.activation_id,
        &value.root_activation_id,
        &value.parent_activation_id,
        &value.idempotency_key,
    ]
    .into_iter()
    .flatten()
    {
        if identifier.is_empty() || identifier.len() > MAXIMUM_IDENTIFIER_BYTES {
            return Err(Status::invalid_argument(
                "invalid native reference identifier",
            ));
        }
    }
    if value.parent_activation_id.is_some() && value.root_activation_id.is_none() {
        return Err(Status::invalid_argument("parent activation requires root"));
    }
    if value.priority > u32::from(u8::MAX)
        || value.metadata.len() > 64
        || value
            .metadata
            .iter()
            .any(|(key, value)| key.is_empty() || key.len() > 512 || value.len() > 4096)
    {
        return Err(Status::invalid_argument("invalid native reference context"));
    }
    let budget = value
        .budget
        .as_ref()
        .ok_or_else(|| Status::invalid_argument("missing resource budget"))?;
    if budget.cpu_fuel == 0
        || budget.memory_bytes == 0
        || budget.child_calls != 0
        || budget.outbound_requests != 0
        || budget.state_read_bytes != 0
        || budget.state_write_bytes != 0
        || budget.blob_read_bytes != 0
        || budget.blob_write_bytes != 0
        || budget.effect_count != 0
    {
        return Err(Status::invalid_argument(
            "unsupported native reference budget",
        ));
    }
    Ok(())
}

pub(super) fn deadline(
    request: &Request<proto::InvokeRequest>,
    started: Instant,
    unix_millis: u64,
    maximum: Duration,
) -> Result<Instant, Status> {
    let mut duration = maximum;
    let value = request.get_ref();
    if let Some(wall) = value
        .budget
        .as_ref()
        .and_then(|budget| budget.wall_time_limit_millis)
    {
        duration = duration.min(Duration::from_millis(wall));
    }
    if let Some(absolute) = value.deadline_unix_millis {
        duration = duration.min(Duration::from_millis(absolute.saturating_sub(unix_millis)));
    }
    let mut timeouts = request.metadata().get_all("grpc-timeout").iter();
    if let Some(timeout) = timeouts.next() {
        duration = duration.min(parse_timeout(
            timeout.to_str().map_err(|_| invalid_timeout())?,
        )?);
    }
    if timeouts.next().is_some() {
        return Err(invalid_timeout());
    }
    started.checked_add(duration).ok_or_else(invalid_timeout)
}

fn parse_timeout(value: &str) -> Result<Duration, Status> {
    if !(2..=9).contains(&value.len()) || !value.is_ascii() {
        return Err(invalid_timeout());
    }
    let (number, unit) = value.split_at(value.len() - 1);
    if !number.bytes().all(|byte| byte.is_ascii_digit()) {
        return Err(invalid_timeout());
    }
    let number = number.parse::<u64>().map_err(|_| invalid_timeout())?;
    match unit {
        "H" => Ok(Duration::from_secs(number * 3600)),
        "M" => Ok(Duration::from_secs(number * 60)),
        "S" => Ok(Duration::from_secs(number)),
        "m" => Ok(Duration::from_millis(number)),
        "u" => Ok(Duration::from_micros(number)),
        "n" => Ok(Duration::from_nanos(number)),
        _ => Err(invalid_timeout()),
    }
}

fn invalid_timeout() -> Status {
    Status::invalid_argument("invalid native reference timeout")
}
