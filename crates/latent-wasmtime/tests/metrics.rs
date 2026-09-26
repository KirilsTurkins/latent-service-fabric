//! Real canonical ABI guests, shared telemetry export and reusable cells.
#![cfg(target_os = "linux")]
#[path = "metrics/audit.rs"]
mod audit;
#[path = "../../latent-control-store/tests/admission/support.rs"]
mod authority;
#[path = "metrics/component.rs"]
mod component;
#[path = "metrics/fixture.rs"]
#[allow(dead_code)]
mod fixture;
#[path = "metrics/isolation.rs"]
mod isolation;
#[path = "metrics/ownership.rs"]
mod ownership;
#[path = "generic_backend/support.rs"]
#[allow(dead_code)]
mod support;
use fixture::*;
use latent_capabilities::broker::metrics::MetricActivationLimits;
use latent_telemetry::{custom::CustomAggregation, TelemetryRecord};
use serde_json::{json, Value};
const INVALID: u32 = 1 << 31;
const EXHAUSTED: u32 = INVALID + 1;
const UNAVAILABLE: u32 = INVALID + 2;
fn metric(name: &str, kind: &str, value: f64) -> Value {
    json!({"name":name,"kind":kind,"value":value.to_string(),"unit":"1","attributes":[["region","east"]]})
}
async fn invoke(f: &Fixture, metric: Value, count: u32, mode: u32) -> u32 {
    let (request, control) = f.request("same-id-same-cell", metric, count, mode);
    returned(f, request, control).await
}
async fn returned(
    f: &Fixture,
    request: latent_executor::ExecutionRequest,
    control: Control,
) -> u32 {
    let report = f.backend.invoke_contained(request, &control).await;
    let outcome = report.outcome.unwrap();
    let GuestOutcome::Returned {
        output,
        consumption,
        ..
    } = outcome
    else {
        panic!("guest result: {outcome:?}")
    };
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    assert!(control
        .budget
        .finalize_at(Some(&consumption), Instant::now())
        .violation()
        .is_none());
    assert_eq!(consumption.outbound_requests, 0);
    assert_eq!(consumption.effect_count, 0);
    f.idle();
    serde_json::from_slice::<Vec<u32>>(&output).unwrap()[0]
}

#[tokio::test]
async fn all_four_kinds_use_shared_export_and_host_owned_identity_on_reused_cells() {
    let mut f = Fixture::new(MetricActivationLimits::default()).await;
    for (name, kind, value) in [
        ("requests", "counter", 2.0),
        ("inflight", "up-down-counter", -1.0),
        ("temperature", "gauge", 3.0),
        ("latency", "histogram", 10.0),
    ] {
        assert_eq!(invoke(&f, metric(name, kind, value), 2, 0).await, 1);
    }
    f.telemetry.flush().await.unwrap();
    let records = f.sink.records();
    let samples = records
        .iter()
        .filter_map(|r| match r {
            TelemetryRecord::CustomMetric(p) => Some(p),
            _ => None,
        })
        .collect::<Vec<_>>();
    assert_eq!(samples.len(), 8);
    for sample in &samples {
        let p = sample.point();
        assert!(p.name.starts_with("latent.application."));
        assert_eq!(p.attributes.get("latent.tenant").unwrap(), "tests");
        assert_eq!(p.attributes.get("latent.service").unwrap(), "generic");
        assert_eq!(p.attributes.get("latent.revision").unwrap(), "revision-1");
        assert_eq!(p.attributes.get("guest.region").unwrap(), "east");
        assert_eq!(p.attributes.len(), 4);
    }
    assert_eq!(
        samples[1].aggregation(),
        &CustomAggregation::Sum {
            total: 4.0,
            count: 2
        }
    );
    assert_eq!(
        samples[3].aggregation(),
        &CustomAggregation::Sum {
            total: -2.0,
            count: 2
        }
    );
    assert!(
        matches!(samples[7].aggregation(), CustomAggregation::Histogram { bucket_counts, count: 2, .. } if bucket_counts.as_ref() == [0, 2, 0])
    );
    assert_eq!(f.provider.registry().snapshot().unwrap().queued_bytes, 0);
    assert_eq!(f.backend.cache_snapshot().entries, 1);
    f.exporter.take().unwrap().shutdown().await.unwrap();
}

#[tokio::test]
async fn nonfinite_conflicting_and_injected_observations_never_create_series() {
    let mut f = Fixture::new(MetricActivationLimits::default()).await;
    for mode in 1..=3 {
        assert_eq!(
            invoke(&f, metric("temperature", "gauge", 0.0), 1, mode).await,
            INVALID
        );
    }
    for value in [
        metric("unknown", "counter", 1.0),
        metric("requests", "counter", -1.0),
        metric("requests", "gauge", 1.0),
    ] {
        assert_eq!(invoke(&f, value, 1, 0).await, INVALID);
    }
    for (key, value) in [
        ("unit", json!("ms")),
        ("name", json!("latent.application.requests")),
        (
            "attributes",
            json!([["region", "east"], ["region", "west"]]),
        ),
        ("attributes", json!([["latent.tenant", "other"]])),
        ("attributes", json!([["region", "attacker-value"]])),
    ] {
        let mut input = metric("requests", "counter", 1.0);
        input[key] = value;
        assert_eq!(invoke(&f, input, 1, 0).await, INVALID);
    }
    assert_eq!(f.provider.registry().snapshot().unwrap().active_series, 0);
    assert_eq!(f.provider.snapshot().accepted, 0);
    assert_eq!(
        invoke(&f, metric("requests", "counter", 1.0), 1, 0).await,
        1
    );
    f.exporter.take().unwrap().shutdown().await.unwrap();
}

#[tokio::test]
async fn activation_allowance_resets_but_shared_cardinality_does_not() {
    let mut config = config();
    config.limits.maximum_series_per_tenant = 1;
    let mut f = Fixture::configured(
        MetricActivationLimits {
            maximum_observations: 2,
            ..Default::default()
        },
        config,
        None,
    )
    .await;
    let input = metric("requests", "counter", 1.0);
    assert_eq!(invoke(&f, input.clone(), 3, 0).await, EXHAUSTED);
    assert_eq!(f.provider.snapshot().accepted, 2);
    f.telemetry.flush().await.unwrap();
    assert_eq!(invoke(&f, input.clone(), 2, 0).await, 1);
    let mut other = input;
    other["attributes"] = json!([["region", "west"]]);
    assert_eq!(invoke(&f, other, 1, 0).await, EXHAUSTED);
    assert_eq!(f.provider.registry().snapshot().unwrap().active_series, 1);
    f.exporter.take().unwrap().shutdown().await.unwrap();
}

#[tokio::test]
async fn closed_exporter_is_typed_unavailable_and_denied_principals_cannot_emit() {
    let mut f = Fixture::new(MetricActivationLimits::default()).await;
    let (mut request, control) = f.request("no-grant", metric("requests", "counter", 1.0), 1, 0);
    request.activation.principal.subject = "ungranted-subject".into();
    assert_eq!(returned(&f, request, control).await, UNAVAILABLE);
    f.exporter.take().unwrap().abort();
    assert_eq!(
        invoke(&f, metric("requests", "counter", 1.0), 1, 0).await,
        UNAVAILABLE
    );
    assert_eq!(f.provider.snapshot().accepted, 0);
    f.idle();
}
