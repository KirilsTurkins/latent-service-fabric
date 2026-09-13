//! Startup may briefly race audit bookkeeping. Retry only its non-mutating read,
//! within the original startup deadline and on the existing control worker.
use crate::Result;
use latent_audit::{AuditHandle, AuditPendingAttempt};
use latent_core::PlatformErrorCode;
use std::time::{Duration, Instant};

pub(super) async fn read(
    audit: &AuditHandle,
    expires: Instant,
) -> Result<Vec<AuditPendingAttempt>> {
    retry(|| audit.pending_attempts(), expires).await
}

async fn retry(
    mut read: impl FnMut() -> Result<Vec<AuditPendingAttempt>>,
    expires: Instant,
) -> Result<Vec<AuditPendingAttempt>> {
    loop {
        if Instant::now() >= expires {
            return Err(crate::deadline());
        }
        match read() {
            Err(failure)
                if failure.code == PlatformErrorCode::ResourceExhausted
                    && failure.message == "audit-busy" =>
            {
                tokio::time::sleep_until(
                    expires
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

    #[tokio::test]
    async fn brief_bookkeeping_contention_does_not_fail_startup() {
        let mut calls = 0;
        let result = retry(
            || {
                calls += 1;
                if calls < 3 {
                    Err(crate::capacity("audit-busy"))
                } else {
                    Ok(Vec::new())
                }
            },
            Instant::now() + Duration::from_secs(1),
        )
        .await
        .unwrap();
        assert!(result.is_empty());
        assert_eq!(calls, 3);
    }

    #[tokio::test]
    async fn capacity_and_other_audit_errors_are_not_retried() {
        let mut calls = 0;
        let failure = retry(
            || {
                calls += 1;
                Err(crate::capacity("audit-capacity"))
            },
            Instant::now() + Duration::from_secs(1),
        )
        .await
        .unwrap_err();
        assert_eq!(failure.message, "audit-capacity");
        assert_eq!(calls, 1);
    }

    #[tokio::test]
    async fn original_deadline_bounds_contention_and_prevents_expired_reads() {
        let mut calls = 0;
        let failure = retry(
            || {
                calls += 1;
                Err(crate::capacity("audit-busy"))
            },
            Instant::now(),
        )
        .await
        .unwrap_err();
        assert_eq!(failure.code, PlatformErrorCode::DeadlineExceeded);
        assert_eq!(calls, 0);
        let failure = retry(
            || Err(crate::capacity("audit-busy")),
            Instant::now() + Duration::from_millis(2),
        )
        .await
        .unwrap_err();
        assert_eq!(failure.code, PlatformErrorCode::DeadlineExceeded);
    }
}
