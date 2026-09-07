use std::sync::atomic::Ordering;

use latent_activation::{ActivationOutcome, RetainedActivationOutcome};
use latent_core::{
    ActivationClock, ActivationId, ActivationPhase, ActivationTerminalState, PlatformErrorCode,
    ServiceId,
};
use latent_scheduler::CellClass;

use super::backend::{DECLARED, FUEL, QUARANTINE, SUCCESS, TRAP, UNAVAILABLE};
use super::model::request;
use super::support::{finish, tenant, Harness};

#[tokio::test]
async fn success_has_ordered_stateless_events_and_retains_diagnostics_without_output() {
    let harness = Harness::standard();
    let input = request("success");
    let expected = input.input.clone();
    let receipt = finish(harness.manager.start(input).expect("start")).await;
    let ActivationOutcome::Succeeded(success) = receipt.outcome else {
        panic!("success outcome")
    };
    assert_eq!(success.output, expected);
    assert_eq!(success.output_media_type, "application/octet-stream");
    assert_eq!(success.committed_state_version, None);
    assert!(success.effect_ids.is_empty());
    assert_eq!(success.consumption.cpu_fuel, 3);
    assert_eq!(success.consumption.log_bytes, 4);
    assert_eq!(success.consumption.peak_memory_bytes, 8);
    let status = harness.status("success");
    assert_eq!(status.phase, ActivationPhase::Running);
    assert_eq!(
        status.terminal_state,
        Some(ActivationTerminalState::Completed)
    );
    assert_eq!(status.final_consumption, Some(success.consumption.clone()));
    assert!(status.terminal_at_unix_millis.is_some());
    assert_eq!(
        status.terminal_outcome,
        Some(RetainedActivationOutcome::Succeeded((&success).into()))
    );
    let events = harness
        .manager
        .events(&tenant(), &ActivationId("success".to_owned()))
        .expect("events");
    assert_eq!(events.len(), 7);
    assert_eq!(
        events.iter().map(|event| event.phase).collect::<Vec<_>>(),
        vec![
            ActivationPhase::Received,
            ActivationPhase::Resolved,
            ActivationPhase::Admitted,
            ActivationPhase::Queued,
            ActivationPhase::Materializing,
            ActivationPhase::Running,
            ActivationPhase::Running,
        ]
    );
    for (index, event) in events.iter().enumerate() {
        assert_eq!(
            event.sequence,
            u64::try_from(index + 1).expect("small event sequence")
        );
        assert_eq!(event.activation_id, receipt.activation_id);
    }
    assert!(events[..6]
        .iter()
        .all(|event| event.terminal_state.is_none()));
    assert_eq!(
        events[6].terminal_state,
        Some(ActivationTerminalState::Completed)
    );
    harness.assert_idle();
}

#[tokio::test]
async fn declared_and_platform_outcomes_have_distinct_retention_and_finalize_spent_resources() {
    for (mode, terminal, code) in [
        (DECLARED, ActivationTerminalState::Completed, None),
        (
            TRAP,
            ActivationTerminalState::GuestTrap,
            Some(PlatformErrorCode::GuestTrap),
        ),
        (
            FUEL,
            ActivationTerminalState::ResourceExhausted,
            Some(PlatformErrorCode::ResourceExhausted),
        ),
        (
            UNAVAILABLE,
            ActivationTerminalState::DependencyFailed,
            Some(PlatformErrorCode::Unavailable),
        ),
        (
            QUARANTINE,
            ActivationTerminalState::PlatformFailed,
            Some(PlatformErrorCode::Internal),
        ),
    ] {
        let harness = Harness::new(2, 8);
        harness.backend.mode.store(mode, Ordering::Release);
        let receipt = finish(harness.manager.start(request("outcome")).expect("start")).await;
        let status = harness.status("outcome");
        assert_eq!(status.terminal_state, Some(terminal));
        let consumption = status
            .final_consumption
            .as_ref()
            .expect("terminal consumption");
        assert_eq!(consumption.cpu_fuel, 3);
        assert_eq!(consumption.log_bytes, 4);
        assert_eq!(consumption.peak_memory_bytes, 8);
        match (receipt.outcome, status.terminal_outcome, code) {
            (
                ActivationOutcome::DeclaredError { error, .. },
                Some(RetainedActivationOutcome::DeclaredError(retained)),
                None,
            ) => {
                assert_eq!(error.code, "guest.invalid-input");
                assert_eq!(retained, error);
            }
            (
                ActivationOutcome::Failed { error, .. },
                Some(RetainedActivationOutcome::PlatformFailure(retained)),
                Some(code),
            ) => {
                assert_eq!(error.code, code);
                assert_eq!(retained, error);
            }
            other => panic!("typed terminal mapping: {other:?}"),
        }
        harness.assert_idle();
        assert_eq!(
            harness.scheduler.observations(CellClass::Tiny).quarantined,
            u32::from(mode == QUARANTINE)
        );
        harness.backend.mode.store(SUCCESS, Ordering::Release);
        assert!(matches!(
            finish(
                harness
                    .manager
                    .start(request("healthy-after"))
                    .expect("healthy start")
            )
            .await
            .outcome,
            ActivationOutcome::Succeeded(_)
        ));
        harness.assert_idle();
    }
}

#[tokio::test]
async fn preexecution_route_admission_deadline_and_artifact_failures_are_terminal_without_backend_calls(
) {
    for mode in 0..4 {
        let harness = Harness::standard();
        let mut input = request("early-failure");
        let expected = match mode {
            0 => {
                input.target.service = ServiceId("absent".to_owned());
                ActivationTerminalState::DependencyFailed
            }
            1 => {
                input.principal.subject = "mallory".to_owned();
                ActivationTerminalState::Rejected
            }
            2 => {
                input.deadline_unix_millis = Some(harness.clock.sample().unix_millis() - 1);
                ActivationTerminalState::DeadlineExceeded
            }
            _ => {
                harness.artifacts.fail.store(1, Ordering::Release);
                ActivationTerminalState::DependencyFailed
            }
        };
        let receipt = finish(harness.manager.start(input).expect("valid initial shape")).await;
        assert!(
            matches!(receipt.outcome, ActivationOutcome::Failed { terminal_state, .. } if terminal_state == expected)
        );
        let status = harness.status("early-failure");
        assert_eq!(status.terminal_state, Some(expected));
        assert_eq!(status.final_consumption.expect("accounting").cpu_fuel, 0);
        assert_eq!(harness.backend.entered.load(Ordering::Relaxed), 0);
        assert_eq!(
            harness.scheduler.observations(CellClass::Tiny).quarantined,
            0
        );
        harness.assert_idle();
    }
}

#[tokio::test]
async fn containment_control_looking_payloads_remain_opaque_product_input() {
    let harness = Harness::standard();
    for (index, payload) in [
        "__latent_test_trap",
        "__latent_test_infinite",
        "__latent_test_memory",
        "__latent_test_delayed_echo:ordinary",
    ]
    .into_iter()
    .enumerate()
    {
        let mut input = request(&format!("payload-{index}"));
        input.input = payload.as_bytes().to_vec();
        let receipt = finish(harness.manager.start(input).expect("start")).await;
        let ActivationOutcome::Succeeded(success) = receipt.outcome else {
            panic!("opaque payload succeeds")
        };
        assert_eq!(success.output, payload.as_bytes());
        let requests = harness.backend.requests.lock().expect("requests");
        assert_eq!(
            requests
                .last()
                .expect("backend call")
                .activation
                .target
                .function
                .0,
            "echo"
        );
        assert_eq!(
            requests.last().expect("backend call").activation.input,
            payload.as_bytes()
        );
    }
    harness.assert_idle();
}
