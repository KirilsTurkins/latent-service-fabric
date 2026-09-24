use super::*;

#[tokio::test]
async fn identical_components_in_different_tenants_cannot_share_identity_or_aggregation() {
    let mut config = config();
    config.limits.maximum_series_per_tenant = 1;
    let mut f = Fixture::configured(MetricActivationLimits::default(), config, None).await;
    let (other, prepared) = f.other_tenant().await;
    assert_eq!(other.release, f.revision.release);
    assert_ne!(other.publication, f.revision.publication);
    assert_eq!(
        invoke(&f, metric("requests", "counter", 2.0), 2, 0).await,
        1
    );
    assert_eq!(
        invoke(&f, metric("temperature", "gauge", 1.0), 1, 0).await,
        EXHAUSTED
    );
    let (mut request, control) = f.request(
        "same-id-same-cell",
        metric("requests", "counter", 2.0),
        1,
        0,
    );
    request.prepared = prepared;
    request.activation.target = other.target.clone();
    request.activation.principal.tenant = Some(other.target.tenant.clone());
    request.activation.resolved_revision = Some(other);
    request
        .activation
        .principal
        .claims
        .insert("latent.tenant".into(), "tests".into());
    assert_eq!(returned(&f, request, control).await, 1);
    assert_eq!(
        invoke(&f, metric("requests", "counter", 2.0), 1, 0).await,
        1
    );
    f.telemetry.flush().await.unwrap();
    let records = f.sink.records();
    let samples = records
        .iter()
        .filter_map(|r| match r {
            TelemetryRecord::CustomMetric(p) => Some(p),
            _ => None,
        })
        .collect::<Vec<_>>();
    assert_eq!(samples.len(), 4);
    assert_eq!(
        samples[2].point().attributes.get("latent.tenant").unwrap(),
        "other"
    );
    assert_eq!(
        samples[2].aggregation(),
        &CustomAggregation::Sum {
            total: 2.0,
            count: 1
        }
    );
    assert_eq!(
        samples[3].point().attributes.get("latent.tenant").unwrap(),
        "tests"
    );
    assert_eq!(
        samples[3].aggregation(),
        &CustomAggregation::Sum {
            total: 6.0,
            count: 3
        }
    );
    let snapshot = f.provider.registry().snapshot().unwrap();
    assert_eq!(snapshot.active_series, 2);
    assert_eq!(&snapshot.tenant_series[..2], &[1, 1]);
    f.exporter.take().unwrap().shutdown().await.unwrap();
}

#[tokio::test]
async fn cancelled_guest_and_retired_provider_do_not_emit_or_retain_store_resources() {
    let mut f = Fixture::new(MetricActivationLimits::default()).await;
    let (request, control) = f.request("cancelled", metric("requests", "counter", 1.0), 1, 0);
    control.probe.0.store(true, Ordering::Release);
    let report = f.backend.invoke_contained(request, &control).await;
    assert!(!matches!(report.outcome, Ok(GuestOutcome::Returned { .. })));
    assert_eq!(f.provider.snapshot().accepted, 0);
    f.idle();
    f.provider.retire();
    let (request, control) = f.request("retired", metric("requests", "counter", 1.0), 1, 0);
    let report = f.backend.invoke_contained(request, &control).await;
    assert!(!matches!(report.outcome, Ok(GuestOutcome::Returned { .. })));
    assert_eq!(f.provider.snapshot().accepted, 0);
    f.idle();
    f.exporter.take().unwrap().shutdown().await.unwrap();
}

#[tokio::test]
async fn uninstalled_metrics_import_is_rejected_before_a_store_is_created() {
    let mut f = Fixture::new(MetricActivationLimits::default()).await;
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
    f.exporter.take().unwrap().shutdown().await.unwrap();
}
