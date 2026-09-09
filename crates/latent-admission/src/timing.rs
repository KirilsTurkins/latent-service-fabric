use std::time::{Duration, Instant};

use latent_core::{
    ActivationClock, DeadlineDiagnosticDecision, DeadlineDiagnosticObservation,
    DeadlineDiagnosticObserver, DeadlineDiagnosticToken, EffectiveActivationBudget, PlatformError,
    PlatformErrorCode,
};

use crate::{rejection, NodeAdmissionPolicy};

#[derive(Clone, Copy)]
pub(crate) enum AdmissionClock<'a> {
    Live,
    Fixed(Instant),
    Injected(&'a dyn ActivationClock),
}

impl AdmissionClock<'_> {
    pub(crate) fn now(self) -> Instant {
        match self {
            Self::Live => Instant::now(),
            Self::Fixed(now) => now,
            Self::Injected(clock) => clock.monotonic_now(),
        }
    }
}

#[derive(Clone, Copy)]
pub(crate) struct ReservationTiming<'a> {
    pub clock: AdmissionClock<'a>,
    pub observed_queue_delay_millis: u64,
    pub load_observed_at: Instant,
    pub diagnostic: Option<(&'a DeadlineDiagnosticObserver, DeadlineDiagnosticToken)>,
}

impl ReservationTiming<'_> {
    /// Invoked inside the quota critical section, after any lock contention.
    /// Live admissions resample monotonic time without extending the original
    /// deadline; `admit_at` deliberately uses its frozen test/embedding clock.
    pub fn validate(
        self,
        policy: &NodeAdmissionPolicy,
        grant: &EffectiveActivationBudget,
        current_cell: u32,
        parallelism: u32,
    ) -> Result<(), PlatformError> {
        let now = self.clock.now();
        let record = |required, decision| {
            if let Some((observer, token)) = self.diagnostic {
                observer.record(
                    token,
                    DeadlineDiagnosticObservation::AdmissionCheck {
                        observed_at: now,
                        deadline: grant.deadline.clone(),
                        remaining: grant.deadline.remaining_at(now),
                        required,
                        decision,
                    },
                );
            }
        };
        if grant.deadline.is_expired_at(now) {
            record(None, DeadlineDiagnosticDecision::DeadlineExceeded);
            return Err(rejection(
                PlatformErrorCode::DeadlineExceeded,
                "request",
                "deadline",
                "deadline-exceeded",
            ));
        }
        if now
            .checked_duration_since(self.load_observed_at)
            .is_none_or(|age| {
                age > Duration::from_millis(policy.overload.maximum_sample_age_millis)
            })
        {
            record(None, DeadlineDiagnosticDecision::LoadStale);
            return Err(rejection(
                PlatformErrorCode::Unavailable,
                "node",
                "load",
                "load-sample-not-current",
            ));
        }
        let required = required_wait(
            policy,
            current_cell,
            parallelism,
            self.observed_queue_delay_millis,
        )
        .ok_or_else(|| {
            record(None, DeadlineDiagnosticDecision::QueueEstimateOverflow);
            rejection(
                PlatformErrorCode::AdmissionRejected,
                "node",
                "deadline",
                "queue-estimate-overflow",
            )
        })?;
        let remaining = grant.deadline.remaining_at(now).ok_or_else(|| {
            record(Some(required), DeadlineDiagnosticDecision::MissingDeadline);
            rejection(
                PlatformErrorCode::InvalidArgument,
                "request",
                "deadline",
                "missing-effective-deadline",
            )
        })?;
        if remaining <= required {
            record(Some(required), DeadlineDiagnosticDecision::QueueInfeasible);
            return Err(rejection(
                PlatformErrorCode::AdmissionRejected,
                "node",
                "deadline",
                "queue-deadline-infeasible",
            ));
        }
        record(Some(required), DeadlineDiagnosticDecision::Accepted);
        Ok(())
    }
}

fn required_wait(
    policy: &NodeAdmissionPolicy,
    current_cell: u32,
    parallelism: u32,
    observed_queue_delay_millis: u64,
) -> Option<Duration> {
    let waves = u64::from(current_cell) / u64::from(parallelism);
    waves
        .checked_mul(policy.deadline.estimated_service_time_millis)
        .map(|estimate| estimate.max(observed_queue_delay_millis))
        .and_then(|wait| wait.checked_add(policy.deadline.minimum_execution_time_millis))
        .and_then(|wait| wait.checked_add(policy.deadline.safety_margin_millis))
        .map(Duration::from_millis)
}
