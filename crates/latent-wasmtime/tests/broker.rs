//! Executed guest tests; no language toolchain fixtures, load run or fake invokes.
#![cfg(target_os = "linux")]
#[path = "broker/component.rs"]
mod component;
#[path = "broker/fixture.rs"]
mod fixture;
#[path = "generic_backend/support.rs"]
#[allow(dead_code)]
mod support;
use fixture::*;
#[path = "broker/async_io.rs"]
mod async_io;

#[tokio::test]
async fn real_guest_runs_with_the_original_phase3_ledger_and_unused_counters_stay_zero() {
    use latent_core::{ActivationBudget, BudgetProfile, EffectiveActivationBudget};
    let mut ceiling = support::budget();
    ceiling.child_calls = 4;
    ceiling.outbound_requests = 2;
    ceiling.blob_read_bytes = 1024;
    ceiling.blob_write_bytes = 1024;
    let f = Fixture::with_budget(ceiling.clone()).await;
    let (mut request, mut control) = f.request("phase3-budget-owner");
    request.budget = ceiling;
    request.activation.budget = request.budget.clone();
    let grant = EffectiveActivationBudget::admit_profile_at(
        BudgetProfile::Phase3,
        &request.budget,
        &request.budget,
        &request.budget,
        None,
        ClockSample::system_now(),
    )
    .unwrap();
    control.budget = ActivationBudget::with_profile(grant, BudgetProfile::Phase3).unwrap();
    let report = f.backend.invoke_contained(request, &control).await;
    let GuestOutcome::Returned { consumption, .. } = report.outcome.unwrap() else {
        panic!("real component must execute its two clock calls");
    };
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    let finalized = control
        .budget
        .finalize_at(Some(&consumption), Instant::now());
    assert!(finalized.violation().is_none());
    // Guest instruction fuel and two 100-fuel clock-provider charges are
    // independently owned in the same activation ledger, without double count.
    assert_eq!(finalized.consumption().cpu_fuel, consumption.cpu_fuel + 200);
    assert!(consumption.cpu_fuel > 0);
    assert_eq!(
        (
            finalized.consumption().child_calls,
            finalized.consumption().outbound_requests,
            finalized.consumption().blob_read_bytes,
            finalized.consumption().blob_write_bytes
        ),
        (0, 0, 0, 0)
    );
    assert_eq!(f.clock.calls.load(Ordering::Acquire), 2);
    f.idle();
}

#[tokio::test]
async fn real_guest_calls_use_fresh_sessions_on_the_same_warm_cell() {
    let f = Fixture::new().await;
    for _ in 0..3 {
        let (request, control) = f.request("same-text-and-cell");
        let report = f.backend.invoke_contained(request, &control).await;
        assert!(matches!(
            report.outcome.unwrap(),
            GuestOutcome::Returned { .. }
        ));
        assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
        assert!(control.budget.snapshot_at(Instant::now()).cpu_fuel > 0);
        f.idle();
    }
    assert_eq!(f.clock.calls.load(Ordering::Acquire), 6);
    assert_eq!(f.backend.cache_snapshot().entries, 1);
}

#[tokio::test]
async fn revocation_during_first_real_host_call_denies_the_second_call_without_deadlocking() {
    let f = Fixture::new().await;
    let policies = f.policies.clone();
    *f.clock.hook.lock().unwrap() = Some(Box::new(move || revoke(&policies)));
    let (request, control) = f.request("revoke-in-provider");
    let report = tokio::time::timeout(
        Duration::from_secs(5),
        f.backend.invoke_contained(request, &control),
    )
    .await
    .unwrap();
    assert!(matches!(
        report.outcome.unwrap(),
        GuestOutcome::Trapped { .. }
    ));
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    assert_eq!(f.clock.calls.load(Ordering::Acquire), 1);
    f.idle();
}

#[tokio::test]
async fn runtime_rejects_forged_owner_context_before_store_or_provider_creation() {
    let f = Fixture::new().await;
    let (mut request, control) = f.request("forged-principal");
    request.activation.principal.tenant = Some(TenantId("foreign".into()));
    assert!(f
        .backend
        .invoke_contained(request, &control)
        .await
        .outcome
        .is_err());
    let (mut request, control) = f.request("forged-revision");
    request
        .activation
        .resolved_revision
        .as_mut()
        .unwrap()
        .route_generation
        .0 += 1;
    assert!(f
        .backend
        .invoke_contained(request, &control)
        .await
        .outcome
        .is_err());
    let (request, _) = f.request("missing-ledger");
    let missing = support::Cancellation::new("missing-ledger");
    assert!(f
        .backend
        .invoke_contained(request, &missing)
        .await
        .outcome
        .is_err());
    assert_eq!(f.backend.resource_snapshot().stores_created, 0);
    assert_eq!(f.clock.calls.load(Ordering::Acquire), 0);
    f.idle();
}

#[tokio::test]
async fn cancellation_in_a_provider_prevents_the_next_guest_call_and_reclaims_owners() {
    let f = Fixture::new().await;
    let (request, control) = f.request("cancel-provider");
    let probe = control.probe.clone();
    *f.clock.hook.lock().unwrap() = Some(Box::new(move || probe.0.store(true, Ordering::Release)));
    let report = f.backend.invoke_contained(request, &control).await;
    assert!(!matches!(report.outcome, Ok(GuestOutcome::Returned { .. })));
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    assert_eq!(f.clock.calls.load(Ordering::Acquire), 1);
    f.idle();
}

#[tokio::test]
async fn managed_factories_and_shutdown_enforce_catalog_and_policy_owners() {
    let f = Fixture::new().await;
    let mut wrong_clock = f.services();
    wrong_clock.clock = Arc::new(latent_core::SystemActivationClock);
    assert!(WasmtimeComponentEngineFactory::with_catalog(
        support::config(),
        wrong_clock,
        f.catalog.lifecycle_authority()
    )
    .is_err());
    assert!(
        WasmtimeComponentEngineFactory::with_host_services(support::config(), f.services())
            .is_err()
    );
    let directory = tempfile::TempDir::new().unwrap();
    let other = DirectoryArtifactRepository::open(
        directory.path().join("catalog"),
        DirectoryArtifactRepositoryConfig::default(),
    )
    .unwrap();
    assert!(WasmtimeComponentEngineFactory::with_catalog(
        support::config(),
        f.services(),
        other.lifecycle_authority()
    )
    .is_err());
    let other_policies = Arc::new(
        PolicyStore::open(
            &directory.path().join("policies"),
            PolicyStoreLimits::default(),
            f.catalog.lifecycle_authority(),
        )
        .unwrap(),
    );
    assert!(f.runtime.check_policy_owner(&other_policies).is_err());
    f.factory.retire_capabilities();
    assert_eq!(f.policies.retained_read_owners(), 0);
    let (request, control) = f.request("retired");
    assert!(f
        .backend
        .invoke_contained(request, &control)
        .await
        .outcome
        .is_err());
    assert_eq!(f.clock.calls.load(Ordering::Acquire), 0);
    f.idle();
}
