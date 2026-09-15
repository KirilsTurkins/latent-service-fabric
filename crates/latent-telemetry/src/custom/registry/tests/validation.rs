use super::*;

#[tokio::test]
async fn selections_cannot_move_between_registries_or_trusted_sources_or_survive_retirement() {
    let (a, _, ah, ar, _) = fixture(config());
    let (b, _, _, br, _) = fixture(config());
    let selected = a
        .inspect(source("a"), input(MetricKind::Counter, 3.0, &[]))
        .unwrap();
    assert_eq!(
        b.try_emit_selected(source("a"), selected.clone()),
        Err(E::Unavailable)
    );
    assert_eq!(
        a.try_emit_selected(source("b"), selected.clone()),
        Err(E::Unavailable)
    );
    let mut other = source("a");
    other.revision = "new-revision";
    assert_eq!(
        a.try_emit_selected(other, selected.clone()),
        Err(E::Unavailable)
    );
    assert_eq!(a.snapshot().unwrap().active_series, 0);
    assert_eq!(a.try_emit_selected(source("a"), selected.clone()), Ok(true));
    ah.flush().await.unwrap();
    a.retire();
    assert_eq!(
        a.try_emit_selected(source("a"), selected),
        Err(E::Unavailable)
    );
    assert_eq!(a.snapshot().unwrap().accepted, 1);
    assert_eq!(b.snapshot().unwrap().accepted, 0);
    ar.shutdown().await.unwrap();
    br.shutdown().await.unwrap();
}

#[tokio::test]
async fn sum_overflow_rejects_without_mutating_the_aggregate_or_queue() {
    let (registry, sink, handle, runtime, _) = fixture(config());
    assert_eq!(
        registry.try_emit(source("a"), input(MetricKind::Counter, f64::MAX, &[])),
        Ok(true)
    );
    handle.flush().await.unwrap();
    assert_eq!(
        registry.try_emit(source("a"), input(MetricKind::Counter, f64::MAX, &[])),
        Err(E::BudgetExhausted)
    );
    assert_eq!(registry.snapshot().unwrap().queued_bytes, 0);
    assert_eq!(
        registry.try_emit(source("a"), input(MetricKind::Counter, 0.0, &[])),
        Ok(true)
    );
    handle.flush().await.unwrap();
    let records = sink.records();
    let TelemetryRecord::CustomMetric(p) = &records[1] else {
        panic!("custom")
    };
    assert_eq!(
        p.aggregation(),
        &CustomAggregation::Sum {
            total: f64::MAX,
            count: 2
        }
    );
    assert_eq!(p.sequence(), 2);
    assert_eq!(registry.snapshot().unwrap().accepted, 2);
    runtime.shutdown().await.unwrap();
}

#[test]
fn descriptors_reject_incompatible_reuse_reserved_names_and_unbounded_configuration() {
    type Mutation = fn(&mut CustomMetricsConfig);
    let mutations: &[Mutation] = &[
        |c| c.tenants[1].metrics[0].kind = MetricKind::Gauge,
        |c| c.tenants[1].metrics[0].unit = "ms".into(),
        |c| c.tenants[1].metrics[3].histogram_upper_bounds = vec![1.0, 10.0],
        |c| c.tenants[0].metrics[3].histogram_upper_bounds = vec![10.0, 10.0],
        |c| c.tenants[0].metrics[3].histogram_upper_bounds = vec![f64::NAN],
        |c| c.tenants[0].metrics[0].histogram_upper_bounds = vec![1.0],
        |c| c.tenants[0].metrics[0].labels[0].key = "LaTent.tenant".into(),
        |c| c.tenants[0].metrics[0].labels[0].values = vec!["east".into(), "east".into()],
        |c| c.tenants[0].metrics[0].labels[0].values = (0..17).map(|i| i.to_string()).collect(),
        |c| c.tenants[0].metrics[0].name = "1bad".into(),
        |c| c.tenants[0].metrics[0].name.reserve(1000),
        |c| {
            let descriptor = c.tenants[1].metrics[0].clone();
            c.tenants[0].metrics.resize(33, descriptor);
        },
        |c| {
            let tenant = c.tenants[0].clone();
            c.tenants.resize(9, tenant);
        },
        |c| c.limits.maximum_series = 1025,
        |c| c.limits.observations_per_second = 16_385,
        |c| c.limits.maximum_label_bytes = 4097,
        |c| c.limits.maximum_queued_bytes = 32 * 1024 * 1024 + 1,
        |c| c.limits.maximum_queued_bytes_per_tenant = RECORD_BYTES - 1,
    ];
    assert!(config().validate().is_ok());
    for (index, mutate) in mutations.iter().enumerate() {
        let mut c = config();
        mutate(&mut c);
        assert_eq!(c.validate(), Err(E::InvalidName), "case {index}");
    }
}
