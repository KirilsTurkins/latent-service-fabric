use super::*;
use crate::activation_runner::{failure_for_platform_error, outcome_consumption};
use crate::transaction_runtime::tests::fixture::Fixture;
use crate::transaction_runtime::TransactionAdmissionResult;
use crate::TransactionActivationAdmission;
use latent_activation::ActivationSuccess;
use latent_core::{
    transaction_contract::{ExpectedVersion, Precondition, Value},
    ActivationBudget, ActivationClock, ClockSample, Metadata,
};
use latent_effects::runtime::CommandAdmissionSource;
use latent_executor::transaction::Mode;
use latent_state::embedded::Family;
use std::{
    sync::atomic::{AtomicUsize, Ordering},
    time::Instant,
};

struct Opening {
    admission: Arc<NativeTransactionAdmission>,
    envelope: ActivationEnvelope,
    budget: ActivationBudget,
    original: CommandRecord,
    original_rows: Vec<Option<Vec<u8>>>,
    outcome: ActivationOutcome,
}

fn stale_precondition(admission: &NativeTransactionAdmission) {
    let mut state = admission.state.lock().unwrap();
    let State::Fresh(Some(selection)) = &mut *state else {
        panic!("original fresh selection absent");
    };
    selection.expected_versions.push(Precondition {
        key: b"counter".to_vec(),
        expected: ExpectedVersion::Absent,
    });
}

async fn failed_opening(fixture: &Fixture, key: &str) -> Opening {
    let (seed, envelope, budget) = fixture.invocation(false, "seed");
    let host = seed.admit(&envelope, &budget).await.unwrap();
    host.acquire(Mode::Command).unwrap();
    host.put(
        b"counter".to_vec(),
        Value {
            bytes: b"original value".to_vec(),
            media_type: "application/octet-stream".into(),
            metadata: Vec::new(),
        },
    )
    .await
    .unwrap();
    host.finish_guest_access();
    let consumption = budget
        .finalize_at(None, Instant::now())
        .consumption()
        .clone();
    let observed = seed
        .complete(
            ActivationOutcome::Succeeded(ActivationSuccess {
                output: b"seed".to_vec(),
                output_media_type: "application/octet-stream".into(),
                metadata: Metadata::new(),
                consumption,
                committed_state_version: None,
                effect_ids: Vec::new(),
            }),
            fixture.commit_control(&envelope, &budget),
        )
        .await;
    assert!(matches!(observed, ActivationOutcome::Succeeded(_)));
    drop((seed.take_owned_completion().unwrap(), seed, host));

    let (admission, envelope, budget) = fixture.invocation(false, key);
    stale_precondition(&admission);
    let failure = admission.admit(&envelope, &budget).await.err().unwrap();
    assert_eq!(failure.code, PlatformErrorCode::StateConflict);
    let original = {
        let state = admission.state.lock().unwrap();
        let State::Pending {
            claim: Some(claim),
            conflict: Some(_),
            ..
        } = &*state
        else {
            panic!("actual original host-open conflict marker absent");
        };
        claim.record().clone()
    };
    let original_rows = original_rows(fixture, &original).await;
    let consumption = budget
        .finalize_at(None, Instant::now())
        .consumption()
        .clone();
    Opening {
        admission,
        envelope,
        budget,
        original,
        original_rows,
        outcome: failure_for_platform_error(failure, consumption),
    }
}

async fn original_rows(fixture: &Fixture, original: &CommandRecord) -> Vec<Option<Vec<u8>>> {
    let keys = [
        latent_commit::atomic::command_row_key(original.id()),
        latent_commit::atomic::attempt_row_key(original.id(), original.attempt()),
        latent_commit::atomic::result_row_key(original.id(), original.attempt()),
    ];
    fixture
        .protected_store()
        .with_store(StoreIoKind::Read, 128 * 1024, move |store| {
            let view = store.snapshot()?;
            keys.iter().map(|key| view.get(key)).collect()
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap()
}

async fn pending(fixture: &Fixture, original: &CommandRecord) {
    let (stored, result) = fixture.inspect(original.key().clone()).await;
    assert_eq!(stored.id(), original.id());
    assert_eq!(stored.attempt(), original.attempt());
    assert_eq!(stored.transaction_id(), original.transaction_id());
    assert_eq!(stored.source(), original.source());
    assert_eq!(stored.fingerprint(), original.fingerprint());
    assert_eq!(stored.outcome(), latent_commit::atomic::Outcome::Pending);
    assert!(stored.abort_proof().is_none() && result.is_none());
    assert_eq!(fixture.rows(Family::State).await, 1);
    assert_eq!(fixture.rows(Family::Outbox).await, 0);
}

struct ProtectedCommandClock {
    source: CommandAdmissionSource,
    samples: AtomicUsize,
    expired: Option<Instant>,
}
impl ActivationClock for ProtectedCommandClock {
    fn monotonic_now(&self) -> Instant {
        // This enters the real original protected dispatcher. Calling it from
        // the role acceptance callback would recursively acquire that owner.
        self.source.command_time().unwrap();
        self.samples.fetch_add(1, Ordering::SeqCst);
        self.expired.unwrap_or_else(Instant::now)
    }
    fn sample(&self) -> ClockSample {
        let observed = self.monotonic_now();
        ClockSample::new(self.source.command_time().unwrap().unix_millis, observed)
    }
}

#[tokio::test]
async fn protected_original_clock_is_sampled_before_publication_and_response_fences() {
    let fixture = Fixture::new().await;
    let opening = failed_opening(&fixture, "protected-clock").await;
    let clock = Arc::new(ProtectedCommandClock {
        source: opening.admission.owners.command.clone(),
        samples: AtomicUsize::new(0),
        expired: None,
    });
    let control = fixture
        .commit_control(&opening.envelope, &opening.budget)
        .with_native_test_clock(clock.clone());
    let observed = opening
        .admission
        .complete(opening.outcome.clone(), control)
        .await;
    assert_eq!(observed, opening.outcome);
    let completion = opening.admission.take_owned_completion().unwrap().unwrap();
    let TransactionCompletionResult::Command(CommandCompletionDisposition::Durable {
        command,
        result,
        ..
    }) = &completion.result
    else {
        panic!("protected-clock original conflict lacks durable abort");
    };
    assert_eq!(command.id(), opening.original.id());
    assert!(command.abort_proof().is_some());
    assert_eq!(result.code(), Some("state-conflict"));
    let before = clock.samples.load(Ordering::SeqCst);
    let mut releases = 0;
    completion
        .authority
        .with_current(&mut || releases += 1)
        .unwrap();
    assert_eq!(releases, 1);
    assert!(clock.samples.load(Ordering::SeqCst) > before);
    drop((completion, opening, clock));
    fixture.shutdown().await;
}

#[tokio::test]
async fn missing_original_conflict_marker_and_contradictory_fault_preserve_pending() {
    for missing in [true, false] {
        let fixture = Fixture::new().await;
        let mut opening = failed_opening(&fixture, "unqualified-fault").await;
        if missing {
            let mut state = opening.admission.state.lock().unwrap();
            let State::Pending { conflict, .. } = &mut *state else {
                unreachable!()
            };
            conflict.take();
        } else {
            opening.outcome = failure_for_platform_error(
                super::super::error(PlatformErrorCode::GuestTrap, "original unrelated fault"),
                outcome_consumption(&opening.outcome),
            );
        }
        let observed = opening
            .admission
            .complete(
                opening.outcome.clone(),
                fixture.commit_control(&opening.envelope, &opening.budget),
            )
            .await;
        assert_eq!(observed, opening.outcome);
        let completion = opening.admission.take_owned_completion().unwrap().unwrap();
        assert!(matches!(
            &completion.result,
            TransactionCompletionResult::PendingRetired { proof: Ok(_), .. }
        ));
        pending(&fixture, &opening.original).await;
        drop((completion, opening));
        fixture.shutdown().await;
    }
}

#[tokio::test]
async fn mismatched_original_identity_fingerprint_and_physical_store_cannot_publish_abort() {
    for mismatch in 0..4 {
        let fixture = Fixture::new().await;
        let opening = failed_opening(&fixture, "mismatched-original").await;
        let foreign = Fixture::new().await;
        {
            let mut state = opening.admission.state.lock().unwrap();
            let State::Pending {
                conflict: Some(marker),
                ..
            } = &mut *state
            else {
                unreachable!()
            };
            match mismatch {
                0 => marker.attempt += 1,
                1 => marker.fingerprint[0] ^= 1,
                2 => marker.store = Arc::downgrade(foreign.protected_store()),
                _ => marker.command.push('0'),
            }
        }
        let observed = opening
            .admission
            .complete(
                opening.outcome.clone(),
                fixture.commit_control(&opening.envelope, &opening.budget),
            )
            .await;
        assert_eq!(observed, opening.outcome);
        let completion = opening.admission.take_owned_completion().unwrap().unwrap();
        assert!(matches!(
            &completion.result,
            TransactionCompletionResult::PendingRetired { proof: Ok(_), .. }
        ));
        pending(&fixture, &opening.original).await;
        drop((completion, opening));
        foreign.shutdown().await;
        fixture.shutdown().await;
    }
}

#[tokio::test]
async fn protected_original_deadline_cannot_be_replaced_by_recovery_time() {
    let fixture = Fixture::new().await;
    let opening = failed_opening(&fixture, "original-expired").await;
    let clock = Arc::new(ProtectedCommandClock {
        source: opening.admission.owners.command.clone(),
        samples: AtomicUsize::new(0),
        expired: opening.budget.deadline().monotonic(),
    });
    let control = fixture
        .commit_control(&opening.envelope, &opening.budget)
        .with_native_test_clock(clock.clone());
    let observed = opening
        .admission
        .complete(opening.outcome.clone(), control)
        .await;
    assert_eq!(observed, opening.outcome);
    let completion = opening.admission.take_owned_completion().unwrap().unwrap();
    assert!(matches!(
        &completion.result,
        TransactionCompletionResult::PendingRetired { proof: Ok(_), .. }
    ));
    pending(&fixture, &opening.original).await;
    drop((completion, opening, clock));
    fixture.shutdown().await;
}

#[tokio::test]
async fn cancelled_or_transport_stopped_original_authority_cannot_publish_pre_host_abort() {
    for cancelled in [true, false] {
        let fixture = Fixture::new().await;
        let opening = failed_opening(&fixture, "stopped-original").await;
        let control = fixture.commit_control(&opening.envelope, &opening.budget);
        if cancelled {
            fixture.cancel_original(&opening.envelope);
        } else {
            control.stop_transport_for_native_test();
        }
        let observed = opening
            .admission
            .complete(opening.outcome.clone(), control)
            .await;
        let completion = opening.admission.take_owned_completion().unwrap();
        assert_eq!(observed, opening.outcome);
        assert!(matches!(
            completion.as_ref().map(|c| &c.result),
            Some(TransactionCompletionResult::PendingRetired { proof: Ok(_), .. })
        ));
        pending(&fixture, &opening.original).await;
        drop((completion, opening));
        fixture.shutdown().await;
    }
}

#[tokio::test]
async fn current_policy_revocation_and_original_identity_expiry_cannot_publish_pre_host_abort() {
    for revoked in [true, false] {
        let fixture = Fixture::new().await;
        let opening = failed_opening(&fixture, "lost-current-authority").await;
        if revoked {
            fixture.revoke();
        } else {
            fixture.set_result_time(opening.original.identity_expires(), true);
        }
        let observed = opening
            .admission
            .complete(
                opening.outcome.clone(),
                fixture.commit_control(&opening.envelope, &opening.budget),
            )
            .await;
        let completion = opening.admission.take_owned_completion().unwrap();
        assert!(
            matches!(observed, ActivationOutcome::Failed { ref error, .. } if error.code == PlatformErrorCode::Unavailable)
        );
        assert_eq!(
            outcome_consumption(&observed),
            outcome_consumption(&opening.outcome)
        );
        assert!(matches!(
            completion.as_ref().map(|c| &c.result),
            Some(TransactionCompletionResult::Command(
                CommandCompletionDisposition::RecoveryRequired { .. }
            ))
        ));
        if revoked {
            // Test-only physical row comparison proves no mutation; it grants
            // no retained result or production inspection authority.
            assert_eq!(
                original_rows(&fixture, &opening.original).await,
                opening.original_rows
            );
        } else {
            pending(&fixture, &opening.original).await;
        }
        assert_eq!(fixture.rows(Family::State).await, 1);
        assert_eq!(fixture.rows(Family::Outbox).await, 0);
        drop((completion, opening));
        fixture.shutdown().await;
    }
}

#[tokio::test]
async fn physical_original_attempt_owner_blocks_abort_until_real_retirement() {
    let fixture = Fixture::new().await;
    let opening = failed_opening(&fixture, "physical-owner").await;
    let (physical, retirement, role) = {
        let state = opening.admission.state.lock().unwrap();
        let State::Pending {
            claim: Some(claim),
            role,
            ..
        } = &*state
        else {
            unreachable!()
        };
        (
            claim.physical_work().unwrap(),
            claim.retirement(),
            role.clone(),
        )
    };
    let observed = opening
        .admission
        .complete(
            opening.outcome.clone(),
            fixture.commit_control(&opening.envelope, &opening.budget),
        )
        .await;
    assert_eq!(observed, opening.outcome);
    let completion = opening.admission.take_owned_completion().unwrap().unwrap();
    assert!(matches!(
        &completion.result,
        TransactionCompletionResult::PendingRetired {
            proof: Err(AtomicError::RecoveryRequired),
            ..
        }
    ));
    assert!(!retirement.physically_retired());
    assert!(retirement.proven_noncommit().is_err());
    pending(&fixture, &opening.original).await;
    physical.retire();
    assert!(retirement.physically_retired());
    assert!(retirement.proven_noncommit().is_ok());
    role.retire().unwrap();
    drop((completion, opening, retirement, role));
    fixture.shutdown().await;
}

#[tokio::test]
async fn original_transport_and_policy_are_rechecked_for_each_confirmed_abort_frame() {
    for transport in [true, false] {
        let fixture = Fixture::new().await;
        let opening = failed_opening(&fixture, "current-response").await;
        let control = fixture.commit_control(&opening.envelope, &opening.budget);
        assert_eq!(
            opening
                .admission
                .complete(opening.outcome.clone(), control.clone())
                .await,
            opening.outcome
        );
        let completion = opening.admission.take_owned_completion().unwrap().unwrap();
        assert!(
            matches!(&completion.result, TransactionCompletionResult::Command(CommandCompletionDisposition::Durable { command, .. }) if command.abort_proof().is_some())
        );
        let mut frames = 0;
        completion
            .authority
            .with_current(&mut || frames += 1)
            .unwrap();
        assert_eq!(frames, 1);
        if transport {
            control.stop_transport_for_native_test();
        } else {
            fixture.revoke();
        }
        assert!(completion
            .authority
            .with_current(&mut || frames += 1)
            .is_err());
        assert_eq!(frames, 1);
        if transport {
            let (stored, result) = fixture.inspect(opening.original.key().clone()).await;
            assert!(stored.abort_proof().is_some());
            assert_eq!(result.unwrap().code(), Some("state-conflict"));
        }
        drop((completion, opening));
        fixture.shutdown().await;
    }
}

#[tokio::test]
async fn canonical_original_replay_keeps_the_old_stale_precondition_and_retained_abort() {
    let fixture = Fixture::new().await;
    let opening = failed_opening(&fixture, "canonical-stale-replay").await;
    assert_eq!(
        opening
            .admission
            .complete(
                opening.outcome.clone(),
                fixture.commit_control(&opening.envelope, &opening.budget)
            )
            .await,
        opening.outcome
    );
    drop(opening.admission.take_owned_completion().unwrap());
    let (replay, envelope, budget) = fixture.invocation(false, "canonical-stale-replay");
    stale_precondition(&replay);
    assert_eq!(
        replay.admit(&envelope, &budget).await.err().unwrap().code,
        PlatformErrorCode::AlreadyExists
    );
    let consumption = budget
        .finalize_at(None, Instant::now())
        .consumption()
        .clone();
    replay
        .complete(
            failure_for_platform_error(
                super::super::error(PlatformErrorCode::Unavailable, "retained original command"),
                consumption,
            ),
            fixture.commit_control(&envelope, &budget),
        )
        .await;
    let completion = replay.take_owned_completion().unwrap().unwrap();
    let TransactionCompletionResult::Existing {
        command,
        result: Ok(Some(result)),
        ..
    } = &completion.result
    else {
        panic!("original retained replay absent")
    };
    assert_eq!(command.id(), opening.original.id());
    assert_eq!(command.attempt(), opening.original.attempt());
    assert_eq!(command.transaction_id(), opening.original.transaction_id());
    assert_eq!(command.fingerprint(), opening.original.fingerprint());
    assert!(command.abort_proof().is_some());
    assert_eq!(result.code(), Some("state-conflict"));
    assert_eq!(fixture.rows(Family::State).await, 1);
    assert_eq!(fixture.rows(Family::Outbox).await, 0);
    drop((completion, replay, opening));
    fixture.shutdown().await;
}

#[tokio::test]
async fn foreign_affine_retirement_proof_cannot_abort_the_original_pending_record() {
    let fixture = Fixture::new().await;
    let opening = failed_opening(&fixture, "original-proof").await;
    let foreign = Fixture::new().await;
    let other = failed_opening(&foreign, "foreign-proof").await;
    let TransactionAdmissionResult::Pending(mut original_pending) =
        opening.admission.take_result().unwrap().unwrap()
    else {
        unreachable!()
    };
    let marker = original_pending.conflict.take().unwrap();
    let original_proof = original_pending.retire_without_guest().unwrap();
    let TransactionAdmissionResult::Pending(other_pending) =
        other.admission.take_result().unwrap().unwrap()
    else {
        unreachable!()
    };
    let foreign_proof = other_pending.retire_without_guest().unwrap();
    let writer = Writer::new(
        &opening.admission,
        marker,
        &opening.original,
        fixture.commit_control(&opening.envelope, &opening.budget),
    )
    .unwrap();
    let active = writer.clone();
    let identity = opening.original.clone();
    let result = fixture
        .protected_store()
        .with_store_retaining(
            StoreIoKind::RecoveryWrite,
            WORK_BYTES,
            writer.clone(),
            move |store| active.publish(store, foreign_proof, &identity),
        )
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    assert!(result.is_none());
    writer.role.retire().unwrap();
    pending(&fixture, &opening.original).await;
    pending(&foreign, &other.original).await;
    drop((result, original_proof, writer, opening, other));
    foreign.shutdown().await;
    fixture.shutdown().await;
}

#[tokio::test]
async fn full_original_recovery_queue_cannot_manufacture_a_pre_host_abort() {
    let fixture = Fixture::new().await;
    let opening = failed_opening(&fixture, "queue-refused").await;
    let snapshot = fixture.protected_store().recovery_snapshot().unwrap();
    let capacity = snapshot.capacity.unwrap();
    assert_eq!(capacity.workers, 1);
    let (entered, started) = tokio::sync::oneshot::channel();
    let (release, parked) = std::sync::mpsc::channel();
    let running = fixture
        .protected_store()
        .with_store(StoreIoKind::RecoveryRead, 1, move |_| {
            entered.send(()).unwrap();
            parked.recv().unwrap();
            Ok(())
        })
        .unwrap();
    started.await.unwrap();
    let queued: Vec<_> = (0..capacity.queued_jobs)
        .map(|_| {
            fixture
                .protected_store()
                .with_store(StoreIoKind::RecoveryRead, 1, |_| Ok(()))
                .unwrap()
        })
        .collect();
    assert_eq!(
        fixture
            .protected_store()
            .recovery_snapshot()
            .unwrap()
            .queued,
        capacity.queued_jobs
    );
    let observed = opening
        .admission
        .complete(
            opening.outcome.clone(),
            fixture.commit_control(&opening.envelope, &opening.budget),
        )
        .await;
    assert_eq!(
        outcome_consumption(&observed),
        outcome_consumption(&opening.outcome)
    );
    let completion = opening.admission.take_owned_completion().unwrap().unwrap();
    assert!(
        matches!(&completion.result, TransactionCompletionResult::Command(CommandCompletionDisposition::RecoveryRequired { command, .. })
        if command.id() == opening.original.id() && command.abort_proof().is_none())
    );
    release.send(()).unwrap();
    running.await.unwrap().unwrap();
    for job in queued {
        job.await.unwrap().unwrap();
    }
    pending(&fixture, &opening.original).await;
    drop((completion, opening));
    fixture.shutdown().await;
}
