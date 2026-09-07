use super::{proto, InvocationLimits};
use latent_core::ClockSample;
use std::time::{Duration, Instant};
use tonic::{Request, Status};

pub(super) struct DeadlinePlan {
    pub effective_unix_millis: Option<u64>,
    pub expires_at: Option<Instant>,
}

pub(super) fn plan(
    request: &Request<proto::InvokeRequest>,
    context: Option<u64>,
    sample: ClockSample,
    limits: &InvocationLimits,
) -> Result<DeadlinePlan, Status> {
    let caller = request.get_ref().deadline_unix_millis;
    let absolute = |value: u64| -> Result<Duration, Status> {
        let millis = value
            .checked_sub(sample.unix_millis())
            .filter(|n| *n > 0)
            .ok_or_else(|| Status::deadline_exceeded("the invocation deadline has expired"))?;
        if millis > limits.max_timeout_millis {
            return Err(Status::invalid_argument(
                "deadline exceeds the configured maximum",
            ));
        }
        Ok(Duration::from_millis(millis))
    };
    let caller_delay = caller.map(absolute).transpose()?;
    let context_delay = context.map(absolute).transpose()?;
    let transport_delay = grpc_timeout(request)?;
    if transport_delay == Some(Duration::ZERO) {
        return Err(Status::deadline_exceeded(
            "the invocation deadline has expired",
        ));
    }
    if transport_delay.is_some_and(|delay| delay > Duration::from_millis(limits.max_timeout_millis))
    {
        return Err(Status::invalid_argument(
            "transport timeout exceeds the configured maximum",
        ));
    }
    let transport_unix = transport_delay
        .map(|delay| {
            let millis = u64::try_from(delay.as_nanos().div_ceil(1_000_000))
                .map_err(|_| Status::invalid_argument("transport deadline overflow"))?;
            sample
                .unix_millis()
                .checked_add(millis)
                .ok_or_else(|| Status::invalid_argument("transport deadline overflow"))
        })
        .transpose()?;
    let delay = [caller_delay, context_delay, transport_delay]
        .into_iter()
        .flatten()
        .min();
    let expires_at = delay
        .map(|delay| {
            sample
                .monotonic()
                .checked_add(delay)
                .ok_or_else(|| Status::invalid_argument("monotonic deadline overflow"))
        })
        .transpose()?;
    Ok(DeadlinePlan {
        effective_unix_millis: [caller, context, transport_unix]
            .into_iter()
            .flatten()
            .min(),
        expires_at,
    })
}

fn grpc_timeout(request: &Request<proto::InvokeRequest>) -> Result<Option<Duration>, Status> {
    let all = request.metadata().get_all("grpc-timeout");
    let mut values = all.iter();
    let Some(value) = values.next() else {
        return Ok(None);
    };
    if values.next().is_some() {
        return Err(Status::invalid_argument("multiple transport timeouts"));
    }
    let value = value
        .to_str()
        .map_err(|_| Status::invalid_argument("invalid transport timeout"))?;
    if value.len() < 2 || value.len() > 9 {
        return Err(Status::invalid_argument("invalid transport timeout"));
    }
    let (digits, unit) = value.split_at(value.len() - 1);
    if !digits.bytes().all(|byte| byte.is_ascii_digit()) {
        return Err(Status::invalid_argument("invalid transport timeout"));
    }
    let value = digits
        .parse::<u64>()
        .map_err(|_| Status::invalid_argument("invalid transport timeout"))?;
    let duration = match unit {
        "H" => Duration::from_secs(value * 3600),
        "M" => Duration::from_secs(value * 60),
        "S" => Duration::from_secs(value),
        "m" => Duration::from_millis(value),
        "u" => Duration::from_micros(value),
        "n" => Duration::from_nanos(value),
        _ => return Err(Status::invalid_argument("invalid transport timeout unit")),
    };
    Ok(Some(duration))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn submillisecond_transport_timeout_keeps_exact_monotonic_expiry() {
        let sample = ClockSample::new(10_000, Instant::now());
        let mut request = Request::new(proto::InvokeRequest::default());
        request
            .metadata_mut()
            .insert("grpc-timeout", "1n".parse().unwrap());
        let result = plan(&request, None, sample, &InvocationLimits::default()).unwrap();
        assert_eq!(result.effective_unix_millis, Some(10_001));
        assert_eq!(
            result.expires_at,
            sample.monotonic().checked_add(Duration::from_nanos(1))
        );
        request
            .metadata_mut()
            .append("grpc-timeout", "2n".parse().unwrap());
        assert_eq!(
            plan(&request, None, sample, &InvocationLimits::default())
                .err()
                .unwrap()
                .code(),
            tonic::Code::InvalidArgument
        );
    }
}
