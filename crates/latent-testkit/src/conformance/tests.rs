use serde_json::json;

use super::{
    encode_bounded, CaseEvidence, ConformanceReport, EvidenceStatus, ReportIdentity, ReportLimits,
    WorkCounter, WorkCounts,
};

#[test]
fn rejected_invocation_attempts_share_the_same_hard_work_ceiling() {
    let counter = WorkCounter::with_limits(2, 4).unwrap();
    counter.before_command(true).unwrap(); // The driver may receive InvalidArgument.
    let other_driver_handle = counter.clone();
    other_driver_handle.before_command(true).unwrap();
    assert!(counter.before_command(true).is_err());
    assert_eq!(counter.snapshot().invoke_attempts, 2);
    assert!(counter.snapshot().budget_exhausted);
}

#[test]
fn command_ceiling_also_bounds_non_invocation_work() {
    let counter = WorkCounter::with_limits(0, 2).unwrap();
    counter.before_command(false).unwrap();
    counter.before_command(false).unwrap();
    assert!(counter.before_command(false).is_err());
    assert_eq!(counter.snapshot().commands, 2);
    assert!(counter.snapshot().budget_exhausted);
    assert!(WorkCounter::with_limits(65, 256).is_err());
    assert!(WorkCounter::with_limits(64, 257).is_err());
}

#[test]
fn expanded_drivers_share_the_same_total_work_ceiling() {
    use super::{
        ADAPTER_MAXIMUM_COMMANDS, ADAPTER_MAXIMUM_INVOKE_ATTEMPTS, MAXIMUM_COMMANDS,
        MAXIMUM_INVOKE_ATTEMPTS, PROCESS_MAXIMUM_COMMANDS, PROCESS_MAXIMUM_INVOKE_ATTEMPTS,
    };
    assert_eq!(
        PROCESS_MAXIMUM_COMMANDS + ADAPTER_MAXIMUM_COMMANDS,
        MAXIMUM_COMMANDS
    );
    assert_eq!(
        PROCESS_MAXIMUM_INVOKE_ATTEMPTS + ADAPTER_MAXIMUM_INVOKE_ATTEMPTS,
        MAXIMUM_INVOKE_ATTEMPTS
    );
    let mut report = report();
    let too_many = WorkCounts {
        commands: 37,
        invoke_attempts: 37,
        budget_exhausted: false,
    };
    assert!(report.finish_process(too_many).is_err());
    assert_eq!(report.work, WorkCounts::default());
    let process = WorkCounts {
        commands: PROCESS_MAXIMUM_COMMANDS,
        invoke_attempts: PROCESS_MAXIMUM_INVOKE_ATTEMPTS,
        budget_exhausted: false,
    };
    report.finish_process(process).unwrap();
    let fragment = super::DriverEvidence {
        driver: "adapter".to_owned(),
        cases: vec![],
        work: WorkCounts {
            commands: ADAPTER_MAXIMUM_COMMANDS,
            invoke_attempts: ADAPTER_MAXIMUM_INVOKE_ATTEMPTS,
            budget_exhausted: false,
        },
        artifacts: vec![],
    };
    report.merge_driver(fragment).unwrap();
    assert_eq!(report.work.commands, MAXIMUM_COMMANDS);
    assert_eq!(report.work.invoke_attempts, MAXIMUM_INVOKE_ATTEMPTS);
    assert!(
        report.validate_deterministic().is_err(),
        "budgets alone never establish case completion"
    );
}

#[test]
fn concurrent_callers_cannot_oversubscribe_the_shared_counter() {
    let counter = WorkCounter::with_limits(4, 4).unwrap();
    let accepted = std::thread::scope(|scope| {
        let jobs: Vec<_> = (0..8)
            .map(|_| {
                let counter = counter.clone();
                scope.spawn(move || counter.before_command(true).is_ok())
            })
            .collect();
        jobs.into_iter()
            .map(|job| usize::from(job.join().unwrap()))
            .sum::<usize>()
    });
    assert_eq!(accepted, 4);
    assert_eq!(counter.snapshot().invoke_attempts, 4);
    assert!(counter.snapshot().budget_exhausted);
}

#[test]
fn full_unsigned_precision_is_canonical_and_noncanonical_values_fail() {
    let counts = WorkCounts {
        commands: u64::MAX,
        invoke_attempts: 1,
        budget_exhausted: false,
    };
    let value = serde_json::to_value(counts).unwrap();
    assert_eq!(value["commands"], u64::MAX.to_string());
    assert_eq!(serde_json::from_value::<WorkCounts>(value).unwrap(), counts);
    for invalid in [
        json!(1),
        json!("01"),
        json!("+1"),
        json!("18446744073709551616"),
    ] {
        assert!(serde_json::from_value::<WorkCounts>(
            json!({"commands": invalid, "invoke_attempts": "0", "budget_exhausted": false})
        )
        .is_err());
    }
}

#[test]
fn serialization_bounds_the_escaped_output_not_only_input_lengths() {
    let value = json!({"diagnostic": "\n".repeat(16)});
    assert!(encode_bounded(&value, ReportLimits { maximum_bytes: 32 }).is_err());
    let bytes = encode_bounded(&value, ReportLimits { maximum_bytes: 128 }).unwrap();
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&bytes).unwrap(),
        value
    );
}

fn report() -> ConformanceReport {
    ConformanceReport::new(
        ReportIdentity {
            source_commit: "a".repeat(40),
            source_tree: "b".repeat(40),
            source_dirty: true,
            cargo_lock_sha256: format!("sha256:{}", "c".repeat(64)),
            config_sha256: format!("sha256:{}", "d".repeat(64)),
            binaries: vec![],
            fixtures: vec![],
        },
        json!({"os": "test"}),
        json!({"cells": 2}),
        "not-measured".to_owned(),
    )
}

#[test]
fn initial_missing_case_evidence_is_failed_and_heavy_work_is_explicitly_unrun() {
    let mut report = report();
    assert!(report.validate_deterministic().is_err());
    assert_eq!(report.deterministic_status, EvidenceStatus::Failed);
    assert_eq!(report.phase1_completion, "incomplete");
    assert_eq!(report.deferred_evidence.len(), 8);
    assert!(report
        .deferred_evidence
        .iter()
        .all(|entry| entry.status == EvidenceStatus::NotRun
            && entry.reason == "not-authorized-heavy-work"));
    assert!(report.encode_bounded(ReportLimits::default()).is_ok());
}

#[test]
fn completed_cases_cannot_be_overwritten_or_invented() {
    let mut report = report();
    let case = CaseEvidence::passed(
        "empty-readiness",
        WorkCounts::default(),
        json!({"ready": true}),
    );
    report.record_case(case.clone()).unwrap();
    assert!(report.record_case(case).is_err());
    assert!(report
        .record_case(CaseEvidence::passed(
            "invented",
            WorkCounts::default(),
            json!({})
        ))
        .is_err());
    assert!(report.validate_deterministic().is_err());
}
