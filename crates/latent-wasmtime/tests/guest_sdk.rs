//! Compiled Rust/C guests admitted through real publisher and builder verification.
#![cfg(target_os = "linux")]
use latent_executor::ExecutionBackend;
#[path = "guest_sdk/package.rs"]
mod package;

fn languages() -> Vec<&'static str> {
    match std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref() {
        Ok("go") => vec!["go"],
        Ok("typescript") => vec!["typescript"],
        Err(std::env::VarError::NotPresent) => vec!["rust", "c"],
        _ => panic!("unknown guest SDK language selection"),
    }
}

#[tokio::test]
#[ignore = "Requires compiled guests from tools/build_guest_capsules.py"]
async fn all_rust_examples_are_exact_signed_phase2_packages() {
    for language in languages() {
        for name in [
            "http",
            "streaming",
            "blob",
            "secrets",
            "events",
            "random",
            "metrics",
            "service",
            "callee",
        ] {
            let root = tempfile::tempdir().unwrap();
            let _publication = package::publish(root.path(), &format!("{language}-{name}")).await;
        }
    }
}

#[path = "guest_sdk/blob.rs"]
mod blob;
#[path = "guest_sdk/metrics.rs"]
mod metrics;
#[path = "guest_sdk/random.rs"]
mod random;
#[path = "generic_backend/support.rs"]
#[allow(dead_code)]
mod support;

fn input(request: &mut latent_executor::ExecutionRequest, which: u32, text: &str, handle: u64) {
    support::guest_runtime::imports(request);
    request.activation.input =
        serde_json::to_vec(&serde_json::json!([which, text, handle.to_string()])).unwrap();
}
async fn run(
    backend: &latent_wasmtime::WasmtimeBackend,
    request: latent_executor::ExecutionRequest,
    control: &impl latent_executor::ExecutionCancellation,
) -> u64 {
    let report = backend.invoke_contained(request, control).await;
    assert_eq!(report.cleanup, latent_executor::ExecutionCleanup::Reusable);
    let outcome = report.outcome.unwrap();
    let latent_executor::GuestOutcome::Returned {
        output,
        consumption,
        ..
    } = outcome
    else {
        panic!("guest must return: {outcome:?}");
    };
    if let Some(budget) = control.budget_accounting() {
        assert!(budget
            .finalize_at(Some(&consumption), std::time::Instant::now())
            .violation()
            .is_none());
    }
    let values: serde_json::Value = serde_json::from_slice(&output).unwrap();
    values[0].as_str().expect("u64 wire value").parse().unwrap()
}

#[path = "guest_sdk/http.rs"]
mod http;
#[path = "guest_sdk/secrets.rs"]
mod secrets;
#[path = "guest_sdk/streaming.rs"]
mod streaming;

fn assert_cancelled(report: latent_executor::ExecutionReport) {
    assert_eq!(report.cleanup, latent_executor::ExecutionCleanup::Reusable);
    match report.outcome {
        Ok(latent_executor::GuestOutcome::Interrupted { kind, .. }) => {
            assert_eq!(kind, latent_executor::GuestInterruptionKind::Cancelled)
        }
        Err(error) => assert_eq!(error.code, latent_core::PlatformErrorCode::Cancelled),
        other => panic!("cancellation must remain explicit: {other:?}"),
    }
}

#[path = "guest_sdk/events.rs"]
mod events;

#[path = "guest_sdk/service.rs"]
mod service;
