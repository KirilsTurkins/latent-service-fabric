use super::*;
use latent_core::{ErrorDetail, Metadata, PlatformErrorCode};
use latent_effects::{dispatch_store::DispatchStoreError, runtime::DispatcherError};
use latent_state::embedded::StoreError;
use std::sync::Arc;

#[tokio::test]
async fn finite_startup_trace_preserves_original_failure_and_excludes_private_error_data() {
    let original = PlatformError {
        code: PlatformErrorCode::Unavailable,
        message: "private-path bearer-secret".into(),
        retryable: true,
        details: vec![ErrorDetail {
            kind: "private-detail".into(),
            fields: Metadata::from([("credential".into(), "secret-value".into())]),
        }],
    };
    let (result, trace) = capture(async {
        record(
            Stage::EffectDispatcher,
            DispatcherError::Store(DispatchStoreError::Storage(StoreError::Corrupt)),
        );
        platform::<()>(Stage::StateClock, Err(original.clone()))
    })
    .await;
    assert_eq!(result, Err(original));
    let report = StartupFailureReport {
        schema_version: "latent.startup-failure-observation.v1",
        startup_succeeded: false,
        terminal_failure: result.as_ref().err().map(Failure::from),
        observations: trace.observations.into_iter().flatten().collect(),
        truncated: trace.truncated,
        shutdown: None,
    };
    let encoded = serde_json::to_string(&report).unwrap();
    let json: serde_json::Value = serde_json::from_str(&encoded).unwrap();
    assert_eq!(json["observations"][0]["failure"]["owner"], "storage");
    assert_eq!(json["observations"][0]["failure"]["reason"], "corrupt");
    assert_eq!(json["observations"][1]["stage"], "stateClock");
    assert_eq!(json["terminalFailure"]["reason"], "unavailable");
    for private in [
        "private-path",
        "bearer-secret",
        "private-detail",
        "secret-value",
    ] {
        assert!(!encoded.contains(private));
    }
}

#[tokio::test]
async fn scoped_startup_traces_remain_isolated_across_concurrent_tasks_and_nested_scopes() {
    let barrier = Arc::new(tokio::sync::Barrier::new(2));
    let mut tasks = Vec::new();
    for error in [StoreError::Corrupt, StoreError::Unavailable] {
        let barrier = Arc::clone(&barrier);
        tasks.push(tokio::spawn(async move {
            capture(async {
                record(Stage::ProtectedStoreStartup, error);
                barrier.wait().await;
                let ((), nested) = capture(async {
                    record(Stage::EffectDispatcher, DispatcherError::CheckpointRequired);
                })
                .await;
                assert_eq!(nested.retained, 1);
                record(Stage::StateManagement, error);
            })
            .await
            .1
        }));
    }
    for (task, expected) in tasks
        .into_iter()
        .zip([Failure::Storage("corrupt"), Failure::Storage("unavailable")])
    {
        let trace = task.await.unwrap();
        assert_eq!(trace.retained, 2);
        assert!(!trace.truncated);
        for observation in trace.observations.into_iter().flatten() {
            assert_eq!(observation.failure, expected);
        }
    }
}

#[tokio::test]
async fn trace_capacity_preserves_first_failures_and_marks_overflow_without_success_events() {
    record(Stage::NodeStart, StoreError::Corrupt);
    let (result, empty) =
        capture(async { platform(Stage::StateOperations, Ok::<_, PlatformError>(7)) }).await;
    assert_eq!(result, Ok(7));
    assert_eq!(empty.retained, 0);
    assert!(!empty.truncated);
    let ((), bounded) = capture(async {
        record(Stage::EffectDispatcher, DispatcherError::CheckpointRequired);
        for _ in 0..MAXIMUM_FAILURES + 2 {
            record(Stage::NodeStart, StoreError::Unavailable);
        }
    })
    .await;
    assert_eq!(bounded.retained, MAXIMUM_FAILURES);
    assert!(bounded.truncated);
    assert_eq!(
        bounded.observations[0].unwrap().failure,
        Failure::Dispatcher("checkpointRequired")
    );
    assert!(bounded.observations.into_iter().all(|item| item.is_some()));
}
