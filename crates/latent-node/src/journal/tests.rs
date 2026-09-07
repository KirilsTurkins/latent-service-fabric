use std::sync::atomic::{AtomicUsize, Ordering};

use latent_activation::{ActivationOutcome, RetainedActivationOutcome};
use latent_core::{ActivationPhase, ActivationTerminalState, BudgetConsumption, Metadata};

use super::*;

mod support;
use support::{envelope, journal, outcome, Clock};

#[test]
fn legal_history_and_terminal_status_publish_complete_declared_outcomes() {
    let (journal, _) = journal(3, 3);
    let envelope = envelope("one");
    let mut owner = journal.begin(&envelope).expect("received");
    for phase in [
        ActivationPhase::Resolved,
        ActivationPhase::Admitted,
        ActivationPhase::Queued,
        ActivationPhase::Materializing,
        ActivationPhase::Running,
    ] {
        owner.advance(phase, Metadata::new()).expect("legal phase");
    }
    let terminal = ActivationOutcome::DeclaredError {
        error: latent_core::DeclaredError {
            code: "domain".to_owned(),
            message: "declared".to_owned(),
            payload: b"[1,2,3]".to_vec(),
            media_type: "test".to_owned(),
            metadata: Metadata::from([("meaning".to_owned(), "preserved".to_owned())]),
        },
        consumption: BudgetConsumption {
            cpu_fuel: 7,
            log_bytes: 3,
            ..BudgetConsumption::default()
        },
    };
    owner
        .validate_terminal(&terminal)
        .expect("bounded terminal");
    assert_eq!(owner.finish(terminal.clone()), terminal);
    let status = journal
        .status(&envelope.target.tenant, &envelope.activation_id)
        .expect("status")
        .expect("record");
    assert_eq!(status.phase, ActivationPhase::Running);
    assert_eq!(
        status.terminal_state,
        Some(ActivationTerminalState::Completed)
    );
    assert!(matches!(
        status.terminal_outcome,
        Some(RetainedActivationOutcome::DeclaredError(_))
    ));
    assert_eq!(
        status
            .final_consumption
            .expect("final accounting")
            .log_bytes,
        3
    );
    let events = journal
        .events(&envelope.target.tenant, &envelope.activation_id)
        .expect("events");
    assert_eq!(events.len(), 7);
    for (index, event) in events.iter().enumerate() {
        assert_eq!(event.sequence, u64::try_from(index + 1).expect("sequence"));
        assert_eq!(event.terminal_state.is_some(), index == 6);
    }
    assert_eq!(journal.snapshot().active, 0);
    assert_eq!(journal.snapshot().completed, 1);
}

#[test]
fn duplicate_and_active_capacity_reject_before_registration_callback() {
    let (journal, _) = journal(1, 2);
    let envelope = envelope("one");
    let owner = journal.begin(&envelope).expect("first");
    let registrations = AtomicUsize::new(0);
    for (input, expected) in [
        (&envelope, PlatformErrorCode::AlreadyExists),
        (
            &support::envelope("two"),
            PlatformErrorCode::ResourceExhausted,
        ),
    ] {
        let result = journal.begin_with(input, || {
            registrations.fetch_add(1, Ordering::Relaxed);
            Ok(())
        });
        assert_eq!(result.err().expect("rejection").code, expected);
    }
    assert_eq!(registrations.load(Ordering::Relaxed), 0);
    owner.finish(outcome());
    assert_eq!(
        journal
            .begin(&envelope)
            .err()
            .expect("retained duplicate")
            .code,
        PlatformErrorCode::AlreadyExists
    );
}

#[test]
fn registration_failure_leaves_no_journal_reservation_or_received_event() {
    let (journal, _) = journal(1, 2);
    let input = envelope("one");
    let result = journal.begin_with(&input, || {
        Err::<(), _>(error(PlatformErrorCode::Unavailable, "registration-failed"))
    });
    assert_eq!(
        result.err().expect("callback failure").message,
        "registration-failed"
    );
    assert_eq!(journal.snapshot(), ActivationJournalSnapshot::default());
    assert!(journal
        .events(&input.target.tenant, &input.activation_id)
        .expect("events")
        .is_empty());
    drop(journal.begin(&input).expect("capacity recovered"));
}

#[test]
fn terminal_eviction_and_monotonic_ttl_never_remove_active_records() {
    let (journal, clock) = journal(3, 1);
    let first = envelope("active");
    let active = journal.begin(&first).expect("active");
    let old = envelope("old");
    journal.begin(&old).expect("old").finish(outcome());
    let newest = envelope("new");
    journal.begin(&newest).expect("new").finish(outcome());
    assert!(journal
        .status(&old.target.tenant, &old.activation_id)
        .expect("status")
        .is_none());
    clock.wall(0);
    assert_eq!(
        journal.snapshot().terminal,
        1,
        "wall rollback does not expire a terminal"
    );
    clock.elapse(Duration::from_secs(2));
    assert_eq!(journal.snapshot().terminal, 0);
    assert!(journal
        .status(&first.target.tenant, &first.activation_id)
        .expect("active status")
        .is_some());
    assert_eq!(journal.snapshot().active, 1);
    drop(active);
    assert_eq!(journal.snapshot().evicted, 2);
}

#[test]
fn fifo_eviction_follows_completion_even_when_admission_order_differs() {
    let (journal, _) = journal(3, 2);
    let first = envelope("admitted-first");
    let second = envelope("completed-first");
    let third = envelope("completed-last");
    let first_owner = journal.begin(&first).expect("first");
    let second_owner = journal.begin(&second).expect("second");
    let third_owner = journal.begin(&third).expect("third");
    second_owner.finish(outcome());
    first_owner.finish(outcome());
    third_owner.finish(outcome());
    assert!(journal
        .status(&second.target.tenant, &second.activation_id)
        .expect("status")
        .is_none());
    assert!(journal
        .status(&first.target.tenant, &first.activation_id)
        .expect("status")
        .is_some());
    assert!(journal
        .status(&third.target.tenant, &third.activation_id)
        .expect("status")
        .is_some());
}

#[test]
fn full_record_reservation_enforces_bytes_independently_of_active_count() {
    let clock = Arc::new(Clock::new());
    let config = LocalActivationJournalConfig {
        maximum_active: 8,
        maximum_terminal: 8,
        maximum_record_bytes: 64 * 1024,
        maximum_retained_bytes: 128 * 1024,
        terminal_retention: Duration::from_secs(30),
    };
    let journal = LocalActivationJournal::new(config, clock).expect("journal");
    let first = journal.begin(&envelope("first")).expect("first");
    let second = journal.begin(&envelope("second")).expect("second");
    assert_eq!(
        journal.snapshot().reserved_bytes,
        config.maximum_retained_bytes
    );
    assert_eq!(
        journal
            .begin(&envelope("third"))
            .err()
            .expect("byte limit")
            .message,
        "activation-journal-capacity"
    );
    drop(first);
    let third = journal
        .begin(&envelope("third"))
        .expect("evicts terminal to reserve full slot");
    assert_eq!(journal.snapshot().terminal, 0);
    drop(second);
    drop(third);
    let snapshot = journal.snapshot();
    assert_eq!(snapshot.reserved_bytes, 0);
    assert!(snapshot.retained_bytes <= config.maximum_retained_bytes);
}

#[test]
fn invalid_phase_and_oversized_attributes_do_not_mutate_the_record() {
    let (journal, _) = journal(1, 2);
    let input = envelope("one");
    let mut owner = journal.begin(&input).expect("begin");
    assert_eq!(
        owner
            .advance(ActivationPhase::Running, Metadata::new())
            .expect_err("skip")
            .message,
        "invalid-activation-phase-transition"
    );
    let attributes = Metadata::from([("too-large".to_owned(), "x".repeat(64 * 1024))]);
    assert_eq!(
        owner
            .advance(ActivationPhase::Resolved, attributes)
            .expect_err("attributes")
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    let status = journal
        .status(&input.target.tenant, &input.activation_id)
        .expect("status")
        .expect("record");
    assert_eq!(status.phase, ActivationPhase::Received);
    assert!(status.metadata.is_empty());
    assert_eq!(
        journal
            .events(&input.target.tenant, &input.activation_id)
            .expect("events")
            .len(),
        1
    );
    owner.finish(outcome());
}

#[test]
fn tenant_queries_and_cancellation_never_expose_another_tenants_record() {
    let (journal, _) = journal(1, 2);
    let input = envelope("one");
    let owner = journal.begin(&input).expect("begin");
    let foreign = TenantId("foreign".to_owned());
    assert!(journal
        .status(&foreign, &input.activation_id)
        .expect("status")
        .is_none());
    assert!(journal
        .events(&foreign, &input.activation_id)
        .expect("events")
        .is_empty());
    let calls = AtomicUsize::new(0);
    assert_eq!(
        journal
            .cancel_with(
                &input.target.tenant,
                &ActivationId(" invalid".to_owned()),
                || { panic!("malformed queries cannot reach cancellation") }
            )
            .expect_err("malformed query is a platform error")
            .code,
        PlatformErrorCode::InvalidArgument
    );
    assert_eq!(
        journal
            .cancel_with(&foreign, &input.activation_id, || {
                calls.fetch_add(1, Ordering::Relaxed);
                CancelDisposition::Accepted
            })
            .expect("valid foreign scope"),
        CancelDisposition::NotFound
    );
    assert_eq!(
        journal
            .cancel_with(&input.target.tenant, &input.activation_id, || {
                calls.fetch_add(1, Ordering::Relaxed);
                CancelDisposition::Accepted
            })
            .expect("valid scope"),
        CancelDisposition::Accepted
    );
    owner.finish(outcome());
    assert_eq!(
        journal
            .cancel_with(&input.target.tenant, &input.activation_id, || {
                calls.fetch_add(1, Ordering::Relaxed);
                CancelDisposition::Accepted
            })
            .expect("valid terminal scope"),
        CancelDisposition::AlreadyTerminal(ActivationTerminalState::Completed)
    );
    assert_eq!(calls.load(Ordering::Relaxed), 1);
}

#[test]
fn dropped_and_panicking_pre_admission_owners_publish_one_terminal_fallback() {
    let (journal, _) = journal(2, 2);
    let input = envelope("unpolled");
    drop(journal.begin(&input).expect("received before polling"));
    let panic_input = envelope("panic");
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        let _owner = journal.begin(&panic_input).expect("owner");
        panic!("injected pre-admission unwind");
    }));
    assert!(result.is_err());
    for input in [input, panic_input] {
        let events = journal
            .events(&input.target.tenant, &input.activation_id)
            .expect("events");
        assert_eq!(events.len(), 2);
        assert_eq!(events[1].sequence, 2);
        assert_eq!(
            events[1].terminal_state,
            Some(ActivationTerminalState::Cancelled)
        );
    }
    assert_eq!(journal.snapshot().active, 0);
    assert_eq!(journal.snapshot().completed, 2);
}

#[test]
fn immediate_success_payload_is_not_retained_but_oversized_declared_payload_is_rejected() {
    let (journal, _) = journal(1, 2);
    let input = envelope("one");
    let owner = journal.begin(&input).expect("owner");
    let mut success = outcome();
    if let ActivationOutcome::Succeeded(success) = &mut success {
        success.output = vec![0; 128 * 1024];
    }
    owner
        .validate_terminal(&success)
        .expect("immediate-only success payload");
    let large = ActivationOutcome::DeclaredError {
        error: latent_core::DeclaredError {
            code: "domain".to_owned(),
            message: "large".to_owned(),
            payload: vec![0; 128 * 1024],
            media_type: "test".to_owned(),
            metadata: Metadata::new(),
        },
        consumption: BudgetConsumption {
            cpu_fuel: 9,
            ..BudgetConsumption::default()
        },
    };
    assert_eq!(
        owner
            .validate_terminal(&large)
            .expect_err("retained bound")
            .message,
        "activation-terminal-record-too-large"
    );
    let effective = owner.finish(large);
    assert!(matches!(
        effective,
        ActivationOutcome::Failed {
            terminal_state: ActivationTerminalState::ResourceExhausted,
            ..
        }
    ));
    let status = journal
        .status(&input.target.tenant, &input.activation_id)
        .expect("status")
        .expect("record");
    assert_eq!(
        status
            .final_consumption
            .expect("preserved consumption")
            .cpu_fuel,
        9
    );
}

#[tokio::test]
async fn unowned_append_is_rejected_without_changing_a_live_history() {
    let (journal, _) = journal(1, 2);
    let input = envelope("one");
    let owner = journal.begin(&input).expect("owner");
    let event = journal
        .events(&input.target.tenant, &input.activation_id)
        .expect("events")[0]
        .clone();
    assert_eq!(
        journal
            .append(event)
            .await
            .expect_err("owner required")
            .code,
        PlatformErrorCode::PermissionDenied
    );
    assert_eq!(
        journal
            .read(&input.activation_id)
            .await
            .expect("trusted read")
            .len(),
        1
    );
    drop(owner);
}

#[test]
fn concurrent_duplicate_start_registers_exactly_one_owner() {
    let (journal, _) = journal(2, 2);
    let registrations = Arc::new(AtomicUsize::new(0));
    let barrier = Arc::new(std::sync::Barrier::new(3));
    let threads = (0..2)
        .map(|_| {
            let journal = journal.clone();
            let barrier = barrier.clone();
            let registrations = registrations.clone();
            std::thread::spawn(move || {
                barrier.wait();
                journal.begin_with(&envelope("same"), || {
                    registrations.fetch_add(1, Ordering::Relaxed);
                    Ok(())
                })
            })
        })
        .collect::<Vec<_>>();
    barrier.wait();
    let results = threads
        .into_iter()
        .map(|thread| thread.join().expect("worker"))
        .collect::<Vec<_>>();
    assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
    assert_eq!(registrations.load(Ordering::Relaxed), 1);
    assert_eq!(journal.snapshot().active, 1);
    drop(results);
    assert_eq!(journal.snapshot().active, 0);
}
