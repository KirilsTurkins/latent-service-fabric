use super::*;

fn busy() -> PlatformError {
    super::super::error(PlatformErrorCode::Unavailable, "admission-authority-busy")
}

#[tokio::test]
async fn startup_yields_then_retries_only_the_read_that_was_busy() {
    let mut attempts = 0;
    let value = check(true, || {
        attempts += 1;
        if attempts == 1 {
            Err(busy())
        } else {
            Ok(42)
        }
    })
    .await
    .unwrap();
    assert_eq!(value, 42);
    assert_eq!(attempts, 2);
}

#[tokio::test]
async fn normal_control_checks_and_non_busy_errors_never_retry() {
    for (recovery, failure) in [
        (false, busy()),
        (
            true,
            super::super::error(
                PlatformErrorCode::PermissionDenied,
                "admission-authority-busy",
            ),
        ),
        (
            true,
            super::super::error(
                PlatformErrorCode::Unavailable,
                "admission-clock-lease-uncovered",
            ),
        ),
    ] {
        let mut attempts = 0;
        let result: Result<(), _> = check(recovery, || {
            attempts += 1;
            Err(failure.clone())
        })
        .await;
        assert_eq!(result.unwrap_err(), failure);
        assert_eq!(attempts, 1);
    }
}

#[tokio::test]
async fn exhausted_startup_budget_does_not_schedule_another_wait() {
    let retry = Retry {
        deadline: Some(Instant::now()),
    };
    assert!(!retry.pause(&busy()).await);
}
