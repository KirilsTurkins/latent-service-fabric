use super::*;
use latent_core::{ErrorDetail, Metadata};

fn charged() -> BudgetConsumption {
    BudgetConsumption {
        cpu_fuel: 17,
        peak_memory_bytes: 4096,
        wall_time_micros: 23,
        state_read_bytes: 31,
        state_write_bytes: 37,
        effect_count: 1,
        ..Default::default()
    }
}

#[test]
fn replay_errors_preserve_the_original_code_and_details_before_result_projection() {
    for code in [
        PlatformErrorCode::PermissionDenied,
        PlatformErrorCode::StateConflict,
        PlatformErrorCode::Unavailable,
    ] {
        let original = PlatformError {
            code,
            message: "original replay refusal".into(),
            retryable: false,
            details: vec![ErrorDetail {
                kind: "transaction.replay".into(),
                fields: Metadata::from([("reason".into(), "refused".into())]),
            }],
        };
        let projected = existing_outcome(Err(original.clone()), charged(), |_, _| {
            panic!("a refused replay cannot project an application result body")
        });
        let Err(error) = projected else {
            panic!("a refused replay cannot disclose a command inspection or result")
        };
        assert_eq!(error, original);
        assert_eq!(error.code, code);
        assert!(!error.retryable);
    }
}

#[test]
fn missing_replay_result_keeps_the_original_consumption_without_disclosing_a_body() {
    let original = charged();
    let projected = existing_outcome(Ok(None), original.clone(), |_, _| {
        panic!("a missing replay cannot project an application result body")
    })
    .unwrap();
    assert!(projected.result.is_none());
    assert_eq!(
        projected.outcome,
        ActivationOutcome::Failed {
            terminal_state: ActivationTerminalState::PlatformFailed,
            error: error(PlatformErrorCode::Unavailable),
            consumption: original,
        }
    );
}
