use std::sync::atomic::Ordering;
use std::time::Duration;

use latent_activation::ActivationOutcome;
use latent_core::{CancelDisposition, RevisionId, RouteGeneration, ServiceId};
use latent_telemetry::{
    BoundedPhase2CanaryOutcomeWindow, CanaryCoverage, CanaryRevisionBinding, CanaryWindowIdentity,
    CanaryWindowSpec, Phase2CanaryOutcomeWindowConfig,
};

use super::backend::{DECLARED, SUCCESS, TRAP};
use super::model::{artifact, request};
use super::support::{finish, pending, tenant, Harness};

fn spec() -> CanaryWindowSpec {
    CanaryWindowSpec {
        identity: CanaryWindowIdentity {
            tenant: tenant(),
            service: ServiceId("echo".into()),
            deployment: "test-deployment".into(),
            rollout_id: "test-rollout".into(),
            step: 1,
            generation: RouteGeneration(1),
        },
        revisions: (0..2)
            .map(|bucket| CanaryRevisionBinding {
                revision: RevisionId(format!("revision-1-{bucket}")),
                component: artifact(1, bucket).descriptor.release_digest,
                package: None,
            })
            .collect(),
        duration: Duration::from_mins(1),
    }
}

#[tokio::test]
async fn canary_only_uses_final_selected_revision_and_preserves_accounting() {
    let outcomes =
        BoundedPhase2CanaryOutcomeWindow::new(Phase2CanaryOutcomeWindowConfig::default()).unwrap();
    let input = spec();
    let window = outcomes.register(&input).unwrap();
    let harness = Harness::with_canary(outcomes.capture_handle());
    harness.artifacts.gate.close();
    let mut handle = Box::pin(harness.manager.start(request("canary-pinned")).unwrap());
    pending(handle.as_mut()).await;
    window.close().unwrap();
    assert_eq!(
        window.snapshot(1).unwrap().coverage(),
        CanaryCoverage::Draining
    );
    harness.catalog.generation.store(2, Ordering::Release);
    harness.clock.advance(Duration::from_millis(7));
    harness.artifacts.gate.open();
    let receipt = finish(handle).await;
    let ActivationOutcome::Succeeded(success) = receipt.outcome else {
        panic!("success")
    };
    assert_eq!(success.consumption.cpu_fuel, 3);
    assert_eq!(
        harness.status("canary-pinned").final_consumption,
        Some(success.consumption)
    );
    let snapshot = window.snapshot(1).unwrap();
    assert_eq!(snapshot.coverage(), CanaryCoverage::CompleteData);
    assert_eq!(snapshot.identity().generation, RouteGeneration(1));
    let selected = receipt.resolved_revision.unwrap();
    let index = snapshot
        .revisions()
        .iter()
        .position(|binding| binding.revision == selected.revision)
        .unwrap();
    assert_eq!(snapshot.revisions()[index].component, selected.release);
    assert_eq!(snapshot.revision_outcomes()[index].outcomes.success, 1);
    assert_eq!(snapshot.revision_outcomes()[index].latency_buckets[3], 1);
    assert_eq!(harness.manager.observation_snapshot().attempted, 0);
    assert_eq!(outcomes.snapshot().unwrap().live_samples, 0);
    harness.assert_idle();
}

#[tokio::test]
async fn canary_terminal_counts_success_domain_failure_and_accepted_cancellation_once() {
    let outcomes =
        BoundedPhase2CanaryOutcomeWindow::new(Phase2CanaryOutcomeWindowConfig::default()).unwrap();
    let window = outcomes.register(&spec()).unwrap();
    let harness = Harness::with_canary(outcomes.capture_handle());
    for (mode, id) in [
        (SUCCESS, "canary-success"),
        (DECLARED, "canary-domain"),
        (TRAP, "canary-trap"),
    ] {
        harness.backend.mode.store(mode, Ordering::Release);
        finish(harness.manager.start(request(id)).unwrap()).await;
    }
    harness.backend.mode.store(SUCCESS, Ordering::Release);
    harness.backend.gate.close();
    let mut handle = Box::pin(harness.manager.start(request("canary-cancel")).unwrap());
    pending(handle.as_mut()).await;
    assert_eq!(
        harness
            .manager
            .cancel_for(&tenant(), handle.activation_id(), "private-reason")
            .unwrap(),
        CancelDisposition::Accepted
    );
    drop(handle);
    window.close().unwrap();
    let snapshot = window.snapshot(4).unwrap();
    assert_eq!(snapshot.coverage(), CanaryCoverage::CompleteData);
    assert_eq!(
        (
            snapshot.starts(),
            snapshot.admitted(),
            snapshot.terminal(),
            snapshot.live()
        ),
        (4, 4, 4, 0)
    );
    let counts = snapshot.revision_outcomes();
    assert_eq!(
        counts.iter().map(|row| row.outcomes.success).sum::<u64>(),
        1
    );
    assert_eq!(
        counts
            .iter()
            .map(|row| row.outcomes.domain_error)
            .sum::<u64>(),
        1
    );
    assert_eq!(
        counts
            .iter()
            .map(|row| row.outcomes.platform_error)
            .sum::<u64>(),
        1
    );
    assert_eq!(
        counts.iter().map(|row| row.outcomes.cancelled).sum::<u64>(),
        1
    );
    harness.assert_idle();
}

#[tokio::test]
async fn accepted_but_unresolved_abandonment_is_not_healthy_missing_data() {
    let outcomes =
        BoundedPhase2CanaryOutcomeWindow::new(Phase2CanaryOutcomeWindowConfig::default()).unwrap();
    let window = outcomes.register(&spec()).unwrap();
    let harness = Harness::with_canary(outcomes.capture_handle());
    let handle = harness.manager.start(request("canary-abandoned")).unwrap();
    assert_eq!(outcomes.snapshot().unwrap().live_samples, 1);
    drop(handle);
    window.close().unwrap();
    let snapshot = window.snapshot(1).unwrap();
    assert_eq!(snapshot.coverage(), CanaryCoverage::Incomplete);
    assert_eq!(
        (
            snapshot.starts(),
            snapshot.selected(),
            snapshot.unattributed(),
            snapshot.live()
        ),
        (1, 0, 1, 0)
    );
    harness.assert_idle();
}
