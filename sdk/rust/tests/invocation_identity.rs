//! Executable contract examples with a fixture server; no transport is implemented.

#[path = "invocation_identity/support.rs"]
mod support;

use latent_core::{ActivationId, ActivationPhase, ActivationTerminalState, PlatformErrorCode};
use latent_sdk::{CancelResponse, InvocationOutcome, LatentClient, RetainedInvocationOutcome};
use support::{poll, ready, request, Fixture, SERVER_ID};

#[test]
fn known_id_allows_status_and_all_cancel_dispositions_before_invocation_completes() {
    let fixture = Fixture::default();
    let client: &dyn LatentClient = &fixture;
    let request = request();
    let id = request.activation_id.clone().unwrap();
    let mut invocation = client.invoke(request);
    assert!(poll(&mut invocation).is_pending());
    let status = ready(client.get_activation(&id)).unwrap();
    assert_eq!(status.activation_id, id);
    assert_eq!(status.phase, ActivationPhase::Running);
    assert_eq!(status.terminal_state, None);
    assert_eq!(fixture.state().root.as_ref(), Some(&id));

    for _ in 0..2 {
        assert_eq!(
            ready(client.cancel(&id, "stop")).unwrap(),
            CancelResponse::Accepted
        );
    }
    assert!(poll(&mut invocation).is_pending());
    assert_eq!(
        ready(client.get_activation(&id)).unwrap().terminal_state,
        None
    );
    assert_eq!(
        ready(client.cancel(&ActivationId("unknown".to_owned()), "stop")).unwrap(),
        CancelResponse::NotFound
    );

    fixture.finish(ActivationTerminalState::Cancelled, false);
    let InvocationOutcome::PlatformFailure(failure) = ready(invocation).unwrap() else {
        panic!("acknowledged cancellation must be a platform outcome");
    };
    assert_eq!(failure.receipt.activation_id, id);
    assert_eq!(failure.error.code, PlatformErrorCode::Cancelled);
    assert_eq!(
        ready(client.cancel(&id, "again")).unwrap(),
        CancelResponse::AlreadyTerminal(ActivationTerminalState::Cancelled)
    );
}

#[test]
fn cancel_transport_failure_is_not_a_disposition_or_terminal_outcome() {
    let fixture = Fixture::default();
    let request = request();
    let id = request.activation_id.clone().unwrap();
    let mut invocation = fixture.invoke(request);
    assert!(poll(&mut invocation).is_pending());
    fixture.state().fail_cancel = true;
    let error = ready(fixture.cancel(&id, "stop")).unwrap_err();
    assert_eq!(error.message, "cancel transport unavailable");
    assert!(!fixture.state().cancellation_requested);
    assert_eq!(
        ready(fixture.get_activation(&id)).unwrap().terminal_state,
        None
    );
    assert!(poll(&mut invocation).is_pending());
    fixture.finish(ActivationTerminalState::Completed, false);
    assert!(matches!(
        ready(invocation),
        Ok(InvocationOutcome::Succeeded(_))
    ));
}

#[test]
fn lost_response_recovers_status_by_original_id_without_reinvoking() {
    let fixture = Fixture::default();
    let request = request();
    let id = request.activation_id.clone().unwrap();
    let mut invocation = fixture.invoke(request);
    assert!(poll(&mut invocation).is_pending());
    fixture.finish(ActivationTerminalState::Completed, true);
    assert_eq!(
        ready(invocation).unwrap_err().message,
        "invocation response lost"
    );
    let status = ready(fixture.get_activation(&id)).unwrap();
    assert_eq!(status.activation_id, id);
    assert_eq!(
        status.terminal_state,
        Some(ActivationTerminalState::Completed)
    );
    assert!(matches!(
        status.terminal_outcome,
        Some(RetainedInvocationOutcome::Succeeded { .. })
    ));
    assert_eq!(status.final_consumption.unwrap().cpu_fuel, 7);
    assert_eq!(status.terminal_at_unix_millis, Some(2));
    assert_eq!(fixture.state().invoke_count, 1);
}

#[test]
fn absent_identity_is_preserved_until_the_fixture_server_assigns_it() {
    let fixture = Fixture::default();
    let mut request = request();
    request.activation_id = None;
    let mut invocation = fixture.invoke(request.clone());
    assert!(poll(&mut invocation).is_pending());
    assert_eq!(fixture.state().observed, Some(request));
    let assigned = ActivationId(SERVER_ID.to_owned());
    assert_eq!(fixture.state().root.as_ref(), Some(&assigned));
    fixture.finish(ActivationTerminalState::Completed, false);
    let InvocationOutcome::Succeeded(response) = ready(invocation).unwrap() else {
        panic!("expected success");
    };
    assert_eq!(response.activation_id, assigned);
}

#[test]
fn explicit_lineage_is_carried_without_replacing_the_caller_identity() {
    let fixture = Fixture::default();
    let mut request = request();
    request.root_activation_id = Some(ActivationId("caller-root".to_owned()));
    request.parent_activation_id = Some(ActivationId("caller-parent".to_owned()));
    let mut invocation = fixture.invoke(request.clone());
    assert!(poll(&mut invocation).is_pending());
    assert_eq!(fixture.state().observed.as_ref(), Some(&request));
    assert_eq!(fixture.state().root, request.root_activation_id);
    fixture.finish(ActivationTerminalState::Completed, false);
    let InvocationOutcome::Succeeded(response) = ready(invocation).unwrap() else {
        panic!("expected success");
    };
    assert_eq!(Some(response.activation_id), request.activation_id);
}

#[test]
fn present_empty_ids_and_parent_without_root_reach_server_validation_unchanged() {
    for invalid_field in 0..4 {
        let fixture = Fixture::default();
        let mut request = request();
        match invalid_field {
            0 => request.activation_id = Some(ActivationId(String::new())),
            1 => request.root_activation_id = Some(ActivationId(String::new())),
            2 => {
                request.root_activation_id = Some(ActivationId("root".to_owned()));
                request.parent_activation_id = Some(ActivationId(String::new()));
            }
            _ => request.parent_activation_id = Some(ActivationId("parent".to_owned())),
        }
        let error = ready(fixture.invoke(request.clone())).unwrap_err();
        assert_eq!(error.message, "invalid invocation identity");
        assert_eq!(fixture.state().observed, Some(request));
        assert!(fixture.state().status.is_none());
    }
}

#[test]
fn dropping_the_local_future_does_not_prove_the_server_activation_stopped() {
    let fixture = Fixture::default();
    let request = request();
    let id = request.activation_id.clone().unwrap();
    let mut invocation = fixture.invoke(request);
    assert!(poll(&mut invocation).is_pending());
    drop(invocation);
    assert_eq!(
        ready(fixture.get_activation(&id)).unwrap().terminal_state,
        None
    );
    assert_eq!(
        ready(fixture.cancel(&id, "explicit stop")).unwrap(),
        CancelResponse::Accepted
    );
    fixture.finish(ActivationTerminalState::Cancelled, false);
    assert_eq!(
        ready(fixture.get_activation(&id)).unwrap().terminal_state,
        Some(ActivationTerminalState::Cancelled)
    );
    assert_eq!(fixture.state().invoke_count, 1);
}
