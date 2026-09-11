//! Real guest writes reach telemetry immediately, independently of retained capture.
#[path = "telemetry/support.rs"]
mod telemetry_support;
use self::telemetry_support::*;
use super::support::*;
use latent_core::ActivationClock;
use latent_telemetry::{SharedActivationObserverConfig, TelemetryPipelineConfig, TelemetryRecord};
use latent_wasmtime::TelemetryLogSink;
use serde_json::json;
use std::sync::Arc;

#[tokio::test]
#[ignore = "requires contracts-gate capabilities component"]
async fn live_guest_logs_are_correlated_and_redacted_even_when_capture_evicts() {
    let clock = Arc::new(ManualClock::new());
    let pipeline = Pipeline::new(
        TelemetryPipelineConfig::default(),
        SharedActivationObserverConfig {
            allowed_guest_field_names: vec!["allowed".into()],
            ..SharedActivationObserverConfig::default()
        },
    );
    let cancellation = Cancellation::new("live-bridge", &budget(), clock.sample());
    pipeline.register(&cancellation);
    pipeline.handle.flush().await.unwrap();
    pipeline.local.clear();
    let mut services = services(&clock);
    services.log_sink = Some(Arc::new(TelemetryLogSink::new(
        pipeline.observer.clone(),
        clock.clone(),
    )));
    let (backend, prepared) = prepared(capture_config(), services).await;
    let output = returned(
        run(
            &backend,
            request(
                &prepared,
                &cancellation,
                "log-twice",
                &json!([MESSAGE, fields()]),
            ),
            &cancellation,
        )
        .await,
    );
    assert_writes(&output, &cancellation, &clock, true);
    // One record is already evicted, and no terminal observer callback or
    // completion replay has occurred. Both host callbacks were observed live.
    assert_eq!(backend.log_sink().snapshot_for(&cancellation.id).len(), 1);
    assert_eq!(pipeline.observer.snapshot().guest_logs, 2);
    assert_eq!(pipeline.observer.snapshot().active_correlations, 1);
    assert_eq!(pipeline.observer.snapshot().completed, 0);
    pipeline.handle.flush().await.unwrap();
    let logs: Vec<_> = pipeline
        .local
        .records()
        .into_iter()
        .filter_map(|record| {
            if let TelemetryRecord::Log(log) = record {
                Some(log)
            } else {
                None
            }
        })
        .collect();
    assert_eq!(logs.len(), 2);
    for log in logs {
        assert_eq!(log.body, "[REDACTED]");
        assert_eq!(log.attributes["activation_id"], cancellation.id.0);
        assert_eq!(log.attributes["root_activation_id"], "root-pinned");
        assert_eq!(log.attributes["tenant"], "tests");
        assert_eq!(log.attributes["guest.allowed"], "visible");
        assert!(!log.attributes.contains_key("guest.discard"));
        let trace = log.trace.unwrap();
        assert_eq!(trace.trace_id.0, "trace-pinned");
        assert_eq!(trace.span_id.0, "span-pinned");
        assert!(trace.baggage.is_empty());
        assert_eq!(log.observed_at_unix_millis, clock.sample().unix_millis());
    }
    pipeline.runtime.shutdown().await.unwrap();
}

#[tokio::test]
#[ignore = "requires contracts-gate capabilities component"]
async fn closed_telemetry_preserves_default_guest_success_but_strict_mode_refunds() {
    for strict in [false, true] {
        let clock = Arc::new(ManualClock::new());
        let pipeline = Pipeline::new(
            TelemetryPipelineConfig {
                fail_on_drop: strict,
                ..TelemetryPipelineConfig::default()
            },
            SharedActivationObserverConfig::default(),
        );
        let cancellation = Cancellation::new("closed-bridge", &budget(), clock.sample());
        pipeline.register(&cancellation);
        pipeline.handle.flush().await.unwrap();
        drop(pipeline.runtime);
        let before = pipeline.handle.snapshot().dropped_queue_closed;
        let mut services = services(&clock);
        services.log_sink = Some(Arc::new(TelemetryLogSink::new(
            pipeline.observer.clone(),
            clock.clone(),
        )));
        let (backend, prepared) = prepared(capture_config(), services).await;
        let output = returned(
            run(
                &backend,
                request(
                    &prepared,
                    &cancellation,
                    "log-twice",
                    &json!([MESSAGE, fields()]),
                ),
                &cancellation,
            )
            .await,
        );
        assert_writes(&output, &cancellation, &clock, !strict);
        assert_eq!(backend.log_sink().snapshot().len(), usize::from(!strict));
        assert_eq!(pipeline.handle.snapshot().dropped_queue_closed - before, 4);
    }
}

#[tokio::test]
#[ignore = "requires contracts-gate capabilities component"]
async fn full_telemetry_preserves_default_guest_success_but_strict_mode_refunds() {
    for strict in [false, true] {
        let clock = Arc::new(ManualClock::new());
        let pipeline = Pipeline::new(
            TelemetryPipelineConfig {
                queue_capacity: 8,
                fail_on_drop: strict,
                export_timeout: std::time::Duration::from_mins(1),
                ..TelemetryPipelineConfig::default()
            },
            SharedActivationObserverConfig::default(),
        );
        let cancellation = Cancellation::new("full-bridge", &budget(), clock.sample());
        pipeline.register(&cancellation);
        pipeline.handle.flush().await.unwrap();
        pipeline.block().await;
        let before = pipeline.handle.snapshot().dropped_queue_full;
        let mut services = services(&clock);
        services.log_sink = Some(Arc::new(TelemetryLogSink::new(
            pipeline.observer.clone(),
            clock.clone(),
        )));
        let (backend, prepared) = prepared(capture_config(), services).await;
        let output = returned(
            run(
                &backend,
                request(
                    &prepared,
                    &cancellation,
                    "log-twice",
                    &json!([MESSAGE, fields()]),
                ),
                &cancellation,
            )
            .await,
        );
        assert_writes(&output, &cancellation, &clock, !strict);
        assert_eq!(backend.log_sink().snapshot().len(), usize::from(!strict));
        assert_eq!(pipeline.handle.snapshot().dropped_queue_full - before, 4);
        assert_eq!(pipeline.handle.snapshot().queue_depth, 8);
        drop(pipeline.runtime);
    }
}
