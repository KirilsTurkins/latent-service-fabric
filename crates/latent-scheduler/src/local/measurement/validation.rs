use latent_core::PlatformErrorCode;

use super::input::{Plan, Settings};
use super::offer::Row;
use super::{Result, Run};

pub(super) fn validate(plan: &Plan, settings: &Settings, run: &Run) -> Result<()> {
    if run.rows.len() != usize::try_from(settings.measured_offers + settings.warmup_offers)?
        || run.finished < run.started
        || run.rows.iter().enumerate().any(|(index, row)| {
            usize::try_from(row.ordinal) != Ok(index)
                || row.cleanup_reclaimed
                || !expected_outcome(plan, row)
        })
    {
        return Err("scheduler incomplete or unexpected outcomes".into());
    }
    if plan.storm()
        && (run
            .rows
            .iter()
            .filter(|row| row.outcome == "released")
            .count()
            != 36
            || run
                .rows
                .iter()
                .filter(|row| row.cancel_accepted == Some(true))
                .count()
                != 32)
    {
        return Err("scheduler storm conservation".into());
    }

    if run
        .checkpoints
        .iter()
        .any(|row| row["work"]["overflowed"] != false)
    {
        return Err("scheduler mechanism counter overflow".into());
    }
    Ok(())
}

fn expected_outcome(plan: &Plan, row: &Row) -> bool {
    if row.role == "warmup" || matches!(plan.case.as_str(), "closed-one" | "reference-many") {
        return row.outcome == "released" && row.error.is_none();
    }
    if plan.storm() {
        return if row.cancel_requested.is_some() {
            row.outcome == "scheduler-error"
                && row.cancel_accepted == Some(true)
                && row
                    .error
                    .as_ref()
                    .is_some_and(|error| error.code == PlatformErrorCode::Cancelled)
        } else {
            row.outcome == "released" && row.error.is_none()
        };
    }
    match row.outcome {
        "released" | "backpressure" => row.error.is_none(),
        "admission-error" => row.error.as_ref().is_some_and(|error| {
            matches!(
                error.code,
                PlatformErrorCode::ResourceExhausted
                    | PlatformErrorCode::DeadlineExceeded
                    | PlatformErrorCode::AdmissionRejected
            )
        }),
        "scheduler-error" => row.error.as_ref().is_some_and(|error| {
            matches!(
                error.code,
                PlatformErrorCode::ResourceExhausted | PlatformErrorCode::DeadlineExceeded
            )
        }),
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::local::measurement::Clock;
    use latent_core::PlatformError;
    use std::time::Instant;

    #[test]
    fn terminal_fixture_errors_cannot_qualify_as_saturation_or_clean_completion() {
        let plan = Plan {
            schema: "latent.optimization.scheduler-plan.v1".to_owned(),
            profile: "smoke".to_owned(),
            variant: "control".to_owned(),
            case: "saturated-one".to_owned(),
            mode: "normal".to_owned(),
            observation_hold_millis: 100,
        };
        let mut row = Row::new(0, 0, "measured", 0, Clock(Instant::now()));
        row.outcome = "scheduler-error";
        row.error = Some(PlatformError {
            code: PlatformErrorCode::InvalidArgument,
            message: "wrong fixture".to_owned(),
            retryable: false,
            details: vec![],
        });
        assert!(!expected_outcome(&plan, &row));
        row.error.as_mut().unwrap().code = PlatformErrorCode::ResourceExhausted;
        assert!(expected_outcome(&plan, &row));
        row.role = "warmup";
        assert!(!expected_outcome(&plan, &row));
    }
}
