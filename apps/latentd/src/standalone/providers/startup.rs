use latent_core::{PlatformError, PlatformErrorCode};
use std::time::{Duration, Instant};

pub(super) async fn admit<Ticket>(
    mut enqueue: impl FnMut() -> Result<Ticket, PlatformError>,
    deadline: Instant,
) -> Result<Ticket, PlatformError> {
    loop {
        if Instant::now() >= deadline {
            return Err(PlatformError {
                code: PlatformErrorCode::DeadlineExceeded,
                message: "provider-startup-admission-deadline".into(),
                retryable: false,
                details: Vec::new(),
            });
        }
        match enqueue() {
            Err(failure)
                if failure.code == PlatformErrorCode::ResourceExhausted
                    && failure.message == "capability-busy" =>
            {
                tokio::time::sleep_until(
                    deadline
                        .min(Instant::now() + Duration::from_millis(1))
                        .into(),
                )
                .await;
            }
            result => return result,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn failure(code: PlatformErrorCode, message: &str) -> PlatformError {
        PlatformError {
            code,
            message: message.into(),
            retryable: false,
            details: Vec::new(),
        }
    }

    #[tokio::test]
    async fn maintenance_contention_waits_only_until_one_ticket_is_admitted() {
        let mut attempts = 0;
        let mut jobs = 0;
        let ticket = admit(
            || {
                attempts += 1;
                if attempts < 3 {
                    Err(failure(
                        PlatformErrorCode::ResourceExhausted,
                        "capability-busy",
                    ))
                } else {
                    jobs += 1;
                    Ok(17)
                }
            },
            Instant::now() + Duration::from_secs(1),
        )
        .await
        .unwrap();
        assert_eq!(ticket, 17);
        assert_eq!(attempts, 3);
        assert_eq!(jobs, 1);
    }

    #[tokio::test]
    async fn real_capacity_and_uncertain_errors_never_admit_another_job() {
        for (code, message) in [
            (PlatformErrorCode::ResourceExhausted, "capability-capacity"),
            (PlatformErrorCode::Unavailable, "capability-busy"),
            (PlatformErrorCode::Unavailable, "provider-job-failed"),
        ] {
            let mut attempts = 0;
            let result = admit::<()>(
                || {
                    attempts += 1;
                    Err(failure(code, message))
                },
                Instant::now() + Duration::from_secs(1),
            )
            .await
            .unwrap_err();
            assert_eq!(result.code, code);
            assert_eq!(attempts, 1);
        }
    }

    #[tokio::test]
    async fn original_deadline_prevents_and_bounds_pre_admission_waits() {
        let mut attempts = 0;
        let result = admit(
            || {
                attempts += 1;
                Ok(())
            },
            Instant::now(),
        )
        .await
        .unwrap_err();
        assert_eq!(result.code, PlatformErrorCode::DeadlineExceeded);
        assert_eq!(attempts, 0);
        let result = admit::<()>(
            || {
                Err(failure(
                    PlatformErrorCode::ResourceExhausted,
                    "capability-busy",
                ))
            },
            Instant::now() + Duration::from_millis(3),
        )
        .await
        .unwrap_err();
        assert_eq!(result.code, PlatformErrorCode::DeadlineExceeded);
    }
}
