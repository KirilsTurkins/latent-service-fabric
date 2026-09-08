use std::sync::atomic::Ordering;

use latent_activation::ActivationOutcome;
use latent_core::{
    ActivationTerminalState, BudgetConsumption, DeclaredError, Metadata, PlatformErrorCode,
};
use latent_executor::ExecutionBackend;

use super::support::{envelope, success, Backend, Manager};
use crate::conformance::WorkCounter;
use crate::harness::{
    BorrowedBackendHarness, ExpectedOutcome, InvocationCase, InvocationConformanceSuite,
};
use crate::{block_on, BackendHarness, ConformanceCase, ConformanceSuite};

fn fixture(id: &str, expected: ExpectedOutcome) -> InvocationCase {
    InvocationCase {
        case: ConformanceCase {
            id: id.to_owned(),
            description: "Bounded outcome check".to_owned(),
            tags: vec!["contract".to_owned()],
        },
        envelope: envelope(),
        expected,
    }
}

fn expected_success(bytes: &[u8]) -> ExpectedOutcome {
    ExpectedOutcome::Success {
        output: bytes.to_vec(),
        media_type: "text/plain".to_owned(),
    }
}

#[test]
fn borrowed_backend_charges_before_synchronous_start_and_never_retries() {
    let backend = Backend;
    let manager = Manager::new([success(b"accepted")]);
    let work = WorkCounter::with_limits(1, 2).unwrap();
    let harness = BorrowedBackendHarness::new(&backend, &manager, work.clone());
    assert_eq!(harness.backend().backend_id(), backend.backend_id());
    let first = harness.invoke(envelope());
    assert_eq!(
        manager.calls.load(Ordering::Relaxed),
        1,
        "start occurs before the first poll"
    );
    assert_eq!(work.snapshot().invoke_attempts, 1);
    drop(first);
    let second = block_on(harness.invoke(envelope()));
    assert!(
        matches!(second, ActivationOutcome::Failed { error, .. } if error.message == "conformance-work-limit")
    );
    assert_eq!(manager.calls.load(Ordering::Relaxed), 1);
    assert!(work.snapshot().budget_exhausted);
}

#[test]
fn suite_compares_success_domain_and_platform_contracts_without_diagnostics_leaks() {
    let domain = ActivationOutcome::DeclaredError {
        error: DeclaredError {
            code: "empty".to_owned(),
            message: "private domain details".to_owned(),
            payload: b"domain".to_vec(),
            media_type: "text/plain".to_owned(),
            metadata: Metadata::new(),
        },
        consumption: BudgetConsumption::default(),
    };
    let failed = ActivationOutcome::Failed {
        error: super::super::error(PlatformErrorCode::GuestTrap, "private guest details"),
        terminal_state: ActivationTerminalState::GuestTrap,
        consumption: BudgetConsumption::default(),
    };
    let manager = Manager::new([
        success(b"returned"),
        domain,
        failed,
        success(b"private unexpected output"),
    ]);
    let backend = Backend;
    let work = WorkCounter::new();
    let harness = BorrowedBackendHarness::new(&backend, &manager, work.clone());
    let suite = InvocationConformanceSuite::new(vec![
        fixture("success", expected_success(b"returned")),
        fixture(
            "domain",
            ExpectedOutcome::DeclaredError {
                code: "empty".to_owned(),
                payload: b"domain".to_vec(),
                media_type: "text/plain".to_owned(),
            },
        ),
        fixture(
            "platform",
            ExpectedOutcome::PlatformFailure {
                code: PlatformErrorCode::GuestTrap,
                terminal_state: ActivationTerminalState::GuestTrap,
            },
        ),
        fixture("mismatch", expected_success(b"expected")),
    ])
    .unwrap();
    let cases = suite.cases();
    for case in &cases[..3] {
        let result = block_on(suite.run(&harness, case));
        assert!(result.passed);
        assert!(result.diagnostics.is_empty());
    }
    let result = block_on(suite.run(&harness, &cases[3]));
    assert!(!result.passed);
    assert_eq!(
        result.diagnostics,
        ["activation outcome differs from expected contract"]
    );
    assert_eq!(work.snapshot().invoke_attempts, 4);
}

#[test]
fn work_limit_cannot_masquerade_as_an_expected_resource_exhaustion() {
    let backend = Backend;
    let manager = Manager::new([]);
    let work = WorkCounter::with_limits(0, 1).unwrap();
    let harness = BorrowedBackendHarness::new(&backend, &manager, work);
    let suite = InvocationConformanceSuite::new(vec![fixture(
        "exhausted",
        ExpectedOutcome::PlatformFailure {
            code: PlatformErrorCode::ResourceExhausted,
            terminal_state: ActivationTerminalState::Rejected,
        },
    )])
    .unwrap();
    let result = block_on(suite.run(&harness, &suite.cases()[0]));
    assert!(!result.passed);
    assert_eq!(result.diagnostics, ["conformance work limit exceeded"]);
    assert_eq!(manager.calls.load(Ordering::Relaxed), 0);
}

#[test]
fn unregistered_case_never_dispatches_or_copies_untrusted_description() {
    let backend = Backend;
    let manager = Manager::new([]);
    let work = WorkCounter::new();
    let harness = BorrowedBackendHarness::new(&backend, &manager, work.clone());
    let suite =
        InvocationConformanceSuite::new(vec![fixture("known", expected_success(b"ok"))]).unwrap();
    let mut forged = suite.cases().remove(0);
    forged.description = "private unregistered description".to_owned();
    let result = block_on(suite.run(&harness, &forged));
    assert!(!result.passed);
    assert_eq!(result.case.id, "unknown-case");
    assert!(!result.case.description.contains("private"));
    assert_eq!(work.snapshot().commands, 0);
}

#[test]
fn suite_rejects_spare_allocations_duplicates_and_large_work_before_retention() {
    let baseline = fixture("bounded", expected_success(b"ok"));
    let mut oversized = baseline.clone();
    oversized.envelope.input = Vec::with_capacity(4097);
    assert!(InvocationConformanceSuite::new(vec![oversized]).is_err());
    let mut oversized = baseline.clone();
    oversized
        .envelope
        .trace
        .baggage
        .insert("key".to_owned(), String::with_capacity(32 * 1024));
    assert!(InvocationConformanceSuite::new(vec![oversized]).is_err());
    let mut oversized = baseline.clone();
    oversized.envelope.budget.cpu_fuel = 10_000_001;
    assert!(InvocationConformanceSuite::new(vec![oversized]).is_err());
    assert!(InvocationConformanceSuite::new(vec![baseline.clone(), baseline.clone()]).is_err());
    let mut oversized = Vec::with_capacity(9);
    oversized.push(baseline);
    assert!(InvocationConformanceSuite::new(oversized).is_err());
}

#[test]
fn success_payload_and_domain_payload_do_not_share_an_outcome_category() {
    let manager = Manager::new([ActivationOutcome::DeclaredError {
        error: DeclaredError {
            code: "error".to_owned(),
            message: String::new(),
            payload: b"ok".to_vec(),
            media_type: "text/plain".to_owned(),
            metadata: Metadata::new(),
        },
        consumption: BudgetConsumption::default(),
    }]);
    let backend = Backend;
    let harness = BorrowedBackendHarness::new(&backend, &manager, WorkCounter::new());
    let suite = InvocationConformanceSuite::new(vec![fixture("category", expected_success(b"ok"))])
        .unwrap();
    assert!(!block_on(suite.run(&harness, &suite.cases()[0])).passed);
}
