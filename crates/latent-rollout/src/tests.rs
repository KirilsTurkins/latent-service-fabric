mod canary;
mod ownership;
mod reconciliation;
mod rollback;
mod support;

use super::*;
use latent_audit::{AuditLimits, DirectoryPhase2AuditJournal};
use std::{
    sync::Arc,
    time::{Duration, Instant},
};

fn expires() -> Instant {
    Instant::now() + Duration::from_secs(5)
}
fn runtime() -> tokio::runtime::Runtime {
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .max_blocking_threads(1)
        .build()
        .unwrap()
}
struct Fixture {
    worker: RolloutWorker,
    handle: RolloutHandle,
    audit_worker: latent_audit::AuditWorker,
    audit: latent_audit::AuditHandle,
    repository: Arc<latent_control_store::DirectoryDeploymentRepository>,
    root: tempfile::TempDir,
}
impl Fixture {
    async fn new(limits: CoordinatorLimits) -> Self {
        let root = tempfile::tempdir().unwrap();
        let repository = support::repository(&root.path().join("catalog")).await;
        let (audit, audit_worker) =
            DirectoryPhase2AuditJournal::open(root.path().join("audit"), AuditLimits::default())
                .unwrap();
        let (handle, mut worker) = RolloutCoordinator::start(
            Arc::clone(&repository),
            audit.clone(),
            limits,
            &tokio::runtime::Handle::current(),
        )
        .unwrap();
        worker.wait_started(expires()).await.unwrap();
        Self {
            worker,
            handle,
            audit_worker,
            audit,
            repository,
            root,
        }
    }
    async fn shutdown(&mut self) {
        assert!(self.worker.join_until(expires()).await.unwrap());
        self.audit.close();
        assert!(self.audit_worker.join_until(expires()).unwrap());
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        self.handle.close();
        self.audit.close();
    }
}

#[test]
fn typed_rollout_audit_binding_covers_revision_actor_and_exact_receipt() {
    let receipt = reconciliation::receipt();
    let attempt = audit::attempt(&receipt, false).unwrap();
    assert!(audit::matches(&attempt, &receipt));
    for changed in [
        {
            let mut r = receipt.clone();
            r.revision += 1;
            r
        },
        {
            let mut r = receipt.clone();
            r.actor.subject = "other".into();
            r
        },
        {
            let mut r = receipt.clone();
            r.step += 1;
            r
        },
        {
            let mut r = receipt.clone();
            r.state_version += 1;
            r
        },
        {
            let mut r = receipt.clone();
            r.completed_at_unix_millis += 1;
            r
        },
    ] {
        assert!(!audit::matches(&attempt, &changed));
    }
    assert_eq!(attempt.expected_generation, None);
    assert_eq!(attempt.expected_deployment_generation, None);
    assert_eq!(attempt.expected_rollout_revision, Some(0));
}

#[test]
fn minimum_page_allowance_covers_a_bounded_status_before_read() {
    assert!(CoordinatorLimits {
        maximum_page_bytes: 4095,
        ..CoordinatorLimits::default()
    }
    .validate()
    .is_err());
    let limits = CoordinatorLimits {
        maximum_page_bytes: 4096,
        maximum_total_page_bytes: 16384,
        ..CoordinatorLimits::default()
    }
    .validate()
    .unwrap();
    let pages = lease::PageBudget::new(limits);
    assert!(pages.reserve(4095).is_err());
    assert_eq!(pages.snapshot(), (0, 0));
    let retained = pages.reserve(4096).unwrap();
    assert_eq!(retained.reserved_bytes(), 16384);
    assert_eq!(pages.snapshot(), (1, 16384));
    drop(retained);
    assert_eq!(pages.snapshot(), (0, 0));
}
