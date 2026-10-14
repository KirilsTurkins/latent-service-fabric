use super::*;
use latent_core::{ActivationTerminalState, ErrorDetail};
use std::cell::Cell;

mod pre_host_conflict;

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

fn observed() -> [ActivationOutcome; 3] {
    [
        ActivationOutcome::Succeeded(ActivationSuccess {
            output: b"retained body".to_vec(),
            output_media_type: "application/octet-stream".into(),
            metadata: Metadata::new(),
            consumption: charged(),
            committed_state_version: None,
            effect_ids: Vec::new(),
        }),
        ActivationOutcome::DeclaredError {
            error: DeclaredError {
                code: "original-rejection".into(),
                message: String::new(),
                payload: b"retained rejection body".to_vec(),
                media_type: "application/octet-stream".into(),
                metadata: Metadata::new(),
            },
            consumption: charged(),
        },
        unavailable(charged()),
    ]
}

#[test]
fn refused_completion_binding_preserves_exact_denial_consumption_and_no_publication() {
    for observation in observed() {
        let denial = PlatformError {
            code: PlatformErrorCode::PermissionDenied,
            message: "original retained-data refusal".into(),
            retryable: false,
            details: vec![ErrorDetail {
                kind: "transaction.retention".into(),
                fields: Metadata::from([("reason".into(), "expired".into())]),
            }],
        };
        let published = Cell::new(false);
        let outcome = with_completion_binding(Err(denial.clone()), observation, |observation| {
            published.set(true);
            observation
        });
        assert!(
            !published.get(),
            "denied data cannot publish an owned completion"
        );
        assert_eq!(
            outcome,
            ActivationOutcome::Failed {
                terminal_state: ActivationTerminalState::Rejected,
                error: denial,
                consumption: charged(),
            }
        );
    }
}

#[test]
fn successful_completion_binding_publishes_the_original_observation_once() {
    for observation in observed() {
        let original = observation.clone();
        let publications = Cell::new(0);
        let outcome = with_completion_binding(Ok(()), observation, |observation| {
            publications.set(publications.get() + 1);
            observation
        });
        assert_eq!(publications.get(), 1);
        assert_eq!(outcome, original);
    }
}

#[test]
fn retained_abort_code_cannot_replace_a_different_original_failure() {
    let original = ActivationOutcome::Failed {
        terminal_state: ActivationTerminalState::GuestTrap,
        error: super::super::error(PlatformErrorCode::GuestTrap, "original guest trap"),
        consumption: charged(),
    };
    for code in [None, Some("state-conflict"), Some("cancelled")] {
        assert_eq!(
            aborted_observation(code, charged(), Some(original.clone())),
            unavailable(charged())
        );
    }
    assert_eq!(
        aborted_observation(Some("guest-trap"), charged(), Some(original.clone())),
        original
    );
    assert_eq!(
        aborted_observation(Some("state-conflict"), charged(), None),
        failure_for_platform_error(
            super::super::error(
                PlatformErrorCode::StateConflict,
                "transaction-state-conflict"
            ),
            charged()
        )
    );
}

#[test]
fn retired_conflict_cannot_replace_an_original_execution_fault() {
    let original = ActivationOutcome::Failed {
        terminal_state: ActivationTerminalState::GuestTrap,
        error: super::super::error(PlatformErrorCode::GuestTrap, "original guest trap"),
        consumption: charged(),
    };
    assert_eq!(
        conflict_observation(charged(), Some(&original)),
        unavailable(charged())
    );
    assert_eq!(
        conflict_observation(charged(), None),
        failure_for_platform_error(
            super::super::error(
                PlatformErrorCode::StateConflict,
                "transaction-state-conflict"
            ),
            charged()
        )
    );
}
