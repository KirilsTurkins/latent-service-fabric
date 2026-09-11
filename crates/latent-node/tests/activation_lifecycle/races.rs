use std::sync::{Arc, Barrier};

use latent_core::{ActivationId, ActivationTerminalState, CancelDisposition, PlatformErrorCode};

use super::model::request;
use super::support::{finish, pending, tenant, Harness};

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn concurrent_starts_cannot_replace_the_same_identity_owner() {
    let harness = Harness::standard();
    let barrier = Arc::new(Barrier::new(2));
    let (first, second) = std::thread::scope(|scope| {
        let begin = || {
            barrier.wait();
            harness.manager.start(request("raced-id"))
        };
        let first = scope.spawn(begin);
        let second = scope.spawn(begin);
        (
            first.join().expect("first caller"),
            second.join().expect("second caller"),
        )
    });
    let ((Ok(handle), Err(error)) | (Err(error), Ok(handle))) = (first, second) else {
        panic!("exactly one concurrent owner must be accepted");
    };
    assert_eq!(error.code, PlatformErrorCode::AlreadyExists);
    let receipt = finish(handle).await;
    assert_eq!(receipt.activation_id.0, "raced-id");
    assert_eq!(harness.manager.journal().snapshot().begun, 1);
    assert_eq!(harness.manager.journal().snapshot().completed, 1);
    harness.assert_idle();
}

#[tokio::test]
async fn cancellation_completion_and_status_race_publish_exactly_one_terminal_event() {
    for index in 0..4 {
        let harness = Harness::standard();
        harness.backend.gate.close();
        let id = ActivationId(format!("race-{index}"));
        let mut handle = Box::pin(harness.manager.start(request(&id.0)).expect("start"));
        pending(handle.as_mut()).await;
        let barrier = tokio::sync::Barrier::new(2);
        let cancel = async {
            barrier.wait().await;
            let status = harness
                .manager
                .status(&tenant(), &id)
                .expect("racing status");
            assert!(status.is_some());
            harness
                .manager
                .cancel_for(&tenant(), &id, "racing cancellation")
                .expect("cancel")
        };
        let complete = async {
            barrier.wait().await;
            harness.backend.gate.open();
            finish(handle).await
        };
        let (disposition, receipt) = tokio::join!(cancel, complete);
        assert_eq!(receipt.activation_id, id);
        let status = harness.status(&id.0);
        let terminal = status.terminal_state.expect("terminal status");
        assert!(matches!(
            terminal,
            ActivationTerminalState::Completed | ActivationTerminalState::Cancelled
        ));
        match disposition {
            CancelDisposition::Accepted => assert_eq!(terminal, ActivationTerminalState::Cancelled),
            CancelDisposition::AlreadyTerminal(state) => assert_eq!(terminal, state),
            CancelDisposition::NotFound => panic!("live or retained activation cannot disappear"),
        }
        let events = harness.manager.events(&tenant(), &id).expect("events");
        assert_eq!(
            events
                .iter()
                .filter(|event| event.terminal_state.is_some())
                .count(),
            1
        );
        assert_eq!(harness.manager.journal().snapshot().completed, 1);
        harness.assert_idle();
    }
}

#[tokio::test]
async fn bounded_start_capacity_rejects_before_retaining_more_work_and_refunds_on_drop() {
    let harness = Harness::standard();
    let mut active = Vec::new();
    for index in 0..8 {
        active.push(
            harness
                .manager
                .start(request(&format!("active-{index}")))
                .expect("bounded active"),
        );
    }
    let before = harness.manager.journal().snapshot();
    assert_eq!(before.active, 8);
    let error = harness
        .manager
        .start(request("overflow"))
        .err()
        .expect("capacity");
    assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
    assert_eq!(harness.manager.journal().snapshot(), before);
    drop(active);
    assert_eq!(harness.manager.journal().snapshot().reserved_bytes, 0);
    harness.assert_idle();
}
