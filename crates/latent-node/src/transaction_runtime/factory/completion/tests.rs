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
            output: (b"retained body".to_vec()).into(),
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
                payload: (b"retained rejection body".to_vec()).into(),
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

#[tokio::test]
async fn query_cannot_succeed_after_a_corrupt_read_loses_the_view() {
    use crate::transaction_runtime::tests::fixture::Fixture;
    use crate::TransactionActivationAdmission;
    use latent_executor::transaction::{Mode, StateFailure};
    use latent_state::embedded::{AtomicBatch, RowMutation};
    use latent_state::session::{state_payload_cell_key, StateMode, StateScope};
    use latent_state::store_io::StoreIoKind;

    let fixture = Fixture::new().await;
    let scope = StateScope {
        tenant: latent_core::TenantId("a".into()),
        namespace: latent_core::StateNamespaceId("orders".into()),
        incarnation: 1,
        state_schema: format!("sha256:{}", "1".repeat(64)),
        entity: None,
        mode: StateMode::Query,
    };
    let row = state_payload_cell_key(&scope, b"bad").unwrap();
    fixture
        .protected_store()
        .with_store(StoreIoKind::RecoveryWrite, 8192, move |store| {
            store.apply(AtomicBatch {
                expectations: vec![],
                mutations: vec![RowMutation {
                    key: row,
                    value: Some(b"corrupt".to_vec()),
                }],
            })
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    let (admission, envelope, budget) = fixture.invocation(true, "failed-query-view");
    let guest = admission.admit(&envelope, &budget).await.unwrap();
    guest.acquire(Mode::Query).unwrap();
    let host = {
        let state = admission.state.lock().unwrap();
        match &*state {
            super::super::State::Ready(Some(TransactionAdmissionResult::Query { host })) => {
                Arc::clone(host)
            }
            _ => panic!("query host absent"),
        }
    };
    assert_eq!(
        guest.read(b"bad".to_vec()).await,
        Err(StateFailure::Unavailable)
    );
    guest.finish_guest_access();
    let _ = budget.finalize_at(None, std::time::Instant::now());
    let observation = admission
        .complete(
            observed()[0].clone(),
            fixture.commit_control(&envelope, &budget),
        )
        .await;
    assert!(matches!(observation, ActivationOutcome::Failed { .. }));
    drop((
        admission.take_owned_completion().unwrap(),
        guest,
        host,
        admission,
    ));
    let native = fixture.native.clone();
    fixture.shutdown_uncertain_writer().await;
    assert!(native.snapshot().unwrap().physically_retired());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn dropped_query_waiter_keeps_operation_until_the_actual_view_is_destroyed() {
    use crate::transaction_runtime::tests::fixture::Fixture;
    use crate::TransactionActivationAdmission;
    use latent_executor::transaction::Mode;
    use std::sync::mpsc;

    let fixture = Fixture::new().await;
    let (admission, envelope, budget) = fixture.invocation(true, "detached-query-view");
    let guest = admission.admit(&envelope, &budget).await.unwrap();
    guest.acquire(Mode::Query).unwrap();
    let host = {
        let state = admission.state.lock().unwrap();
        match &*state {
            super::super::State::Ready(Some(TransactionAdmissionResult::Query { host })) => {
                Arc::clone(host)
            }
            _ => panic!("query host absent"),
        }
    };
    let (entered, entered_rx) = mpsc::channel();
    let (release, release_rx) = mpsc::channel();
    let worker_host = Arc::clone(&host);
    let waiter = tokio::spawn(async move {
        worker_host
            .access("get-query", 0, 0, move |_, _| {
                entered.send(()).unwrap();
                release_rx.recv().unwrap();
                Ok(())
            })
            .await
    });
    tokio::task::spawn_blocking(move || {
        entered_rx
            .recv_timeout(std::time::Duration::from_secs(5))
            .unwrap()
    })
    .await
    .unwrap();
    waiter.abort();
    assert!(waiter.await.unwrap_err().is_cancelled());
    guest.finish_guest_access();
    let _ = budget.finalize_at(None, std::time::Instant::now());
    let outcome = admission
        .complete(
            observed()[0].clone(),
            fixture.commit_control(&envelope, &budget),
        )
        .await;
    assert!(matches!(outcome, ActivationOutcome::Failed { .. }));
    drop((
        admission.take_owned_completion().unwrap(),
        guest,
        host,
        admission,
    ));
    let held = fixture.protected_store().snapshot().unwrap();
    assert!(
        held.physical_owners >= 2,
        "view and original operation remain owned: {held:?}"
    );
    assert!(!fixture.native.snapshot().unwrap().physically_retired());
    release.send(()).unwrap();
    fixture.shutdown().await;
}
