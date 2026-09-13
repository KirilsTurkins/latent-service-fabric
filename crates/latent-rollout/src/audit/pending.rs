//! Startup may briefly race audit bookkeeping. Retry only reads or a rejected
//! pre-enqueue lock acquisition, within the original deadline. Never retry an
//! accepted journal write or its acknowledgement.
use crate::Result;
use latent_audit::{AuditAppendTicket, AuditHandle, AuditOperationConclusion, AuditPendingAttempt};
use latent_core::PlatformErrorCode;
use std::time::{Duration, Instant};

pub(crate) async fn read(
    audit: &AuditHandle,
    expires: Instant,
) -> Result<Vec<AuditPendingAttempt>> {
    retry(|| audit.pending_attempts(), expires).await
}

pub(crate) async fn reconcile(
    audit: &AuditHandle,
    sequence: u64,
    conclusion: &AuditOperationConclusion,
    expires: Instant,
) -> Result<AuditAppendTicket> {
    // AuditHandle::reconcile can return audit-busy only before it obtains the
    // pending owner and calls finish. Once a ticket exists the caller waits once.
    retry(|| audit.reconcile(sequence, conclusion.clone()), expires).await
}

async fn retry<T>(mut read: impl FnMut() -> Result<T>, expires: Instant) -> Result<T> {
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
                    Ok(Vec::<AuditPendingAttempt>::new())
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
        let failure = retry::<()>(
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
        let failure = retry::<()>(
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
        let failure = retry::<()>(
            || Err(crate::capacity("audit-busy")),
            Instant::now() + Duration::from_millis(2),
        )
        .await
        .unwrap_err();
        assert_eq!(failure.code, PlatformErrorCode::DeadlineExceeded);
    }

    #[tokio::test]
    async fn enqueue_retries_stop_once_an_owned_ticket_or_uncertain_error_exists() {
        let mut attempts = 0;
        let mut enqueued = 0;
        let ticket = retry(
            || {
                attempts += 1;
                if attempts < 3 {
                    return Err(crate::capacity("audit-busy"));
                }
                enqueued += 1;
                Ok(17)
            },
            Instant::now() + Duration::from_secs(1),
        )
        .await
        .unwrap();
        assert_eq!(ticket, 17);
        assert_eq!(enqueued, 1);
        let mut uncertain_attempts = 0;
        let error = retry::<()>(
            || {
                uncertain_attempts += 1;
                Err(crate::error(
                    PlatformErrorCode::Unavailable,
                    "audit-write-uncertain",
                ))
            },
            Instant::now() + Duration::from_secs(1),
        )
        .await
        .unwrap_err();
        assert_eq!(error.code, PlatformErrorCode::Unavailable);
        assert_eq!(uncertain_attempts, 1);
    }
}
