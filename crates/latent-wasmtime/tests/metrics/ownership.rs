use super::*;
use latent_artifacts::ArtifactRepository;
use latent_capabilities::broker::metrics::{Metric, MetricError};
use latent_telemetry::MetricKind;

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
fn observation(name: &str) -> Metric {
    Metric {
        name: name.into(),
        kind: if name == "requests" {
            MetricKind::Counter
        } else {
            MetricKind::Gauge
        },
        value: 1.0,
        unit: "1".into(),
        attributes: vec![],
    }
}
#[tokio::test]
async fn identical_configuration_on_another_pipeline_does_not_borrow_the_installed_grant() {
    use latent_capabilities::broker::metrics::MetricProvider;
    let mut f = Fixture::new(MetricActivationLimits::default()).await;
    let sink = Arc::new(latent_telemetry::StructuredLocalSink::new(Default::default()).unwrap());
    let (handle, exporter) =
        latent_telemetry::TelemetryRuntime::spawn(Default::default(), sink).unwrap();
    let other = MetricProvider::install(
        &f.broker,
        handle,
        1,
        config(),
        MetricActivationLimits::default(),
    )
    .unwrap();
    assert_eq!(
        other.reference().configuration_digest(),
        f.provider.reference().configuration_digest()
    );
    let (request, control) =
        f.request("foreign-provider", metric("requests", "counter", 1.0), 1, 0);
    let s = session(&f, &request, &control);
    assert!(matches!(
        other.emit(&s, observation("requests")),
        Err(MetricError::Unavailable)
    ));
    assert_eq!(other.registry().snapshot().unwrap().accepted, 0);
    assert_eq!(control.budget.snapshot_at(Instant::now()).cpu_fuel, 0);
    drop(s);
    f.idle();
    exporter.shutdown().await.unwrap();
    f.exporter.take().unwrap().shutdown().await.unwrap();
}
#[tokio::test]
async fn abandoned_work_refunds_activation_series_observations_and_record_bytes() {
    let mut f = Fixture::new(MetricActivationLimits {
        maximum_observations: 1,
        maximum_series: 1,
        maximum_record_bytes: 32768,
    })
    .await;
    let (request, control) = f.request("pending", metric("requests", "counter", 1.0), 1, 0);
    let s = session(&f, &request, &control);
    let pending = f.provider.emit(&s, observation("requests")).unwrap();
    assert!(matches!(
        f.provider.emit(&s, observation("temperature")),
        Err(MetricError::BudgetExhausted)
    ));
    assert_eq!(f.provider.snapshot().accepted, 0);
    drop(pending);
    let result = f
        .provider
        .emit(&s, observation("temperature"))
        .unwrap()
        .await
        .unwrap();
    assert!(result.accepted);
    assert!(matches!(
        f.provider.emit(&s, observation("temperature")),
        Err(MetricError::BudgetExhausted)
    ));
    drop(s);
    assert_eq!(f.broker.snapshot().calls, 1);
    drop(result);
    f.idle();
    assert_eq!(control.budget.outstanding_reservations(), 0);
    f.exporter.take().unwrap().shutdown().await.unwrap();
}
#[tokio::test]
async fn queue_failure_refunds_a_pending_activation_and_does_not_create_its_series() {
    let mut config = config();
    config.limits.maximum_queued_bytes_per_tenant = 32768;
    let mut f = Fixture::configured(
        MetricActivationLimits {
            maximum_observations: 1,
            maximum_series: 1,
            maximum_record_bytes: 32768,
        },
        config,
        None,
    )
    .await;
    let (request, control) = f.request("retry", metric("requests", "counter", 1.0), 1, 0);
    let s = session(&f, &request, &control);
    // Occupy the shared queue without yielding to the exporter on this thread.
    let registry = f.provider.registry();
    assert_eq!(
        registry.try_emit(
            latent_telemetry::custom::CustomMetricSource {
                tenant: "tests",
                service: "generic",
                revision: "revision-1"
            },
            latent_telemetry::custom::CustomMetricInput {
                name: "requests",
                kind: MetricKind::Counter,
                value: 1.0,
                unit: "1",
                attributes: &[]
            }
        ),
        Ok(true)
    );
    assert!(matches!(
        f.provider
            .emit(&s, observation("temperature"))
            .unwrap()
            .await,
        Err(MetricError::BudgetExhausted)
    ));
    assert_eq!(registry.snapshot().unwrap().active_series, 1);
    f.telemetry.flush().await.unwrap();
    let result = f
        .provider
        .emit(&s, observation("temperature"))
        .unwrap()
        .await
        .unwrap();
    assert!(result.accepted);
    assert_eq!(registry.snapshot().unwrap().active_series, 2);
    drop(result);
    drop(s);
    f.idle();
    f.exporter.take().unwrap().shutdown().await.unwrap();
}
#[tokio::test]
async fn fuel_exhaustion_and_cancelled_pending_work_never_touch_aggregation() {
    let mut f = Fixture::new(MetricActivationLimits::default()).await;
    let (request, control) = f.request("cancel", metric("requests", "counter", 1.0), 1, 0);
    let s = session(&f, &request, &control);
    let available = control.budget.remaining_at(Instant::now()).cpu_fuel;
    let held = control
        .budget
        .reserve(latent_core::BudgetDimension::CpuFuel, available - 99)
        .unwrap();
    assert!(matches!(
        f.provider.emit(&s, observation("requests")),
        Err(MetricError::BudgetExhausted)
    ));
    drop(held);
    let pending = f.provider.emit(&s, observation("requests")).unwrap();
    control.probe.0.store(true, Ordering::Release);
    assert!(matches!(pending.await, Err(MetricError::Unavailable)));
    assert_eq!(f.provider.snapshot().accepted, 0);
    assert_eq!(f.provider.registry().snapshot().unwrap().active_series, 0);
    drop(s);
    f.idle();
    assert_eq!(control.budget.outstanding_reservations(), 0);
    f.exporter.take().unwrap().shutdown().await.unwrap();
}
