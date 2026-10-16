use super::*;
use crate::standalone::startup_observation::observe_startup;

#[tokio::test]
async fn actual_protected_initializer_refusal_keeps_typed_trace_error_and_physical_cleanup() {
    let (_root, settings, mut bootstrap) = fixture();
    let native = bootstrap.native.clone();
    let deadline = bootstrap.deadline;
    std::fs::set_permissions(&settings.store.root, std::fs::Permissions::from_mode(0o777)).unwrap();
    let (result, trace) = observe_startup(bootstrap.open_store(&settings)).await;
    let failure = result.err();
    let deadline_unchanged = bootstrap.deadline == deadline;
    drop(bootstrap);
    let retired = native
        .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
        .unwrap()
        .await;

    assert!(retired.snapshot.physically_retired());
    assert!(!retired.clean && retired.snapshot.quarantined);
    assert!(deadline_unchanged);
    assert_eq!(failure, Some(super::super::super::unavailable()));
    let trace = serde_json::to_value(trace.unwrap()).unwrap();
    assert_eq!(trace["startupSucceeded"], false);
    assert_eq!(trace["terminalFailure"]["owner"], "platform");
    assert_eq!(trace["terminalFailure"]["reason"], "unavailable");
    assert_eq!(trace["truncated"], false);
    assert_eq!(trace["shutdown"], serde_json::Value::Null);
    let observations = trace["observations"].as_array().unwrap();
    assert_eq!(observations.len(), 1);
    assert_eq!(
        observations[0]["stage"],
        "protectedStoreInitializerCompletion"
    );
    assert_eq!(observations[0]["failure"]["owner"], "protected");
    assert_eq!(observations[0]["failure"]["reason"], "unsafeRoot");
}

#[tokio::test]
async fn actual_successful_protected_initializer_emits_no_failure_trace_and_retires() {
    let (_root, settings, mut bootstrap) = fixture();
    let native = bootstrap.native.clone();
    let deadline = bootstrap.deadline;
    let (result, trace) = observe_startup(bootstrap.open_store(&settings)).await;
    let store = result.unwrap();
    store.close();
    let retired = store
        .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
        .unwrap()
        .await;
    let joined = store.reap_retired_threads().unwrap();
    drop(store);
    let deadline_unchanged = bootstrap.deadline == deadline;
    drop(bootstrap);

    assert!(retired.clean && retired.snapshot.physically_retired());
    assert!(joined > 0);
    assert!(native.snapshot().unwrap().physically_retired());
    assert!(deadline_unchanged);
    assert!(trace.is_none());
}
