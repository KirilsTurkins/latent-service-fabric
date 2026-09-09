use std::time::{Duration, Instant};

use super::{
    BudgetError, ClockSample, EffectiveActivationBudget, EffectiveDeadline, ResourceBudget,
};

/// An exact deadline already normalized by trusted local ingress code.
///
/// The monotonic value is timing authority in the admission clock's domain.
/// The Unix value is its diagnostic projection, never a second constraint to
/// reconstruct after a wall-clock change or whole-millisecond rounding.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct IncomingDeadline {
    monotonic: Instant,
    unix_millis: u64,
}

impl IncomingDeadline {
    /// Constructs a trusted-local constraint, not a caller-deserializable value.
    /// The caller must have already intersected all incoming absolute and
    /// transport constraints in the same monotonic domain used for admission.
    #[must_use]
    pub const fn new(monotonic: Instant, unix_millis: u64) -> Self {
        Self {
            monotonic,
            unix_millis,
        }
    }

    #[must_use]
    pub const fn monotonic(&self) -> Instant {
        self.monotonic
    }

    #[must_use]
    pub const fn unix_millis(&self) -> u64 {
        self.unix_millis
    }
}

impl EffectiveActivationBudget {
    /// Intersects exact incoming timing authority with the effective relative
    /// wall ceiling anchored once at admission. Diagnostic Unix milliseconds
    /// cannot shorten or extend the resulting monotonic deadline.
    pub fn admit_with_deadline_at(
        request: &ResourceBudget,
        deployment_ceiling: &ResourceBudget,
        node_ceiling: &ResourceBudget,
        incoming: &IncomingDeadline,
        sample: ClockSample,
    ) -> Result<Self, BudgetError> {
        let budget = ResourceBudget::phase1_effective(request, deployment_ceiling, node_ceiling)?;
        let admitted_at_monotonic = sample.monotonic();
        let admitted_at_unix_millis = sample.unix_millis();
        let mut monotonic = incoming.monotonic();
        let mut unix_millis = incoming.unix_millis();
        if monotonic <= admitted_at_monotonic {
            return Err(BudgetError::DeadlineExceeded {
                deadline_unix_millis: unix_millis,
                admitted_at_unix_millis,
            });
        }
        if let Some(millis) = budget.wall_time_limit_millis {
            let relative = Duration::from_millis(millis);
            // Compare before addition: an irrelevant very large relative
            // ceiling need not be representable when incoming is earlier.
            if relative < monotonic.duration_since(admitted_at_monotonic) {
                unix_millis = admitted_at_unix_millis.saturating_add(millis);
                monotonic = admitted_at_monotonic.checked_add(relative).ok_or(
                    BudgetError::DeadlineOutOfRange {
                        deadline_unix_millis: unix_millis,
                        admitted_at_unix_millis,
                    },
                )?;
            }
        }
        if monotonic <= admitted_at_monotonic {
            return Err(BudgetError::DeadlineExceeded {
                deadline_unix_millis: unix_millis,
                admitted_at_unix_millis,
            });
        }
        Ok(Self {
            budget,
            deadline: EffectiveDeadline {
                admitted_at_unix_millis,
                admitted_at_monotonic,
                unix_millis: Some(unix_millis),
                monotonic: Some(monotonic),
            },
        })
    }
}

#[cfg(test)]
mod tests;
