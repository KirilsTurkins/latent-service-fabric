use std::sync::atomic::Ordering;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use latent_activation::ActivationOutcome;
use latent_core::{ActivationId, ActivationPhase, ActivationTerminalState, CancelDisposition};
use latent_telemetry::{
    ActivationCleanupDisposition, ActivationObservation, ActivationObservationContext,
    ActivationObservationKind, ActivationObserver, ActivationOutcomeClass, LocalSinkConfig,
    SharedActivationObserver, SharedActivationObserverConfig, StructuredLocalSink,
    TelemetryPipelineConfig, TelemetryRuntime,
};

use super::backend::{DECLARED, DROP_PANIC, FUEL, PANIC, QUARANTINE, SUCCESS, TRAP, UNAVAILABLE};
use super::model::request;
use super::support::{finish, pending, tenant, Harness};

#[derive(Default)]
struct Collector(Mutex<Vec<(ActivationObservationContext, ActivationObservation)>>);
impl ActivationObserver for Collector {
    fn on_observation(
        &self,
        context: &ActivationObservationContext,
        event: &ActivationObservation,
    ) {
        self.0
            .lock()
            .unwrap()
            .push((context.clone(), event.clone()));
    }
}

#[tokio::test]
async fn observations_match_committed_outcomes_and_exclude_payloads_and_diagnostics() {
    for mode in [
        SUCCESS,
        DECLARED,
        TRAP,
        FUEL,
        UNAVAILABLE,
        QUARANTINE,
        PANIC,
        DROP_PANIC,
    ] {
        let observer = Arc::new(Collector::default());
        let harness = Harness::with_observer(2, 8, Some(observer.clone()));
        harness.backend.mode.store(mode, Ordering::Release);
        let mut input = request("observed");
        input.input = b"secret-input".to_vec();
        input
            .metadata
            .insert("secret-key".to_owned(), "secret-metadata".to_owned());
        input
            .principal
            .claims
            .insert("token".to_owned(), "secret-claim".to_owned());
        input
            .trace
            .baggage
            .insert("token".to_owned(), "secret-baggage".to_owned());
        let receipt = finish(harness.manager.start(input).unwrap()).await;
        let status = harness.status("observed");
        let events = observer.0.lock().unwrap();
        let (context, last) = events.last().unwrap();
        let ActivationObservationKind::Terminal(terminal) = &last.kind else {
            panic!("terminal last");
        };
        assert_eq!(Some(terminal.terminal_state), status.terminal_state);
        assert_eq!(
            Some(&terminal.consumption),
            status.final_consumption.as_ref()
        );
        assert_eq!(terminal.last_phase, status.phase);
        assert_eq!(
            terminal.sequence,
            harness
                .manager
                .events(&tenant(), &receipt.activation_id)
                .unwrap()
                .last()
                .unwrap()
                .sequence
        );
        assert_eq!(
            terminal.class,
            match receipt.outcome {
                ActivationOutcome::Succeeded(_) => ActivationOutcomeClass::GuestSuccess,
                ActivationOutcome::DeclaredError { .. } => ActivationOutcomeClass::GuestDomainError,
                ActivationOutcome::Failed { .. } => ActivationOutcomeClass::PlatformFailure,
            }
        );
        assert_eq!(
            context.release.as_ref(),
            receipt.resolved_revision.as_ref().map(|pin| &pin.release)
        );
        assert_eq!(
            events
                .iter()
                .filter(|(_, e)| matches!(e.kind, ActivationObservationKind::Terminal(_)))
                .count(),
            1
        );
        assert_eq!(
            events
                .iter()
                .filter(|(_, e)| matches!(e.kind, ActivationObservationKind::Cleanup(_)))
                .count(),
            1
        );
        let rendered = format!("{events:?}");
        for secret in [
            "secret-input",
            "secret-metadata",
            "secret-claim",
            "secret-baggage",
            "declared fixture error",
            "controlled unavailable",
            "controlled trap",
        ] {
            assert!(!rendered.contains(secret), "diagnostic leaked: {secret}");
        }
        drop(events);
        harness.assert_idle();
    }
}

#[tokio::test]
async fn resolved_context_grants_and_elapsed_time_follow_actual_lifecycle() {
    let observer = Arc::new(Collector::default());
    let harness = Harness::with_observer(1, 8, Some(observer.clone()));
    harness.artifacts.gate.close();
    let mut handle = Box::pin(
        harness
            .manager
            .start(request("pinned-observation"))
            .unwrap(),
    );
    pending(handle.as_mut()).await;
    harness.catalog.generation.store(2, Ordering::Release);
    harness.clock.advance(Duration::from_millis(7));
    harness.artifacts.gate.open();
    let receipt = finish(handle).await;
    let events = observer.0.lock().unwrap();
    let phases = events
        .iter()
        .filter_map(|(_, e)| match e.kind {
            ActivationObservationKind::Phase { phase, sequence } => Some((phase, sequence)),
            _ => None,
        })
        .collect::<Vec<_>>();
    assert_eq!(
        phases,
        vec![
            (ActivationPhase::Resolved, 2),
            (ActivationPhase::Admitted, 3),
            (ActivationPhase::Queued, 4),
            (ActivationPhase::Materializing, 5),
            (ActivationPhase::Running, 6)
        ]
    );
    let grant = events
        .iter()
        .find_map(|(_, e)| match &e.kind {
            ActivationObservationKind::AdmittedGrant(grant) => Some(grant),
            _ => None,
        })
        .unwrap();
    assert_eq!(grant, &harness.backend.requests.lock().unwrap()[0].budget);
    assert_eq!(events.last().unwrap().1.elapsed, Duration::from_millis(7));
    assert_eq!(
        events.last().unwrap().0.route_generation,
        receipt.resolved_revision.map(|pin| pin.route_generation)
    );
    assert!(events.iter().any(|(_, e)| matches!(
        e.kind,
        ActivationObservationKind::Cleanup(ActivationCleanupDisposition::Released)
    )));
    drop(events);
    harness.assert_idle();
}

#[tokio::test]
async fn abandoned_stages_and_accepted_cancellation_each_observe_one_terminal() {
    for stage in 0..4 {
        let observer = Arc::new(Collector::default());
        let harness = Harness::with_observer(1, 8, Some(observer.clone()));
        match stage {
            1 => harness.artifacts.gate.close(),
            2 => harness.backend.prepare_gate.close(),
            3 => harness.backend.gate.close(),
            _ => {}
        }
        let mut handle = Box::pin(
            harness
                .manager
                .start(request("abandoned-observation"))
                .unwrap(),
        );
        if stage != 0 {
            pending(handle.as_mut()).await;
        }
        assert_eq!(
            harness
                .manager
                .cancel_for(&tenant(), handle.activation_id(), "private-cancel-reason")
                .unwrap(),
            CancelDisposition::Accepted
        );
        drop(handle);
        let events = observer.0.lock().unwrap();
        let terminal = events
            .iter()
            .filter_map(|(_, e)| match &e.kind {
                ActivationObservationKind::Terminal(t) => Some(t),
                _ => None,
            })
            .collect::<Vec<_>>();
        assert_eq!(terminal.len(), 1);
        assert_eq!(
            terminal[0].terminal_state,
            ActivationTerminalState::Cancelled
        );
        assert_eq!(
            Some(&terminal[0].consumption),
            harness
                .status("abandoned-observation")
                .final_consumption
                .as_ref()
        );
        assert!(!format!("{events:?}").contains("private-cancel-reason"));
        drop(events);
        harness.assert_idle();
    }
}

struct Panics;
impl ActivationObserver for Panics {
    fn on_observation(&self, _: &ActivationObservationContext, _: &ActivationObservation) {
        panic!("observer failure");
    }
}

#[tokio::test]
async fn observer_panics_and_closed_export_pipeline_preserve_success_and_cleanup() {
    let harness = Harness::with_observer(1, 8, Some(Arc::new(Panics)));
    let receipt = finish(harness.manager.start(request("panic-observer")).unwrap()).await;
    assert!(matches!(receipt.outcome, ActivationOutcome::Succeeded(_)));
    let counters = harness.manager.observation_snapshot();
    assert!(counters.attempted > 6);
    assert_eq!(counters.attempted, counters.observer_panics);
    harness.assert_idle();

    let sink = Arc::new(StructuredLocalSink::new(LocalSinkConfig::default()).unwrap());
    let (pipeline, runtime) =
        TelemetryRuntime::spawn(TelemetryPipelineConfig::default(), sink).unwrap();
    let observer = Arc::new(
        SharedActivationObserver::new(pipeline.clone(), SharedActivationObserverConfig::default())
            .unwrap(),
    );
    drop(runtime);
    let harness = Harness::with_observer(1, 8, Some(observer.clone()));
    assert!(matches!(
        finish(harness.manager.start(request("closed-pipeline")).unwrap())
            .await
            .outcome,
        ActivationOutcome::Succeeded(_)
    ));
    assert_eq!(observer.snapshot().active_correlations, 0);
    assert_eq!(observer.snapshot().completed, 1);
    assert!(pipeline.snapshot().dropped_queue_closed > 0);
    harness.assert_idle();
}

#[tokio::test]
async fn observation_incarnations_remain_unique_across_managers_and_id_reuse() {
    let observer = Arc::new(Collector::default());
    let first = Harness::with_observer(1, 1, Some(observer.clone()));
    let second = Harness::with_observer(1, 1, Some(observer.clone()));
    let a = first.manager.start(request("same-id")).unwrap();
    let b = second.manager.start(request("same-id")).unwrap();
    drop(a);
    drop(b);
    drop(first.manager.start(request("evict-old")).unwrap());
    assert!(first
        .manager
        .status(&tenant(), &ActivationId("same-id".to_owned()))
        .unwrap()
        .is_none());
    drop(first.manager.start(request("same-id")).unwrap());
    let events = observer.0.lock().unwrap();
    let tokens = events
        .iter()
        .filter(|(c, e)| {
            c.activation_id.0 == "same-id" && matches!(e.kind, ActivationObservationKind::Received)
        })
        .map(|(c, _)| c.token)
        .collect::<std::collections::BTreeSet<_>>();
    assert_eq!(tokens.len(), 3);
    assert!(events
        .iter()
        .all(|(_, event)| !matches!(event.kind, ActivationObservationKind::Cancellation(_))));
    drop(events);
    first.assert_idle();
    second.assert_idle();
}
