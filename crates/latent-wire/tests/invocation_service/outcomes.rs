use std::sync::atomic::Ordering;

use latent_wire::invocation::{proto, InvocationService};

use super::backend::{DECLARED, FAILURE, RETURNED, SECRET};
use super::support::{authenticated, finish, pending, request, status, Harness};

#[tokio::test]
async fn immediate_and_retained_outcomes_preserve_categories_and_final_accounting() {
    let harness = Harness::standard();
    let adapter = harness.adapter();
    for (id, mode) in [
        ("success", RETURNED),
        ("declared", DECLARED),
        ("failure", FAILURE),
    ] {
        harness.backend.mode.store(mode, Ordering::Release);
        let response = finish(adapter.invoke(authenticated(request(id))))
            .await
            .expect("terminal receipt")
            .into_inner();
        assert_eq!(response.activation_id, id);
        assert!(!response.revision_id.is_empty());
        assert!(!response.release_digest.is_empty());
        assert_eq!(response.route_generation, 1);
        let consumption = response.consumption.expect("terminal consumption");
        assert_eq!(consumption.cpu_fuel, 3);
        assert_eq!(consumption.peak_memory_bytes, 8);
        assert_eq!(consumption.log_bytes, 4);
        let retained = status(&adapter, id).await;
        assert_eq!(retained.final_consumption, Some(consumption));
        assert!(retained.terminal_at_unix_millis.is_some());
        match (mode, response.result, retained.terminal_outcome) {
            (
                RETURNED,
                Some(proto::invoke_response::Result::Success(success)),
                Some(proto::activation_status::TerminalOutcome::Succeeded(_)),
            ) => {
                assert_eq!(success.payload, b"opaque payload");
                assert_eq!(retained.terminal_state.as_deref(), Some("completed"));
            }
            (
                DECLARED,
                Some(proto::invoke_response::Result::DeclaredError(error)),
                Some(proto::activation_status::TerminalOutcome::DeclaredError(retained)),
            ) => {
                assert_eq!(error.code, "guest.invalid-input");
                assert_eq!(error.payload, b"domain payload");
                assert_eq!(error, retained);
            }
            (
                FAILURE,
                Some(proto::invoke_response::Result::PlatformFailure(error)),
                Some(proto::activation_status::TerminalOutcome::PlatformFailure(retained)),
            ) => {
                assert_eq!(error.code, "unavailable");
                assert!(error.retryable);
                assert_eq!(error, retained);
                assert!(!error.message.contains(SECRET));
                assert!(error.detail_items.is_empty());
                let Some(latent_activation::RetainedActivationOutcome::PlatformFailure(internal)) =
                    harness.status(id).terminal_outcome
                else {
                    panic!("trusted diagnostic retained internally");
                };
                assert_eq!(internal.message, SECRET);
            }
            _ => panic!("RPC category must match manager terminal category"),
        }
    }
    harness.assert_idle();
}

#[tokio::test]
async fn accepted_failure_before_resolution_has_no_fabricated_pin() {
    let harness = Harness::standard();
    let adapter = harness.adapter();
    let mut input = request("unresolved");
    input.target.as_mut().expect("target").service = "missing-service".to_owned();
    let response = finish(adapter.invoke(authenticated(input)))
        .await
        .expect("accepted terminal failure")
        .into_inner();
    assert_eq!(response.activation_id, "unresolved");
    assert_eq!(response.revision_id, "");
    assert_eq!(response.release_digest, "");
    assert_eq!(response.route_generation, 0);
    let Some(proto::invoke_response::Result::PlatformFailure(error)) = response.result else {
        panic!("resolution failure");
    };
    assert_eq!(error.code, "route-unavailable");
    assert_eq!(
        response
            .consumption
            .expect("zero final accounting")
            .cpu_fuel,
        0
    );
    assert!(status(&adapter, "unresolved")
        .await
        .terminal_state
        .is_some());
    assert_eq!(harness.artifacts.entered.load(Ordering::Relaxed), 0);
    assert_eq!(harness.backend.entered.load(Ordering::Relaxed), 0);
    harness.assert_idle();
}

#[tokio::test]
async fn artifact_failure_keeps_pin_and_next_call_reuses_unexecuted_cell() {
    let harness = Harness::standard();
    let adapter = harness.adapter();
    harness.artifacts.fail.store(1, Ordering::Release);
    let response = finish(adapter.invoke(authenticated(request("materialization-failure"))))
        .await
        .expect("accepted failure")
        .into_inner();
    assert_eq!(response.route_generation, 1);
    assert!(!response.revision_id.is_empty());
    let Some(proto::invoke_response::Result::PlatformFailure(error)) = response.result else {
        panic!("artifact failure");
    };
    assert_eq!(error.code, "unavailable");
    assert_eq!(
        response.consumption.expect("finalized accounting").cpu_fuel,
        0
    );
    harness.artifacts.fail.store(0, Ordering::Release);
    finish(adapter.invoke(authenticated(request("after-failure"))))
        .await
        .expect("cell reusable");
    assert_eq!(harness.backend.entered.load(Ordering::Relaxed), 1);
    harness.assert_idle();
}

#[tokio::test]
async fn rpc_receipt_and_execution_keep_one_pinned_catalog_generation() {
    let harness = Harness::standard();
    let adapter = harness.adapter();
    harness.artifacts.gate.close();
    let mut first = Box::pin(adapter.invoke(authenticated(request("route-a"))));
    pending(first.as_mut()).await;
    harness.catalog.generation.store(2, Ordering::Release);
    harness.artifacts.gate.open();
    let first = finish(first).await.expect("pinned result").into_inner();
    assert_eq!(first.route_generation, 1);
    let second = finish(adapter.invoke(authenticated(request("route-b"))))
        .await
        .expect("new generation")
        .into_inner();
    assert_eq!(second.route_generation, 2);
    let requests = harness.backend.requests.lock().expect("requests");
    let pin = requests[0]
        .activation
        .resolved_revision
        .as_ref()
        .expect("execution pin");
    assert_eq!(first.revision_id, pin.revision.0);
    assert_eq!(first.release_digest, pin.release.0);
    assert_eq!(requests[0].prepared.key.release, pin.release);
    drop(requests);
    harness.assert_idle();
}
