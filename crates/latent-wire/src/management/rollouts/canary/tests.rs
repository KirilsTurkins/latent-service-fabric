use super::{policy, proto};

fn declaration() -> proto::RolloutCanaryPolicy {
    proto::RolloutCanaryPolicy {
        format_version: 1,
        observation_millis: 1,
        minimum_candidate_samples: 1,
        maximum_failure_basis_points: Some(0),
        latency_threshold_micros: 100,
        maximum_slow_basis_points: Some(0),
    }
}

#[test]
fn zero_thresholds_require_presence_and_preserve_explicit_zero() {
    let value = declaration();
    assert_eq!(policy::wire(policy::decode(&value).unwrap()), value);
    let mut absent = value;
    absent.maximum_failure_basis_points = None;
    assert!(policy::decode(&absent).is_err());
    let mut absent = value;
    absent.maximum_slow_basis_points = None;
    assert!(policy::decode(&absent).is_err());
}

#[test]
fn protocol_policy_cannot_narrow_overflow_or_invent_latency_precision() {
    for threshold in [10_000, 65_536, u32::MAX] {
        let mut value = declaration();
        value.maximum_failure_basis_points = Some(threshold);
        assert!(policy::decode(&value).is_err());
    }
    for threshold in [0, 99, 101, 10_000_001, u64::MAX] {
        let mut value = declaration();
        value.latency_threshold_micros = threshold;
        assert!(policy::decode(&value).is_err());
    }
    let mut value = declaration();
    value.observation_millis = 3_600_000;
    value.minimum_candidate_samples = 1_000_000;
    value.maximum_failure_basis_points = Some(9999);
    value.maximum_slow_basis_points = Some(10_000);
    assert!(policy::decode(&value).is_ok());
    value.observation_millis += 1;
    assert!(policy::decode(&value).is_err());
}
