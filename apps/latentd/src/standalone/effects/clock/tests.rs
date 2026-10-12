use super::*;
use std::time::{Duration, Instant};

#[cfg(target_os = "linux")]
mod lifecycle;

fn observed(wall: u64, start: Instant) -> Observation {
    let sample = ClockSample::new(wall, start);
    Observation {
        anchor: sample,
        last: sample,
        authority_epoch: 1,
        rejected: false,
    }
}

#[test]
fn original_monotonic_progress_rejects_hidden_wall_and_monotonic_rollbacks() {
    let start = Instant::now();
    let mut state = observed(10_000, start);
    state.last = ClockSample::new(11_000, start + Duration::from_secs(1));
    assert!(continuous(
        &state,
        ClockSample::new(12_000, start + Duration::from_secs(2))
    ));
    assert!(!continuous(
        &state,
        ClockSample::new(10_999, start + Duration::from_secs(2))
    ));
    assert!(!continuous(&state, ClockSample::new(12_000, start)));
}

#[test]
fn original_anchor_bounds_forward_discontinuity_and_cumulative_drift() {
    let start = Instant::now();
    let mut state = observed(10_000, start);
    state.last = ClockSample::new(11_500, start + Duration::from_secs(1));
    assert!(!continuous(
        &state,
        ClockSample::new(13_001, start + Duration::from_secs(2))
    ));
    assert!(continuous(
        &state,
        ClockSample::new(13_000, start + Duration::from_secs(2))
    ));
    let overflowing = observed(u64::MAX, start);
    assert!(!continuous(
        &overflowing,
        ClockSample::new(u64::MAX, start + Duration::from_secs(1))
    ));
}

#[test]
fn actual_covered_clock_requires_nonzero_epoch_finite_lease_and_matching_wall() {
    let start = Instant::now();
    let covered = CoveredClock {
        now_seconds: 10,
        authority_epoch: 1,
        covered_until_seconds: 15,
    };
    assert!(covered_sample(ClockSample::new(10_999, start), covered));
    assert!(!covered_sample(ClockSample::new(11_001, start), covered));
    assert!(!covered_sample(
        ClockSample::new(10_000, start),
        CoveredClock {
            authority_epoch: 0,
            ..covered
        }
    ));
    assert!(!covered_sample(
        ClockSample::new(15_000, start),
        CoveredClock {
            now_seconds: 15,
            ..covered
        }
    ));
    assert!(!covered_sample(
        ClockSample::new(u64::MAX, start),
        CoveredClock {
            now_seconds: u64::MAX,
            covered_until_seconds: u64::MAX,
            ..covered
        }
    ));
}
