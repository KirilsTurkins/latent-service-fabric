//! Actual covered authority plus the original wall/monotonic process clock.
use std::sync::{Arc, Mutex};

use latent_core::{ActivationClock, ClockSample};
use latent_effects::{authority::EffectTime, runtime::EffectTimeSource};
use latent_policy::supply_chain::{CoveredClock, CoveredClockSource, SupplyChainAuthority};
use latent_state::store_identity::ExternalCheckpoint;

use super::{error, PlatformError, PlatformErrorCode};

const MAXIMUM_DRIFT_MILLIS: u64 = 1000;

struct Observation {
    anchor: ClockSample,
    last: ClockSample,
    authority_epoch: u64,
    rejected: bool,
}

/// Constructed only after inspecting the actual external checkpoint and its
/// coherent store owner. Neither a caller timestamp nor a configuration bit
/// can create continuity. Busy authority rejects this observation; actual
/// regression, lost coverage or uncertainty irreversibly rejects this clock.
pub struct ProtectedEffectClock {
    original: Arc<dyn ActivationClock>,
    _authority: Arc<SupplyChainAuthority>,
    coverage: CoveredClockSource,
    observation: Mutex<Observation>,
}

impl ProtectedEffectClock {
    pub(super) fn admit(
        original: Arc<dyn ActivationClock>,
        authority: Arc<SupplyChainAuthority>,
        checkpoint: Option<&ExternalCheckpoint>,
    ) -> Result<Arc<Self>, PlatformError> {
        let sample = original.sample();
        let coverage = authority.covered_clock_source();
        let covered = coverage.sample()?;
        let floor = checkpoint.map_or(0, ExternalCheckpoint::clock_floor_millis);
        let epoch = checkpoint.map_or(0, ExternalCheckpoint::protected_clock_epoch);
        if sample.unix_millis() < floor
            || covered.authority_epoch < epoch
            || !covered_sample(sample, covered)
        {
            return Err(unavailable());
        }
        Ok(Arc::new(Self {
            original,
            _authority: authority,
            coverage,
            observation: Mutex::new(Observation {
                anchor: sample,
                last: sample,
                authority_epoch: covered.authority_epoch,
                rejected: false,
            }),
        }))
    }

    /// One accepted pair, also suitable for a command's original deadline.
    /// The authority uses its bounded currentness read, without filesystem I/O
    /// or renewal. No consumer substitutes a later wall-clock sample.
    pub fn sample(&self) -> Result<ClockSample, PlatformError> {
        let sample = self.original.sample();
        // This exact original owner's sealed metadata remains readable inside
        // its current admission fence, without recursively locking its ledger.
        let coverage = self.coverage.sample();
        let mut state = self.observation.lock().map_err(|_| unavailable())?;
        if state.rejected || !continuous(&state, sample) {
            state.rejected = true;
            return Err(unavailable());
        }
        let covered = match coverage {
            Ok(covered) => covered,
            Err(error) if error.message == "admission-authority-busy" => {
                // Contention grants no positive observation, and does not
                // manufacture evidence of a clock rollback or a new lease.
                state.last = sample;
                return Err(error);
            }
            Err(error) => {
                state.rejected = true;
                return Err(error);
            }
        };
        if covered.authority_epoch < state.authority_epoch || !covered_sample(sample, covered) {
            state.rejected = true;
            return Err(unavailable());
        }
        state.last = sample;
        state.authority_epoch = covered.authority_epoch;
        Ok(sample)
    }

    pub(super) fn covered_epoch(&self) -> Result<u64, PlatformError> {
        self.sample()?;
        let state = self.observation.lock().map_err(|_| unavailable())?;
        if state.rejected {
            return Err(unavailable());
        }
        Ok(state.authority_epoch)
    }
}

impl EffectTimeSource for ProtectedEffectClock {
    fn observe(&self) -> EffectTime {
        match self.sample() {
            Ok(sample) => EffectTime {
                unix_millis: sample.unix_millis(),
                continuity_proven: true,
            },
            Err(_) => EffectTime {
                unix_millis: 0,
                continuity_proven: false,
            },
        }
    }
}

fn covered_sample(sample: ClockSample, covered: CoveredClock) -> bool {
    covered.authority_epoch != 0
        && covered.now_seconds < covered.covered_until_seconds
        && covered.now_seconds.checked_mul(1000).is_some_and(|floor| {
            sample.unix_millis().abs_diff(floor) <= MAXIMUM_DRIFT_MILLIS
                && covered
                    .covered_until_seconds
                    .checked_mul(1000)
                    .is_some_and(|until| sample.unix_millis() < until)
        })
}

fn continuous(state: &Observation, sample: ClockSample) -> bool {
    if sample.unix_millis() < state.last.unix_millis()
        || sample.monotonic() < state.last.monotonic()
    {
        return false;
    }
    sample
        .monotonic()
        .checked_duration_since(state.anchor.monotonic())
        .and_then(|elapsed| u64::try_from(elapsed.as_millis()).ok())
        .and_then(|elapsed| state.anchor.unix_millis().checked_add(elapsed))
        .is_some_and(|expected| sample.unix_millis().abs_diff(expected) <= MAXIMUM_DRIFT_MILLIS)
}

fn unavailable() -> PlatformError {
    error(
        PlatformErrorCode::Unavailable,
        "transaction clock continuity is unavailable",
    )
}

#[cfg(test)]
mod tests;
