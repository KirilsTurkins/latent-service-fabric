use crate::management::proto;
use latent_control_store::rollouts::RolloutCanaryPolicy;
use tonic::Status;

pub(in crate::management::rollouts) fn decode(
    value: &proto::RolloutCanaryPolicy,
) -> Result<RolloutCanaryPolicy, Status> {
    let failure = value.maximum_failure_basis_points.ok_or_else(invalid)?;
    let slow = value.maximum_slow_basis_points.ok_or_else(invalid)?;
    if value.format_version != 1
        || !(1..=3_600_000).contains(&value.observation_millis)
        || !(1..=1_000_000).contains(&value.minimum_candidate_samples)
        || failure > 9999
        || slow > 10_000
        || ![
            100, 1000, 5000, 10_000, 50_000, 100_000, 1_000_000, 10_000_000,
        ]
        .contains(&value.latency_threshold_micros)
    {
        return Err(invalid());
    }
    Ok(RolloutCanaryPolicy {
        format_version: value.format_version,
        observation_millis: value.observation_millis,
        minimum_candidate_samples: value.minimum_candidate_samples,
        maximum_failure_basis_points: u16::try_from(failure).map_err(|_| invalid())?,
        latency_threshold_micros: value.latency_threshold_micros,
        maximum_slow_basis_points: u16::try_from(slow).map_err(|_| invalid())?,
    })
}

pub(in crate::management::rollouts) fn wire(
    value: RolloutCanaryPolicy,
) -> proto::RolloutCanaryPolicy {
    proto::RolloutCanaryPolicy {
        format_version: value.format_version,
        observation_millis: value.observation_millis,
        minimum_candidate_samples: value.minimum_candidate_samples,
        maximum_failure_basis_points: Some(u32::from(value.maximum_failure_basis_points)),
        latency_threshold_micros: value.latency_threshold_micros,
        maximum_slow_basis_points: Some(u32::from(value.maximum_slow_basis_points)),
    }
}

fn invalid() -> Status {
    Status::invalid_argument("invalid explicit rollout canary policy")
}
