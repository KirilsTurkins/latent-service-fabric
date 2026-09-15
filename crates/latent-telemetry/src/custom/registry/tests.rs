use super::*;
use crate::{
    custom::*, LocalSinkConfig, StructuredLocalSink, TelemetryPipelineConfig, TelemetryRecord,
    TelemetryRuntime,
};
mod retirement;

struct Clock {
    base: Instant,
    millis: AtomicU64,
}
impl Clock {
    fn new() -> Arc<Self> {
        Arc::new(Self {
            base: Instant::now(),
            millis: AtomicU64::new(0),
        })
    }
}
impl ActivationClock for Clock {
    fn monotonic_now(&self) -> Instant {
        self.base + Duration::from_millis(self.millis.load(Ordering::Acquire))
    }
    fn sample(&self) -> latent_core::ClockSample {
        latent_core::ClockSample::system_now()
    }
}
fn config() -> CustomMetricsConfig {
    let metrics = vec![
        ("requests", MetricKind::Counter),
        ("inflight", MetricKind::UpDownCounter),
        ("temperature", MetricKind::Gauge),
        ("latency", MetricKind::Histogram),
    ]
    .into_iter()
    .map(|(name, kind)| CustomMetricDescriptor {
        name: name.into(),
        kind,
        unit: "1".into(),
        labels: vec![CustomMetricLabel {
            key: "region".into(),
            values: vec!["east".into(), "west".into()],
        }],
        histogram_upper_bounds: if kind == MetricKind::Histogram {
            vec![0.0, 10.0]
        } else {
            vec![]
        },
    })
    .collect::<Vec<_>>();
    CustomMetricsConfig {
        limits: CustomMetricLimits::default(),
        tenants: vec![
            TenantMetricsPolicy {
                tenant: "a".into(),
                metrics: metrics.clone(),
            },
            TenantMetricsPolicy {
                tenant: "b".into(),
                metrics,
            },
        ],
    }
}
fn source(tenant: &str) -> CustomMetricSource<'_> {
    CustomMetricSource {
        tenant,
        service: "service",
        revision: "revision",
    }
}
fn input(kind: MetricKind, value: f64, attributes: &[(String, String)]) -> CustomMetricInput<'_> {
    CustomMetricInput {
        name: match kind {
            MetricKind::Counter => "requests",
            MetricKind::UpDownCounter => "inflight",
            MetricKind::Gauge => "temperature",
            MetricKind::Histogram => "latency",
        },
        kind,
        value,
        unit: "1",
        attributes,
    }
}
fn fixture(
    config: CustomMetricsConfig,
) -> (
    Arc<CustomMetricRegistry>,
    Arc<StructuredLocalSink>,
    TelemetryHandle,
    TelemetryRuntime,
    Arc<Clock>,
) {
    let sink = Arc::new(StructuredLocalSink::new(LocalSinkConfig::default()).unwrap());
    let (handle, runtime) =
        TelemetryRuntime::spawn(TelemetryPipelineConfig::default(), sink.clone()).unwrap();
    let clock = Clock::new();
    let registry = CustomMetricRegistry::install(handle.clone(), config, clock.clone()).unwrap();
    (registry, sink, handle, runtime, clock)
}
#[tokio::test]
async fn aggregates_preserve_counter_sign_gauge_order_and_exact_histogram_buckets() {
    let (registry, sink, handle, runtime, _) = fixture(config());
    for (kind, values) in [
        (MetricKind::Counter, vec![2.0, 3.0]),
        (MetricKind::UpDownCounter, vec![3.0, -5.0]),
        (MetricKind::Gauge, vec![4.0, 2.0]),
        (MetricKind::Histogram, vec![-1.0, 0.0, 1.0, 10.0, 11.0]),
    ] {
        for value in values {
            assert_eq!(
                registry.try_emit(source("a"), input(kind, value, &[])),
                Ok(true)
            );
        }
    }
    handle.flush().await.unwrap();
    let records = sink.records();
    let points: Vec<_> = records
        .iter()
        .filter_map(|r| {
            if let TelemetryRecord::CustomMetric(p) = r {
                Some(p)
            } else {
                None
            }
        })
        .collect();
    assert_eq!(points.len(), 11);
    assert_eq!(
        points[1].aggregation(),
        &CustomAggregation::Sum {
            total: 5.0,
            count: 2
        }
    );
    assert_eq!(
        points[3].aggregation(),
        &CustomAggregation::Sum {
            total: -2.0,
            count: 2
        }
    );
    assert_eq!(points[5].point().value.to_bits(), 2.0_f64.to_bits());
    assert!(points.windows(2).all(|p| p[0].sequence() < p[1].sequence()));
    assert_eq!(
        points[10].aggregation(),
        &CustomAggregation::Histogram {
            upper_bounds: vec![0.0, 10.0].into(),
            bucket_counts: vec![2, 2, 1].into(),
            count: 5,
            sum: 21.0
        }
    );
    assert_eq!(points[0].point().name, "latent.application.requests");
    assert_eq!(
        points[0].point().attributes,
        Metadata::from([
            ("latent.tenant".into(), "a".into()),
            ("latent.service".into(), "service".into()),
            ("latent.revision".into(), "revision".into())
        ])
    );
    assert_eq!(registry.snapshot().unwrap().queued_bytes, 0);
    runtime.shutdown().await.unwrap();
}
#[tokio::test]
async fn invalid_observations_and_label_injection_allocate_no_series_or_queue_records() {
    let (registry, _, handle, runtime, _) = fixture(config());
    for value in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY, -1.0] {
        assert_eq!(
            registry.try_emit(source("a"), input(MetricKind::Counter, value, &[])),
            Err(E::InvalidName)
        );
    }
    for attrs in [
        vec![("latent.tenant".into(), "b".into())],
        vec![
            ("region".into(), "east".into()),
            ("region".into(), "west".into()),
        ],
        vec![("region".into(), "unknown".into())],
        vec![("extra".into(), "east".into())],
    ] {
        assert_eq!(
            registry.try_emit(source("a"), input(MetricKind::Counter, 1.0, &attrs)),
            Err(E::InvalidName)
        );
    }
    let mut wrong = input(MetricKind::Counter, 1.0, &[]);
    wrong.unit = "By";
    assert_eq!(registry.try_emit(source("a"), wrong), Err(E::InvalidName));
    wrong = input(MetricKind::Counter, 1.0, &[]);
    wrong.kind = MetricKind::Gauge;
    assert_eq!(registry.try_emit(source("a"), wrong), Err(E::InvalidName));
    assert_eq!(
        registry.try_emit(source("unknown"), input(MetricKind::Counter, 1.0, &[])),
        Err(E::Unavailable)
    );
    assert_eq!(registry.snapshot().unwrap().active_series, 0);
    assert_eq!(handle.snapshot().accepted, 0);
    runtime.shutdown().await.unwrap();
}
#[tokio::test]
async fn series_caps_separate_tenants_and_fixed_rate_windows_refund_rejections() {
    let mut limits = config();
    limits.limits.maximum_series = 2;
    limits.limits.maximum_series_per_tenant = 1;
    limits.limits.observations_per_second = 3;
    limits.limits.observations_per_tenant_per_second = 2;
    let (registry, _, handle, runtime, clock) = fixture(limits);
    let metric = input(MetricKind::Counter, 1.0, &[]);
    assert_eq!(registry.try_emit(source("a"), metric), Ok(true));
    assert_eq!(
        registry.try_emit(
            CustomMetricSource {
                service: "other",
                ..source("a")
            },
            metric
        ),
        Err(E::BudgetExhausted)
    );
    assert_eq!(registry.try_emit(source("a"), metric), Ok(true));
    assert_eq!(
        registry.try_emit(source("a"), metric),
        Err(E::BudgetExhausted)
    );
    assert_eq!(registry.try_emit(source("b"), metric), Ok(true));
    assert_eq!(
        registry.try_emit(source("b"), metric),
        Err(E::BudgetExhausted)
    );
    clock.millis.store(1000, Ordering::Release);
    assert_eq!(registry.try_emit(source("b"), metric), Ok(true));
    assert_eq!(registry.try_emit(source("b"), metric), Ok(true));
    clock.millis.store(0, Ordering::Release);
    assert_eq!(
        registry.try_emit(source("b"), metric),
        Err(E::BudgetExhausted)
    );
    let state = registry.snapshot().unwrap();
    assert_eq!(state.active_series, 2);
    assert_eq!(&state.tenant_series[..2], &[1, 1]);
    assert_eq!(state.accepted, 5);
    handle.flush().await.unwrap();
    runtime.shutdown().await.unwrap();
}
#[tokio::test]
async fn config_failure_does_not_consume_installation_but_retired_owners_cannot_be_replaced() {
    let sink = Arc::new(StructuredLocalSink::new(LocalSinkConfig::default()).unwrap());
    let (handle, runtime) =
        TelemetryRuntime::spawn(TelemetryPipelineConfig::default(), sink).unwrap();
    let mut invalid = config();
    invalid.tenants[0].metrics[0].name = "latent.inject".into();
    assert!(CustomMetricRegistry::install(handle.clone(), invalid, Clock::new()).is_err());
    let registry = CustomMetricRegistry::install(handle.clone(), config(), Clock::new()).unwrap();
    assert!(CustomMetricRegistry::install(handle.clone(), config(), Clock::new()).is_err());
    registry.retire();
    assert_eq!(
        registry.try_emit(source("a"), input(MetricKind::Counter, 1.0, &[])),
        Err(E::Unavailable)
    );
    assert!(CustomMetricRegistry::install(handle, config(), Clock::new()).is_err());
    runtime.shutdown().await.unwrap();
}
