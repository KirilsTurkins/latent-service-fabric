use super::*;
use crate::phase4::retained_abort_fixture as original;

fn projected(fixture: &original::StoredAbort) -> PlatformErrorCode {
    let consumed = charged();
    let outcome = result_outcome(&fixture.command, &fixture.result, consumed.clone()).unwrap();
    let ActivationOutcome::Failed {
        terminal_state,
        error: failure,
        consumption,
    } = outcome
    else {
        panic!("original retained abort cannot become an application success");
    };
    assert_eq!(terminal_state, ActivationTerminalState::PlatformFailed);
    assert_eq!(consumption, consumed);
    assert_eq!(failure.message, "transactional invocation unavailable");
    assert!(!failure.retryable && failure.details.is_empty());
    let inspected = inspection(&fixture.command, Some(&fixture.result), None);
    assert_eq!(inspected.outcome, t::CommandOutcome::Aborted as i32);
    assert!(inspected.metadata_durable && !inspected.application_state_committed);
    assert!(inspected.commit.is_none() && inspected.proven_abort.is_some());
    assert_eq!(inspected.source, Some(source(fixture.command.source())));
    failure.code
}
#[test]
fn actual_retired_abort_replay_preserves_known_codes_and_consumption() {
    for code in original::KNOWN {
        let fixture = original::aborted(code.wire_code());
        assert_eq!(projected(&fixture), code);
    }
}
#[test]
fn actual_retired_abort_replay_keeps_unknown_codes_unavailable() {
    for code in original::UNKNOWN {
        let fixture = original::aborted(code);
        assert_eq!(projected(&fixture), PlatformErrorCode::Unavailable);
    }
}
