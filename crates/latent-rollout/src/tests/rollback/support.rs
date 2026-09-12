use super::super::*;
use latent_control_store::rollouts::{RolloutCommand, RolloutId, RolloutRequest};
use latent_core::{RouteGeneration, TenantId};
use std::sync::atomic::AtomicU8;

pub(super) async fn fixture(canary: bool) -> (Fixture, Arc<AtomicU8>) {
    let root = tempfile::tempdir().unwrap();
    let gate = Arc::new(AtomicU8::new(0));
    let repository =
        super::super::support::repository_with_gate(&root.path().join("catalog"), gate.clone())
            .await;
    let repository = if canary {
        let Ok(repository) = Arc::try_unwrap(repository) else {
            panic!("exclusive fixture catalog")
        };
        Arc::new(
            repository
                .with_canary(
                    latent_telemetry::BoundedPhase2CanaryOutcomeWindow::new(
                        latent_telemetry::Phase2CanaryOutcomeWindowConfig::default(),
                    )
                    .unwrap(),
                )
                .unwrap(),
        )
    } else {
        repository
    };
    let (audit, audit_worker) =
        DirectoryPhase2AuditJournal::open(root.path().join("audit"), AuditLimits::default())
            .unwrap();
    let (handle, mut worker) = RolloutCoordinator::start(
        repository.clone(),
        audit.clone(),
        CoordinatorLimits::default(),
        &tokio::runtime::Handle::current(),
    )
    .unwrap();
    worker.wait_started(expires()).await.unwrap();
    (
        Fixture {
            worker,
            handle,
            audit_worker,
            audit,
            repository,
            root,
        },
        gate,
    )
}
pub(super) fn request(operation: &str, revision: u64, target: u64) -> RolloutRequest {
    RolloutRequest::Change {
        context: super::super::support::context(operation, revision),
        id: RolloutId("rollout".into()),
        command: RolloutCommand::Rollback {
            target_generation: RouteGeneration(target),
        },
    }
}
pub(super) async fn rows(fixture: &Fixture) -> Vec<latent_audit::AuditStoredRecord> {
    let deadline = expires();
    let ticket = loop {
        match fixture.audit.query(
            latent_audit::AuditQueryRequest {
                scope: latent_audit::AuditScope::Tenant(TenantId("alice".into())),
                filter: latent_audit::AuditFilter::default(),
                cursor: None,
                limit: 32,
                maximum_bytes: 32768,
            },
            deadline,
        ) {
            Ok(ticket) => break ticket,
            Err(error) if error.message == "audit-busy" && Instant::now() < deadline => {
                tokio::task::yield_now().await;
            }
            Err(error) => panic!("bounded audit query failed: {error:?}"),
        }
    };
    let page = ticket.wait().await.unwrap();
    page.records().to_vec()
}
pub(super) async fn start(fixture: &Fixture, canary: bool) {
    let mut request = super::super::support::start();
    if canary {
        let RolloutRequest::Start { spec, .. } = &mut request else {
            unreachable!()
        };
        spec.canary_policy = Some(latent_control_store::rollouts::RolloutCanaryPolicy {
            format_version: 1,
            observation_millis: 60_000,
            minimum_candidate_samples: 2,
            maximum_failure_basis_points: 0,
            latency_threshold_micros: 100,
            maximum_slow_basis_points: 0,
        });
    }
    drop(
        fixture
            .handle
            .submit(request, expires(), |_| Ok(()))
            .unwrap()
            .wait()
            .await
            .unwrap(),
    );
}
