use std::time::Duration;

use latent_core::ActivationClock;
use latent_wire::invocation::AuthenticatedInvocationContext;
use tonic::body::Body;
use tonic::codegen::http::Request;
use tonic::Status;

use super::TransportConfig;

pub(super) fn authenticate(
    request: &mut Request<Body>,
    config: &TransportConfig,
    clock: &dyn ActivationClock,
) -> Result<(), Status> {
    // Capture before validation/cloning, while still inside Service::call and
    // before Tonic constructs its outer grpc-timeout sleep.
    let sample = clock.sample();
    let mut authorization = request.headers().get_all("authorization").iter();
    let token = authorization
        .next()
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.strip_prefix("Bearer "))
        .filter(|value| !value.is_empty() && value.len() <= 512)
        .ok_or_else(unauthenticated)?;
    if authorization.next().is_some() {
        return Err(unauthenticated());
    }
    let credential = config
        .credentials
        .iter()
        .find(|value| value.token == token)
        .ok_or_else(unauthenticated)?;
    let mut timeouts = request.headers().get_all("grpc-timeout").iter();
    let timeout = timeouts
        .next()
        .map(|value| {
            value
                .to_str()
                .map_err(|_| invalid_timeout())
                .and_then(parse_timeout)
        })
        .transpose()?
        .unwrap_or(config.request_timeout)
        .min(config.request_timeout);
    if timeouts.next().is_some() {
        return Err(invalid_timeout());
    }
    if timeout.is_zero() {
        return Err(Status::deadline_exceeded(
            "standalone request deadline has expired",
        ));
    }
    let expiry = sample
        .monotonic()
        .checked_add(timeout)
        .ok_or_else(invalid_timeout)?;
    let millis =
        u64::try_from(timeout.as_nanos().div_ceil(1_000_000)).map_err(|_| invalid_timeout())?;
    let unix = sample
        .unix_millis()
        .checked_add(millis)
        .ok_or_else(invalid_timeout)?;
    request.extensions_mut().insert(
        AuthenticatedInvocationContext::new(credential.principal.clone())
            .with_transport_deadline_at(unix, expiry),
    );
    Ok(())
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
    Status::invalid_argument("invalid standalone transport timeout")
}
fn unauthenticated() -> Status {
    Status::unauthenticated("a configured standalone credential is required")
}
