use super::*;
use latent_artifacts::ArtifactRepository;

fn session(
    f: &Fixture,
    request: &latent_executor::ExecutionRequest,
    control: &Control,
) -> CapabilitySession {
    let publication = f
        .catalog
        .execution_eligibility_selected(&f.revision.release, f.revision.publication.as_ref())
        .unwrap()
        .unwrap();
    f.broker
        .open_session(f.plan.clone(), request, control, &publication)
        .unwrap()
}
#[tokio::test]
async fn abandoned_pending_calls_refund_aggregate_but_started_failures_spend_it() {
    let source = Arc::new(Source::default());
    let f = Fixture::new(
        Some(source.clone()),
        RandomLimits {
            maximum_bytes_per_call: 8,
            maximum_bytes_per_activation: 8,
        },
    )
    .await;
    let (request, control) = f.request("pending", 0, 8, 1);
    let s = session(&f, &request, &control);
    let pending = f.provider.bytes(&s, 8).unwrap();
    assert!(matches!(
        f.provider.u64_value(&s),
        Err(RandomError::BudgetExhausted)
    ));
    assert_eq!(source.calls.load(Ordering::Acquire), 0);
    drop(pending);
    source.fail.store(true, Ordering::Release);
    assert!(matches!(
        f.provider.u64_value(&s).unwrap().await,
        Err(RandomError::Unavailable)
    ));
    assert!(matches!(
        f.provider.bytes(&s, 1),
        Err(RandomError::BudgetExhausted)
    ));
    assert_eq!(source.calls.load(Ordering::Acquire), 1);
    drop(s);
    f.idle();
    assert_eq!(control.budget.outstanding_reservations(), 0);
}
#[tokio::test]
async fn original_output_owner_outlives_closed_session_and_cancelled_pending_work_skips_entropy() {
    let source = Arc::new(Source::default());
    let f = Fixture::new(Some(source.clone()), RandomLimits::default()).await;
    let (request, control) = f.request("held-result", 0, 8, 1);
    let s = session(&f, &request, &control);
    let result = f.provider.bytes(&s, 8).unwrap().await.unwrap();
    assert!(f.broker.snapshot().buffer_bytes >= 8);
    let pending = f.provider.bytes(&s, 8).unwrap();
    control.probe.0.store(true, Ordering::Release);
    assert!(matches!(pending.await, Err(RandomError::Unavailable)));
    assert_eq!(source.calls.load(Ordering::Acquire), 1);
    drop(s);
    assert!(f.broker.snapshot().buffer_bytes >= 8);
    drop(result);
    f.idle();
    assert_eq!(control.budget.outstanding_reservations(), 0);
}
#[tokio::test]
async fn uninstalled_random_import_is_rejected_before_any_store() {
    let f = Fixture::new(None, RandomLimits::default()).await;
    let factory = WasmtimeComponentEngineFactory::with_catalog(
        support::config(),
        WasmtimeHostServices {
            clock: f.clock.clone(),
            log_sink: None,
            capabilities: None,
            currentness_read_wait: None,
        },
        f.catalog.lifecycle_authority(),
    )
    .unwrap();
    let backend = factory.create_backend_instance();
    let mut key = factory.preparation_key(f.revision.release.clone());
    key.publication = f.revision.publication.clone();
    let error = backend
        .prepare_ready_from_repository(f.catalog.clone(), key)
        .await
        .err()
        .unwrap();
    assert_eq!(
        error.code,
        latent_core::PlatformErrorCode::IncompatibleContract
    );
    assert_eq!(backend.resource_snapshot().stores_created, 0);
    assert_eq!(f.provider.snapshot().generated_bytes, 0);
}

#[tokio::test]
async fn fuel_and_buffer_capacity_are_reserved_before_entropy_or_result_allocation() {
    use latent_core::BudgetDimension::CpuFuel;
    let source = Arc::new(Source::default());
    let f = Fixture::new(Some(source.clone()), RandomLimits::default()).await;
    let (request, control) = f.request("prepaid", 0, 8, 1);
    let s = session(&f, &request, &control);
    let available = control.budget.remaining_at(Instant::now()).cpu_fuel;
    let held = control.budget.reserve(CpuFuel, available - 99).unwrap();
    assert!(matches!(
        f.provider.bytes(&s, 0),
        Err(RandomError::BudgetExhausted)
    ));
    assert!(matches!(
        f.provider.u64_value(&s),
        Err(RandomError::BudgetExhausted)
    ));
    assert_eq!(source.calls.load(Ordering::Acquire), 0);
    assert_eq!(f.broker.snapshot().buffer_bytes, 0);
    drop(held);
    let before = control.budget.snapshot_at(Instant::now()).cpu_fuel;
    let result = f.provider.bytes(&s, 0).unwrap().await.unwrap();
    assert_eq!(
        control.budget.snapshot_at(Instant::now()).cpu_fuel,
        before + 100
    );
    assert_eq!(source.calls.load(Ordering::Acquire), 0);
    drop(result);
    let result = f.provider.u64_value(&s).unwrap().await.unwrap();
    assert_eq!(
        control.budget.snapshot_at(Instant::now()).cpu_fuel,
        before + 208
    );
    assert_eq!(source.calls.load(Ordering::Acquire), 1);
    drop(result);
    drop(s);
    f.idle();
}

#[tokio::test]
async fn a_second_provider_with_identical_metadata_cannot_borrow_the_installed_grant() {
    use latent_capabilities::broker::random::RandomProvider;
    let source = Arc::new(Source::default());
    let f = Fixture::new(Some(source.clone()), RandomLimits::default()).await;
    let second =
        RandomProvider::for_test(&f.broker, 1, RandomLimits::default(), source.clone()).unwrap();
    assert_eq!(
        second.reference().configuration_digest(),
        f.provider.reference().configuration_digest()
    );
    let (request, control) = f.request("foreign-owner", 0, 8, 1);
    let s = session(&f, &request, &control);
    assert!(matches!(second.bytes(&s, 8), Err(RandomError::Unavailable)));
    assert_eq!(source.calls.load(Ordering::Acquire), 0);
    assert_eq!(control.budget.snapshot_at(Instant::now()).cpu_fuel, 0);
    drop(s);
    f.idle();
}

#[tokio::test]
async fn sequential_u64_results_retire_after_lowering_before_the_next_call() {
    let source = Arc::new(Source::default());
    let f = Fixture::new(Some(source.clone()), RandomLimits::default()).await;
    assert_eq!(
        CapabilityBrokerLimits::default().maximum_calls_per_session,
        16
    );
    let count = 33;
    assert!(count > CapabilityBrokerLimits::default().maximum_calls_per_session);
    for _ in 0..2 {
        assert_eq!(
            invoke(&f, 1, 0, u32::try_from(count).unwrap()).await,
            SCALAR
        );
        f.idle();
    }
    assert_eq!(source.calls.load(Ordering::Acquire), 2 * count);
    assert_eq!(f.provider.snapshot().generated_bytes, 2 * count as u64 * 8);
    assert_eq!(f.provider.snapshot().budget_exhaustions, 0);
}

#[tokio::test]
async fn scalar_lowering_destination_errors_and_provider_errors_reclaim_original_calls() {
    let source = Arc::new(Source::default());
    let f = Fixture::new(Some(source.clone()), RandomLimits::default()).await;
    for destination in [131_064, 513] {
        let (request, control) = f.request("bad-scalar-destination", 3, destination, 0);
        let report = f.backend.invoke_contained(request, &control).await;
        assert!(matches!(report.outcome, Ok(GuestOutcome::Trapped { .. })));
        assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
        assert_eq!(control.budget.outstanding_reservations(), 0);
        f.idle();
        assert_eq!(invoke(&f, 1, 0, 33).await, SCALAR);
    }
    source.fail.store(true, Ordering::Release);
    assert_eq!(invoke(&f, 1, 0, 1).await, UNAVAILABLE);
    source.fail.store(false, Ordering::Release);
    assert_eq!(invoke(&f, 1, 0, 33).await, SCALAR);
    f.idle();
}

#[tokio::test]
async fn variable_list_results_keep_the_original_store_owned_lowering_limit() {
    let source = Arc::new(Source::default());
    let f = Fixture::new(Some(source.clone()), RandomLimits::default()).await;
    assert_eq!(invoke(&f, 0, 1, 17).await, EXHAUSTED);
    assert_eq!(source.calls.load(Ordering::Acquire), 16);
    f.idle();
    assert_eq!(invoke(&f, 1, 0, 33).await, SCALAR);
    assert_eq!(source.calls.load(Ordering::Acquire), 49);
}
