use std::sync::Arc;
use std::time::Duration;

use latent_core::{
    ActivationId, ActivationPhase, ActivationTerminalState, BudgetConsumption, ContractId,
    FunctionId, Metadata, PlatformErrorCode, ReleaseDigest, ResourceBudget, RevisionId,
    RouteGeneration, ServiceId, SpanId, TenantId, TraceId,
};

use crate::{
    ActivationObservationToken, ActivationOutcomeClass, ActivationTerminalObservation,
    LocalSinkConfig, LogSeverity, StructuredLocalSink, TelemetryPipelineConfig, TelemetryRecord,
    TelemetryRuntime,
};

use super::*;

fn context(sequence: u64) -> ActivationObservationContext {
    ActivationObservationContext {
        token: ActivationObservationToken {
            manager: 1,
            sequence,
        },
        activation_id: ActivationId("activation".to_owned()),
        root_activation_id: ActivationId("root".to_owned()),
        parent_activation_id: None,
        tenant: TenantId("tenant".to_owned()),
        service: ServiceId("service".to_owned()),
        contract: ContractId("example:component/service@1.0.0".to_owned()),
        function: FunctionId("run".to_owned()),
        trace_id: TraceId("trace".to_owned()),
        span_id: SpanId("span".to_owned()),
        trace_flags: 1,
        release: None,
        revision: None,
        route_generation: None,
    }
}

fn event(kind: ActivationObservationKind) -> ActivationObservation {
    ActivationObservation {
        occurred_at_unix_millis: 1000,
        elapsed: Duration::ZERO,
        kind,
    }
}

fn terminal(class: ActivationOutcomeClass) -> ActivationObservationKind {
    ActivationObservationKind::Terminal(ActivationTerminalObservation {
        class,
        terminal_state: if class == ActivationOutcomeClass::PlatformFailure {
            ActivationTerminalState::GuestTrap
        } else {
            ActivationTerminalState::Completed
        },
        platform_code: (class == ActivationOutcomeClass::PlatformFailure)
            .then_some(PlatformErrorCode::GuestTrap),
        consumption: BudgetConsumption {
            cpu_fuel: 5,
            peak_memory_bytes: 4096,
            wall_time_micros: 2000,
            log_bytes: 3,
            ..BudgetConsumption::default()
        },
        last_phase: ActivationPhase::Running,
        sequence: 7,
    })
}

fn setup(
    config: SharedActivationObserverConfig,
    pipeline: TelemetryPipelineConfig,
) -> (
    SharedActivationObserver,
    StructuredLocalSink,
    TelemetryHandle,
    TelemetryRuntime,
) {
    let sink = StructuredLocalSink::new(LocalSinkConfig::default()).unwrap();
    let (handle, runtime) = TelemetryRuntime::spawn(pipeline, Arc::new(sink.clone())).unwrap();
    let observer = SharedActivationObserver::new(handle.clone(), config).unwrap();
    (observer, sink, handle, runtime)
}

#[tokio::test]
async fn resolved_context_actual_grant_and_monotonic_terminal_are_exported() {
    let (observer, sink, handle, runtime) = setup(
        SharedActivationObserverConfig::default(),
        TelemetryPipelineConfig::default(),
    );
    let mut context = context(1);
    observer.on_observation(&context, &event(ActivationObservationKind::Received));
    handle.flush().await.unwrap();
    assert!(!sink.records().iter().any(|record| matches!(record, TelemetryRecord::Metric(metric) if metric.name == "latent.activation.budget.granted")));
    context.release = Some(ReleaseDigest("sha256:pinned".to_owned()));
    context.revision = Some(RevisionId("revision-2".to_owned()));
    context.route_generation = Some(RouteGeneration(2));
    observer.on_observation(
        &context,
        &event(ActivationObservationKind::Phase {
            phase: ActivationPhase::Resolved,
            sequence: 2,
        }),
    );
    let grant = ResourceBudget {
        cpu_fuel: 7,
        memory_bytes: 8192,
        wall_time_limit_millis: Some(5),
        log_bytes: 4,
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        effect_count: 0,
    };
    observer.on_observation(
        &context,
        &event(ActivationObservationKind::AdmittedGrant(grant)),
    );
    observer.on_observation(
        &context,
        &ActivationObservation {
            occurred_at_unix_millis: 900,
            elapsed: Duration::from_millis(3),
            kind: terminal(ActivationOutcomeClass::GuestSuccess),
        },
    );
    handle.flush().await.unwrap();
    let records = sink.records();
    assert!(records.iter().any(|record| matches!(record, TelemetryRecord::Metric(metric) if
        metric.name == "latent.activation.budget.granted" && metric.attributes.get("resource").is_some_and(|value| value == "cpu_fuel") && (metric.value - 7.0).abs() < f64::EPSILON)));
    assert!(records.iter().any(|record| matches!(record, TelemetryRecord::Metric(metric) if metric.name == "latent.activation.latency" && (metric.value - 3000.0).abs() < f64::EPSILON)));
    let completion = records
        .iter()
        .find_map(|record| match record {
            TelemetryRecord::Span(span) if span.name == "latent.activation" => Some(span),
            _ => None,
        })
        .unwrap();
    assert_eq!(
        records
            .iter()
            .filter(|record| matches!(record, TelemetryRecord::Span(_)))
            .count(),
        1
    );
    for stage in ["receipt", "resolution", "completion"] {
        assert!(records
            .iter()
            .any(|record| matches!(record, TelemetryRecord::Log(log)
            if log.attributes.get("stage").is_some_and(|value| value == stage))));
    }
    assert_eq!(
        completion.ended_at_unix_nanos - completion.started_at_unix_nanos,
        3_000_000
    );
    assert_eq!(completion.attributes["release"], "sha256:pinned");
    assert_eq!(completion.attributes["revision"], "revision-2");
    assert_eq!(completion.attributes["cpu_fuel"], "5");
    assert_eq!(completion.attributes["log_bytes"], "3");
    assert_eq!(observer.snapshot().active_correlations, 0);
    assert_eq!(handle.snapshot().dropped_invalid_record, 0);
    runtime.shutdown().await.unwrap();
}

#[tokio::test]
async fn capacity_never_evicts_active_and_stale_tokens_cannot_remove_reused_ids() {
    let (observer, _, _, runtime) = setup(
        SharedActivationObserverConfig {
            maximum_active_correlations: 1,
            ..Default::default()
        },
        TelemetryPipelineConfig::default(),
    );
    let first = context(1);
    let mut other = context(2);
    other.activation_id = ActivationId("other".to_owned());
    observer.on_observation(&first, &event(ActivationObservationKind::Received));
    observer.on_observation(&other, &event(ActivationObservationKind::Received));
    assert_eq!(
        observer.correlation(&first.activation_id).unwrap().token,
        first.token
    );
    assert_eq!(observer.snapshot().capacity_drops, 1);
    observer.on_observation(
        &first,
        &event(terminal(ActivationOutcomeClass::GuestSuccess)),
    );
    let reused = context(3);
    observer.on_observation(&reused, &event(ActivationObservationKind::Received));
    observer.on_observation(
        &first,
        &event(terminal(ActivationOutcomeClass::PlatformFailure)),
    );
    assert_eq!(
        observer.correlation(&reused.activation_id).unwrap().token,
        reused.token
    );
    assert_eq!(observer.snapshot().completed, 1);
    observer.on_observation(
        &reused,
        &event(terminal(ActivationOutcomeClass::GuestDomainError)),
    );
    assert_eq!(observer.snapshot().completed, 2);
    assert_eq!(observer.snapshot().active_correlations, 0);
    runtime.shutdown().await.unwrap();
}

#[tokio::test]
async fn outcome_classes_and_metric_labels_are_distinct_and_bounded() {
    let (observer, sink, handle, runtime) = setup(
        SharedActivationObserverConfig::default(),
        TelemetryPipelineConfig::default(),
    );
    for (index, class) in [
        ActivationOutcomeClass::GuestSuccess,
        ActivationOutcomeClass::GuestDomainError,
        ActivationOutcomeClass::PlatformFailure,
    ]
    .into_iter()
    .enumerate()
    {
        let context = context(u64::try_from(index).unwrap());
        observer.on_observation(&context, &event(ActivationObservationKind::Received));
        observer.on_observation(&context, &event(terminal(class)));
    }
    handle.flush().await.unwrap();
    let records = sink.records();
    let outcomes: Vec<_> = records
        .iter()
        .filter_map(|record| match record {
            TelemetryRecord::Metric(metric) if metric.name == "latent.activation.outcomes" => {
                Some(metric)
            }
            _ => None,
        })
        .collect();
    assert_eq!(outcomes.len(), 3);
    for (metric, expected) in
        outcomes
            .iter()
            .zip(["guest_success", "guest_domain_error", "platform_failure"])
    {
        assert_eq!(metric.attributes["outcome"], expected);
    }
    assert_eq!(outcomes[2].attributes["error_code"], "guest-trap");
    for record in records {
        if let TelemetryRecord::Metric(metric) = record {
            assert!(!metric.attributes.keys().any(|name| [
                "activation_id",
                "tenant",
                "service",
                "release",
                "trace_id"
            ]
            .contains(&name.as_str())));
        }
    }
    assert_eq!(handle.snapshot().dropped_invalid_record, 0);
    runtime.shutdown().await.unwrap();
}

#[tokio::test]
async fn default_guest_export_drops_unknown_names_and_hides_bodies() {
    let (observer, sink, handle, runtime) = setup(
        SharedActivationObserverConfig::default(),
        TelemetryPipelineConfig::default(),
    );
    let context = context(1);
    observer.on_observation(&context, &event(ActivationObservationKind::Received));
    let fields = Metadata::from([
        ("secret-key-name".to_owned(), "secret-value".to_owned()),
        ("LATENT.activation_id".to_owned(), "forged-id".to_owned()),
        ("activation_id".to_owned(), "forged-other".to_owned()),
    ]);
    observer
        .on_guest_log(GuestLogRecord {
            activation_id: &context.activation_id,
            severity: LogSeverity::Info,
            body: "raw-payload-sentinel",
            fields: &fields,
            observed_at_unix_millis: 1001,
        })
        .unwrap();
    handle.flush().await.unwrap();
    let rendered = format!("{:?}", sink.records());
    for sentinel in [
        "secret-key-name",
        "secret-value",
        "forged-id",
        "forged-other",
        "raw-payload-sentinel",
    ] {
        assert!(!rendered.contains(sentinel));
    }
    let records = sink.records();
    let guest = records
        .iter()
        .find_map(|record| match record {
            TelemetryRecord::Log(log) if log.body == "[REDACTED]" => Some(log),
            _ => None,
        })
        .unwrap();
    assert_eq!(guest.attributes["activation_id"], "activation");
    assert!(guest.trace.as_ref().unwrap().baggage.is_empty());
    runtime.shutdown().await.unwrap();
}

#[tokio::test]
async fn allowlisted_guest_fields_are_bounded_and_sensitive_values_redacted() {
    let (observer, sink, handle, runtime) = setup(
        SharedActivationObserverConfig {
            export_guest_log_bodies: true,
            allowed_guest_field_names: vec!["status".to_owned(), "detail".to_owned()],
            maximum_field_value_bytes: 16,
            ..Default::default()
        },
        TelemetryPipelineConfig::default(),
    );
    let context = context(1);
    observer.on_observation(&context, &event(ActivationObservationKind::Received));
    let fields = Metadata::from([
        ("status".to_owned(), "abcdefghijklmnopqrstuvwxyz".to_owned()),
        ("detail".to_owned(), "Bearer credential-value".to_owned()),
    ]);
    observer
        .on_guest_log(GuestLogRecord {
            activation_id: &context.activation_id,
            severity: LogSeverity::Warn,
            body: "healthy",
            fields: &fields,
            observed_at_unix_millis: 1001,
        })
        .unwrap();
    handle.flush().await.unwrap();
    let records = sink.records();
    let guest = records
        .iter()
        .find_map(|record| match record {
            TelemetryRecord::Log(log) if log.body == "healthy" => Some(log),
            _ => None,
        })
        .unwrap();
    assert_eq!(guest.attributes["guest.status"], "abcdefghijklmnop");
    assert_eq!(guest.attributes["guest.detail"], "[REDACTED]");
    runtime.shutdown().await.unwrap();
}

#[tokio::test]
async fn oversized_borrowed_context_is_rejected_before_retention() {
    let (observer, _, _, runtime) = setup(
        SharedActivationObserverConfig {
            maximum_correlation_value_bytes: 32,
            ..Default::default()
        },
        TelemetryPipelineConfig::default(),
    );
    let mut context = context(1);
    context.service.0 = "s".repeat(33);
    observer.on_observation(&context, &event(ActivationObservationKind::Received));
    assert_eq!(observer.snapshot().active_correlations, 0);
    assert_eq!(observer.snapshot().invalid_records, 1);
    runtime.shutdown().await.unwrap();
}

#[tokio::test]
async fn full_queue_drops_export_but_terminal_always_releases_correlation() {
    // On the current-thread runtime, the worker cannot drain until we yield.
    let (observer, _, handle, runtime) = setup(
        SharedActivationObserverConfig::default(),
        TelemetryPipelineConfig {
            queue_capacity: 1,
            ..Default::default()
        },
    );
    let context = context(1);
    observer.on_observation(&context, &event(ActivationObservationKind::Received));
    observer
        .on_guest_log(GuestLogRecord {
            activation_id: &context.activation_id,
            severity: LogSeverity::Info,
            body: "dropped",
            fields: &Metadata::new(),
            observed_at_unix_millis: 1001,
        })
        .unwrap();
    observer.on_observation(
        &context,
        &event(terminal(ActivationOutcomeClass::GuestSuccess)),
    );
    assert_eq!(observer.snapshot().active_correlations, 0);
    assert_eq!(observer.snapshot().completed, 1);
    assert!(observer.snapshot().observations_dropped > 0);
    assert!(handle.snapshot().dropped_queue_full > 0);
    runtime.shutdown().await.unwrap();
}

#[tokio::test]
async fn queue_wait_uses_monotonic_phase_boundaries() {
    let (observer, sink, handle, runtime) = setup(
        SharedActivationObserverConfig::default(),
        TelemetryPipelineConfig::default(),
    );
    let context = context(1);
    observer.on_observation(&context, &event(ActivationObservationKind::Received));
    for (phase, sequence, elapsed) in [
        (ActivationPhase::Queued, 4, 2),
        (ActivationPhase::Materializing, 5, 7),
    ] {
        observer.on_observation(
            &context,
            &ActivationObservation {
                occurred_at_unix_millis: 500,
                elapsed: Duration::from_millis(elapsed),
                kind: ActivationObservationKind::Phase { phase, sequence },
            },
        );
    }
    handle.flush().await.unwrap();
    assert!(sink.records().iter().any(|record| matches!(record, TelemetryRecord::Metric(metric)
        if metric.name == "latent.scheduler.queue.wait" && (metric.value - 5000.0).abs() < f64::EPSILON)));
    runtime.shutdown().await.unwrap();
}

#[tokio::test]
async fn strict_guest_submission_error_does_not_prevent_terminal_removal() {
    let (observer, _, _, runtime) = setup(
        SharedActivationObserverConfig::default(),
        TelemetryPipelineConfig {
            queue_capacity: 1,
            fail_on_drop: true,
            ..TelemetryPipelineConfig::default()
        },
    );
    let context = context(1);
    observer.on_observation(&context, &event(ActivationObservationKind::Received));
    assert!(observer
        .on_guest_log(GuestLogRecord {
            activation_id: &context.activation_id,
            severity: LogSeverity::Info,
            body: "dropped",
            fields: &Metadata::new(),
            observed_at_unix_millis: 1001
        })
        .is_err());
    observer.on_observation(
        &context,
        &event(terminal(ActivationOutcomeClass::GuestSuccess)),
    );
    assert_eq!(observer.snapshot().active_correlations, 0);
    assert!(observer.snapshot().submission_errors > 0);
    runtime.shutdown().await.unwrap();
}

#[tokio::test]
async fn overlapping_incarnations_coexist_and_ambiguous_guest_logs_are_dropped() {
    let (observer, _, handle, runtime) = setup(
        SharedActivationObserverConfig::default(),
        TelemetryPipelineConfig::default(),
    );
    let first = context(1);
    let mut second = context(2);
    second.token.manager = 2;
    observer.on_observation(&first, &event(ActivationObservationKind::Received));
    observer.on_observation(&second, &event(ActivationObservationKind::Received));
    assert_eq!(observer.snapshot().active_correlations, 2);
    assert_eq!(observer.snapshot().received, 2);
    assert!(observer.correlation(&first.activation_id).is_none());
    let log = GuestLogRecord {
        activation_id: &first.activation_id,
        severity: LogSeverity::Info,
        body: "ambiguous",
        fields: &Metadata::new(),
        observed_at_unix_millis: 1001,
    };
    observer.on_guest_log(log).unwrap();
    assert_eq!(observer.snapshot().guest_logs, 0);
    assert_eq!(observer.snapshot().unknown_correlations, 1);
    observer.on_observation(
        &first,
        &event(terminal(ActivationOutcomeClass::GuestSuccess)),
    );
    assert_eq!(observer.snapshot().active_correlations, 1);
    assert_eq!(
        observer.correlation(&second.activation_id).unwrap().token,
        second.token
    );
    observer.on_guest_log(log).unwrap();
    assert_eq!(observer.snapshot().guest_logs, 1);
    observer.on_observation(
        &first,
        &event(terminal(ActivationOutcomeClass::PlatformFailure)),
    );
    assert_eq!(observer.snapshot().active_correlations, 1);
    observer.on_observation(
        &second,
        &event(terminal(ActivationOutcomeClass::GuestDomainError)),
    );
    assert_eq!(observer.snapshot().active_correlations, 0);
    assert_eq!(observer.snapshot().completed, 2);
    handle.flush().await.unwrap();
    assert_eq!(handle.snapshot().dropped_invalid_record, 0);
    runtime.shutdown().await.unwrap();
}

#[tokio::test]
async fn retained_allowlist_capacities_and_index_arithmetic_are_bounded() {
    let (_, _, handle, runtime) = setup(
        SharedActivationObserverConfig::default(),
        TelemetryPipelineConfig::default(),
    );
    let mut oversized_slots = Vec::with_capacity(33);
    oversized_slots.push("status".to_owned());
    let mut oversized_name = String::with_capacity(65);
    oversized_name.push_str("status");
    for names in [oversized_slots, vec![oversized_name]] {
        let config = SharedActivationObserverConfig {
            allowed_guest_field_names: names,
            ..SharedActivationObserverConfig::default()
        };
        assert!(SharedActivationObserver::new(handle.clone(), config).is_err());
    }
    let config = SharedActivationObserverConfig {
        maximum_active_correlations: usize::MAX / 4096,
        maximum_context_bytes: 1,
        ..SharedActivationObserverConfig::default()
    };
    assert!(SharedActivationObserver::new(handle, config).is_err());
    runtime.shutdown().await.unwrap();
}

#[tokio::test]
async fn refreshed_context_does_not_retain_previous_string_capacities() {
    let (observer, _, _, runtime) = setup(
        SharedActivationObserverConfig {
            maximum_context_bytes: 160,
            maximum_correlation_value_bytes: 100,
            ..SharedActivationObserverConfig::default()
        },
        TelemetryPipelineConfig::default(),
    );
    let mut context = context(1);
    context.service.0 = "s".repeat(90);
    observer.on_observation(&context, &event(ActivationObservationKind::Received));
    context.service.0 = "s".to_owned();
    context.contract.0 = "c".repeat(90);
    observer.on_observation(
        &context,
        &event(ActivationObservationKind::Phase {
            phase: ActivationPhase::Resolved,
            sequence: 2,
        }),
    );
    {
        let state = observer.lock();
        let retained = &state.entries[&context.token].context;
        assert_eq!(retained.service.0.capacity(), retained.service.0.len());
        assert_eq!(retained.contract.0.capacity(), retained.contract.0.len());
    }
    runtime.shutdown().await.unwrap();
}
