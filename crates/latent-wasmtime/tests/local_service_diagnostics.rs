//! Pure fake-invoker regression: runs natively without guest packages or Linux.
#[path = "local_service/diagnostics.rs"]
#[allow(
    dead_code,
    reason = "the real adapter is composed by the shared fixture"
)]
mod diagnostics;
#[path = "local_service/diagnostics/test_support.rs"]
mod support;

use diagnostics::{FailureRecord, Reason, Recorder, Stage, MAX_RECORDS};
use latent_activation::{ActivationOutcome, ActivationSuccess};
use latent_core::{DeclaredError, Metadata, PlatformErrorCode};
use std::{
    sync::{atomic::Ordering, Arc},
    task::{Context, Poll, Waker},
};
use support::{detail_error, error, failed, FakeCompletion, FakeInvoker};

#[test]
#[expect(
    clippy::too_many_lines,
    reason = "one explicit closed vocabulary matrix covers every supported constructor"
)]
fn closed_constructor_shapes_have_distinct_safe_reasons() {
    let currentness = [
        Reason::AdmissionAuthorityBusy,
        Reason::AdmissionAuthorityPoisoned,
        Reason::AdmissionControlBusy,
        Reason::AdmissionClockLeaseUncovered,
        Reason::AdmissionClockRegression,
        Reason::AdmissionDurabilityUncertain,
        Reason::AdmissionOwnerRetired,
        Reason::AdmissionRestartClockFloor,
        Reason::AdmissionVerificationBusy,
        Reason::SignatureClockRegression,
        Reason::SignatureTrustConflict,
        Reason::SignatureStaleProof,
    ];
    assert_eq!(
        currentness.len(),
        latent_core::error::ADMISSION_CURRENTNESS_REASONS.len()
    );
    for (reason, expected) in latent_core::error::ADMISSION_CURRENTNESS_REASONS
        .iter()
        .zip(currentness)
    {
        let mut failure = detail_error("admission.currentness", reason);
        if reason.starts_with("signature-") {
            failure.code = PlatformErrorCode::StateConflict;
            failure.retryable = false;
        }
        support::assert_reason(failure, expected);
    }
    for (reason, expected) in [
        ("shutdown", Reason::SchedulerShutdown),
        ("handoff-closed", Reason::SchedulerHandoffClosed),
        ("sequence-exhausted", Reason::SchedulerSequenceExhausted),
        (
            "all-cells-quarantined",
            Reason::SchedulerAllCellsQuarantined,
        ),
    ] {
        support::assert_reason(detail_error("scheduler.limit", reason), expected);
    }
    let mut quota = detail_error("admission.limit", "quota-state-unavailable");
    quota.details[0].fields.extend([
        ("scope".into(), "node".into()),
        ("dimension".into(), "quota".into()),
    ]);
    support::assert_reason(quota, Reason::QuotaStateUnavailable);
    for (reason, expected) in [
        (
            "preparation-ready-capacity",
            Reason::PreparationReadyCapacity,
        ),
        ("preparation-ready-bytes", Reason::PreparationReadyBytes),
        ("compiler-stopping", Reason::CompilerStopping),
        ("compiler-waiter-capacity", Reason::CompilerWaiterCapacity),
        (
            "compiler-generation-abandoned",
            Reason::CompilerGenerationAbandoned,
        ),
        (
            "compiler-waiter-generation-exhausted",
            Reason::CompilerWaiterGenerationExhausted,
        ),
        ("compiler-job-capacity", Reason::CompilerJobCapacity),
        ("compiler-queue-capacity", Reason::CompilerQueueCapacity),
        (
            "compiler-job-generation-exhausted",
            Reason::CompilerJobGenerationExhausted,
        ),
        (
            "compiler-document-capacity",
            Reason::CompilerDocumentCapacity,
        ),
        (
            "compiler-job-no-longer-pending",
            Reason::CompilerJobNoLongerPending,
        ),
        (
            "compiler-document-already-reserved",
            Reason::CompilerDocumentAlreadyReserved,
        ),
        (
            "compiler-creator-abandoned",
            Reason::CompilerCreatorAbandoned,
        ),
        ("compiler-job-panicked", Reason::CompilerJobPanicked),
        ("compiler-job-abandoned", Reason::CompilerJobAbandoned),
        ("release-lifecycle-busy", Reason::ReleaseLifecycleBusy),
    ] {
        support::assert_reason(error(reason), expected);
    }
    for (reason, expected) in [
        (
            "release-lifecycle-unavailable",
            Reason::ReleaseLifecycleUnavailable,
        ),
        (
            "admission-repository-retired",
            Reason::AdmissionRepositoryRetired,
        ),
    ] {
        let mut failure = error(reason);
        failure.retryable = false;
        support::assert_reason(failure, expected);
    }
}

#[test]
fn unknown_malformed_and_missing_details_are_explicitly_unclassified() {
    let mut missing_reason = detail_error("admission.currentness", "admission-authority-busy");
    missing_reason.details[0].fields.clear();
    let mut extra_field = detail_error("admission.currentness", "admission-authority-busy");
    extra_field.details[0]
        .fields
        .insert("secret".into(), support::PRIVATE.into());
    let mut duplicate_detail = detail_error("admission.currentness", "admission-authority-busy");
    duplicate_detail
        .details
        .push(duplicate_detail.details[0].clone());
    let mut wrong_code = error("compiler-job-panicked");
    wrong_code.code = PlatformErrorCode::PermissionDenied;
    let mut wrong_retry = error("compiler-stopping");
    wrong_retry.retryable = false;
    let mut appended_detail = error("compiler-stopping");
    appended_detail.details = extra_field.details.clone();
    let mut wrong_currentness_code =
        detail_error("admission.currentness", "admission-authority-busy");
    wrong_currentness_code.code = PlatformErrorCode::GuestTrap;
    let mut wrong_currentness_retry =
        detail_error("admission.currentness", "admission-authority-busy");
    wrong_currentness_retry.retryable = false;
    let mut wrong_scheduler_retry = detail_error("scheduler.limit", "handoff-closed");
    wrong_scheduler_retry.retryable = false;
    for failure in [
        missing_reason,
        extra_field,
        duplicate_detail,
        wrong_code,
        wrong_retry,
        appended_detail,
        wrong_currentness_code,
        wrong_currentness_retry,
        wrong_scheduler_retry,
        error(support::PRIVATE),
        error("admission-authority-busy"), // not a currentness constructor without its detail
        error("compiler-job-panicked private-token"),
        detail_error("admission.currentness", support::PRIVATE),
        detail_error("admission.currentness", "signature-stale-proof"),
        detail_error(support::PRIVATE, "admission-authority-busy"),
        detail_error("scheduler.limit", support::PRIVATE),
        detail_error("admission.limit", "quota-state-unavailable"),
    ] {
        support::assert_reason(failure, Reason::Unclassified);
    }
}

#[test]
fn synchronous_start_failure_is_forwarded_once_without_cloning() {
    let recorder = Arc::new(Recorder::default());
    let original = detail_error("scheduler.limit", "handoff-closed");
    let message = original.message.as_ptr();
    let details = original.details.as_ptr();
    let mut invoker = FakeInvoker::rejected(original);
    let returned = invoker.observed(recorder.clone()).err().unwrap();
    assert_eq!(invoker.starts, 1);
    assert_eq!(returned.message.as_ptr(), message);
    assert_eq!(returned.details.as_ptr(), details);
    assert_eq!(returned, detail_error("scheduler.limit", "handoff-closed"));
    assert_eq!(
        recorder.snapshot().records,
        [FailureRecord {
            stage: Stage::Start,
            code: PlatformErrorCode::Unavailable,
            reason: Reason::SchedulerHandoffClosed,
        }]
    );
    assert!(!recorder.snapshot().incomplete);
}

#[tokio::test]
async fn asynchronous_error_and_child_failure_forward_original_results_and_owners() {
    let recorder = Arc::new(Recorder::default());
    let original = error("compiler-job-panicked");
    let message = original.message.as_ptr();
    let mut invoker = FakeInvoker::ready(Err(original));
    let returned = invoker
        .observed(recorder.clone())
        .unwrap()
        .await
        .err()
        .unwrap();
    assert_eq!(returned.message.as_ptr(), message);
    assert_eq!(returned, error("compiler-job-panicked"));
    assert_eq!(invoker.starts, 1);
    assert_eq!(invoker.polls.load(Ordering::Relaxed), 1);
    assert_eq!(invoker.drops.load(Ordering::Relaxed), 1);

    let original = detail_error("admission.currentness", "admission-authority-busy");
    let message = original.message.as_ptr();
    let completion = FakeCompletion::new(failed(original));
    let owner_drops = completion.owner.0.clone();
    let mut invoker = FakeInvoker::ready(Ok(completion));
    let returned = invoker.observed(recorder.clone()).unwrap().await.unwrap();
    let ActivationOutcome::Failed {
        error,
        consumption,
        terminal_state,
    } = &returned.outcome
    else {
        panic!("the failed outcome must not be reclassified");
    };
    assert_eq!(error.message.as_ptr(), message);
    assert_eq!(
        error,
        &detail_error("admission.currentness", "admission-authority-busy")
    );
    assert_eq!(*consumption, support::consumption());
    assert_eq!(
        *terminal_state,
        latent_core::ActivationTerminalState::DependencyFailed
    );
    assert_eq!(invoker.starts, 1);
    assert_eq!(owner_drops.load(Ordering::Relaxed), 0);
    assert_eq!(
        recorder.snapshot().records,
        [
            FailureRecord {
                stage: Stage::InvocationError,
                code: PlatformErrorCode::Unavailable,
                reason: Reason::CompilerJobPanicked
            },
            FailureRecord {
                stage: Stage::ChildFailure,
                code: PlatformErrorCode::Unavailable,
                reason: Reason::AdmissionAuthorityBusy
            },
        ]
    );
    drop(returned);
    assert_eq!(owner_drops.load(Ordering::Relaxed), 1);
}

#[tokio::test]
async fn successful_and_declared_outcomes_keep_payloads_and_owners_without_records() {
    let recorder = Arc::new(Recorder::default());
    for declared in [false, true] {
        let payload = support::PRIVATE.as_bytes().to_vec();
        let pointer = payload.as_ptr();
        let outcome = if declared {
            ActivationOutcome::DeclaredError {
                error: DeclaredError {
                    code: "example".into(),
                    message: support::PRIVATE.into(),
                    payload,
                    media_type: "text/plain".into(),
                    metadata: Metadata::new(),
                },
                consumption: support::consumption(),
            }
        } else {
            ActivationOutcome::Succeeded(ActivationSuccess {
                output: payload,
                output_media_type: "text/plain".into(),
                consumption: support::consumption(),
                committed_state_version: None,
                effect_ids: vec![],
                metadata: Metadata::new(),
            })
        };
        let completion = FakeCompletion::new(outcome);
        let owner_drops = completion.owner.0.clone();
        let mut invoker = FakeInvoker::ready(Ok(completion));
        let returned = invoker.observed(recorder.clone()).unwrap().await.unwrap();
        let (payload, consumption) = match &returned.outcome {
            ActivationOutcome::Succeeded(value) if !declared => (&value.output, &value.consumption),
            ActivationOutcome::DeclaredError { error, consumption } if declared => {
                (&error.payload, consumption)
            }
            _ => panic!("the outcome must be forwarded unchanged"),
        };
        assert_eq!(payload.as_ptr(), pointer);
        assert_eq!(payload, support::PRIVATE.as_bytes());
        assert_eq!(consumption, &support::consumption());
        assert_eq!(invoker.starts, 1);
        assert_eq!(owner_drops.load(Ordering::Relaxed), 0);
        assert!(recorder.snapshot().records.is_empty());
        assert!(!recorder.snapshot().incomplete);
        drop(returned);
        assert_eq!(owner_drops.load(Ordering::Relaxed), 1);
    }
}

#[test]
fn full_contended_or_poisoned_observation_storage_never_changes_invocation_results() {
    let recorder = Arc::new(Recorder::default());
    for _ in 0..MAX_RECORDS + 4 {
        support::assert_forwarded_error(recorder.clone());
    }
    assert_eq!(recorder.snapshot().records.len(), MAX_RECORDS);
    assert!(recorder.snapshot().incomplete);
    let recorder = Arc::new(Recorder::default());
    let guard = recorder.storage.lock().unwrap();
    support::assert_forwarded_error(recorder.clone());
    let snapshot = recorder.snapshot();
    assert!(snapshot.records.is_empty());
    assert!(snapshot.incomplete);
    drop(guard);
    support::assert_forwarded_error(recorder.clone());
    assert_eq!(recorder.snapshot().records.len(), 1);
    assert!(recorder.snapshot().incomplete);
    let poisoned = Arc::new(Recorder::default());
    assert!(std::panic::catch_unwind(|| {
        let _guard = poisoned.storage.lock().unwrap();
        panic!("intentional test-only recorder poisoning");
    })
    .is_err());
    support::assert_forwarded_error(poisoned.clone());
    assert!(poisoned.snapshot().records.is_empty());
    assert!(poisoned.snapshot().incomplete);
}

#[test]
fn dropping_unpolled_or_pending_invocations_preserves_inner_ownership() {
    for poll_once in [false, true] {
        let recorder = Arc::new(Recorder::default());
        let completion = FakeCompletion::new(failed(error(support::PRIVATE)));
        let owner_drops = completion.owner.0.clone();
        let mut invoker = FakeInvoker::pending(completion);
        let mut invocation = invoker.observed(recorder.clone()).unwrap();
        assert_eq!(invoker.starts, 1);
        assert_eq!(invoker.polls.load(Ordering::Relaxed), 0);
        assert_eq!(owner_drops.load(Ordering::Relaxed), 0);
        if poll_once {
            assert!(matches!(
                invocation
                    .as_mut()
                    .poll(&mut Context::from_waker(Waker::noop())),
                Poll::Pending
            ));
        }
        assert_eq!(
            invoker.polls.load(Ordering::Relaxed),
            usize::from(poll_once)
        );
        assert_eq!(owner_drops.load(Ordering::Relaxed), 0);
        drop(invocation);
        assert_eq!(invoker.drops.load(Ordering::Relaxed), 1);
        assert_eq!(owner_drops.load(Ordering::Relaxed), 1);
        assert!(recorder.snapshot().records.is_empty());
        assert!(!recorder.snapshot().incomplete);
    }
}
