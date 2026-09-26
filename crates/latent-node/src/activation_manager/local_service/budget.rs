use latent_core::{ClockSample, IncomingDeadline, PlatformError, ResourceBudget};
use std::time::{Duration, Instant};

pub(super) fn incoming(
    sample: ClockSample,
    policy: Instant,
    requested_unix: Option<u64>,
) -> Result<IncomingDeadline, PlatformError> {
    let failure = super::super::control::deadline_error;
    let mut monotonic = policy;
    if let Some(unix) = requested_unix {
        let remaining = unix
            .checked_sub(sample.unix_millis())
            .filter(|value| *value > 0)
            .ok_or_else(failure)?;
        monotonic = monotonic.min(
            sample
                .monotonic()
                .checked_add(Duration::from_millis(remaining))
                .ok_or_else(failure)?,
        );
    }
    let remaining = monotonic
        .checked_duration_since(sample.monotonic())
        .filter(|remaining| !remaining.is_zero())
        .ok_or_else(failure)?;
    let millis = u64::try_from(remaining.as_millis()).map_err(|_| failure())?;
    Ok(IncomingDeadline::new(
        monotonic,
        sample.unix_millis().saturating_add(millis),
    ))
}

pub(super) fn share(mut remaining: ResourceBudget) -> ResourceBudget {
    remaining.cpu_fuel /= 2;
    remaining.memory_bytes /= 2;
    remaining.child_calls = remaining.child_calls.saturating_sub(1) / 2;
    remaining.outbound_requests /= 2;
    remaining.blob_read_bytes /= 2;
    remaining.blob_write_bytes /= 2;
    remaining.log_bytes /= 2;
    remaining.wall_time_limit_millis = remaining.wall_time_limit_millis.map(|value| value / 2);
    remaining
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn preserves_exact_policy_deadline_and_narrows_guest_unix_only_once() {
        let now = Instant::now();
        let policy = now + Duration::from_micros(1900);
        for unix in [1000, 1_000_000] {
            let sample = ClockSample::new(unix, now);
            assert_eq!(incoming(sample, policy, None).unwrap().monotonic(), policy);
            assert_eq!(
                incoming(sample, policy, Some(unix + 1000))
                    .unwrap()
                    .monotonic(),
                policy
            );
            assert_eq!(
                incoming(sample, policy, Some(unix + 1))
                    .unwrap()
                    .monotonic(),
                now + Duration::from_millis(1)
            );
            assert!(incoming(sample, policy, Some(unix)).is_err());
            assert!(incoming(sample, now, None).is_err());
        }
    }
}
