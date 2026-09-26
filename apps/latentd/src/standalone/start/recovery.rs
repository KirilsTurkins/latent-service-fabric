use std::{future::Future, time::Duration, time::Instant};

use latent_artifacts::ArtifactRepository;
use latent_audit::AuditHandle;
use latent_core::{PlatformError, PlatformErrorCode};

pub(super) async fn reconcile(
    audit: &AuditHandle,
    repository: &dyn ArtifactRepository,
    deadline: Instant,
) -> Result<(), PlatformError> {
    wait_before_admission(
        || latent_capabilities::broker::reconcile_capability_audit(audit, deadline),
        deadline,
    )
    .await?;
    wait_before_admission(
        || latent_artifacts::reconcile_release_audit(audit, repository),
        deadline,
    )
    .await
}

async fn wait_before_admission<Operation>(
    mut operation: impl FnMut() -> Operation,
    deadline: Instant,
) -> Result<(), PlatformError>
where
    Operation: Future<Output = Result<(), PlatformError>>,
{
    loop {
        if Instant::now() >= deadline {
            return Err(expired());
        }
        match tokio::time::timeout_at(deadline.into(), operation())
            .await
            .map_err(|_| expired())?
        {
            Err(failure)
                if failure.code == PlatformErrorCode::ResourceExhausted
                    && failure.message == "audit-busy" =>
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

fn expired() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::DeadlineExceeded,
        message: "startup-audit-recovery-deadline".into(),
        retryable: false,
        details: Vec::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{cell::Cell, future::ready};

    fn failure(code: PlatformErrorCode, message: &str) -> PlatformError {
        PlatformError {
            code,
            message: message.into(),
            retryable: false,
            details: Vec::new(),
        }
    }

    #[tokio::test]
    async fn only_pre_admission_audit_contention_waits_before_one_success() {
        let attempts = Cell::new(0);
        let accepted = Cell::new(0);
        wait_before_admission(
            || {
                attempts.set(attempts.get() + 1);
                ready(if attempts.get() < 3 {
                    Err(failure(PlatformErrorCode::ResourceExhausted, "audit-busy"))
                } else {
                    accepted.set(accepted.get() + 1);
                    Ok(())
                })
            },
            Instant::now() + Duration::from_secs(1),
        )
        .await
        .unwrap();
        assert_eq!(attempts.get(), 3);
        assert_eq!(accepted.get(), 1);
    }

    #[tokio::test]
    async fn real_capacity_and_uncertain_write_failures_are_never_replayed() {
        for (code, message) in [
            (PlatformErrorCode::ResourceExhausted, "audit-capacity"),
            (PlatformErrorCode::Unavailable, "audit-write-uncertain"),
            (PlatformErrorCode::Unavailable, "audit-busy"),
        ] {
            let attempts = Cell::new(0);
            let result = wait_before_admission(
                || {
                    attempts.set(attempts.get() + 1);
                    ready(Err(failure(code, message)))
                },
                Instant::now() + Duration::from_secs(1),
            )
            .await
            .unwrap_err();
            assert_eq!(result.code, code);
            assert_eq!(result.message, message);
            assert_eq!(attempts.get(), 1);
        }
    }

    #[tokio::test]
    async fn original_deadline_bounds_busy_reads_and_pending_acknowledgements() {
        let attempts = Cell::new(0);
        let result = wait_before_admission(
            || {
                attempts.set(attempts.get() + 1);
                ready(Ok(()))
            },
            Instant::now(),
        )
        .await
        .unwrap_err();
        assert_eq!(result.code, PlatformErrorCode::DeadlineExceeded);
        assert_eq!(attempts.get(), 0);
        let result = wait_before_admission(
            || {
                ready(Err(failure(
                    PlatformErrorCode::ResourceExhausted,
                    "audit-busy",
                )))
            },
            Instant::now() + Duration::from_millis(3),
        )
        .await
        .unwrap_err();
        assert_eq!(result.code, PlatformErrorCode::DeadlineExceeded);
        let result = wait_before_admission(
            std::future::pending,
            Instant::now() + Duration::from_millis(3),
        )
        .await
        .unwrap_err();
        assert_eq!(result.code, PlatformErrorCode::DeadlineExceeded);
    }
}
