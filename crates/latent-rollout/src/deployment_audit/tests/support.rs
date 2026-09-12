use super::*;
use latent_artifacts::ReleaseAuditAck;
use latent_audit::{
    AuditHandle, AuditLimits, AuditStoredRecord, AuditWorker, DirectoryPhase2AuditJournal,
};
use latent_control_store::{
    deployment_operations::{DeploymentOperationCommit, DeploymentOperationContext},
    DirectoryDeploymentRepository,
};
use std::{
    sync::Arc,
    time::{Duration, Instant},
};

pub(super) fn expires() -> Instant {
    Instant::now() + Duration::from_secs(5)
}
pub(super) fn runtime() -> tokio::runtime::Runtime {
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap()
}
pub(super) fn context(operation: &str, version: u64) -> DeploymentOperationContext {
    let rollout = releases::context(operation, 0);
    DeploymentOperationContext {
        tenant: rollout.tenant,
        actor: rollout.actor,
        operation_id: operation.into(),
        expected_state_version: version,
    }
}
pub(super) fn apply(operation: &str, version: u64) -> DeploymentOperationRequest {
    let latent_control_store::rollouts::RolloutRequest::Start { spec, .. } = releases::start()
    else {
        unreachable!()
    };
    DeploymentOperationRequest::Apply {
        context: context(operation, version),
        manifest: spec.candidate,
        expected_generation: 0,
    }
}
pub(super) struct Fixture {
    pub repository: Arc<DirectoryDeploymentRepository>,
    pub audit: AuditHandle,
    pub root: tempfile::TempDir,
    worker: AuditWorker,
}
impl Fixture {
    pub async fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let repository = releases::repository(&root.path().join("catalog")).await;
        let (audit, worker) =
            DirectoryPhase2AuditJournal::open(root.path().join("audit"), AuditLimits::default())
                .unwrap();
        Self {
            repository,
            audit,
            root,
            worker,
        }
    }
    pub async fn execute(
        &self,
        request: DeploymentOperationRequest,
    ) -> (DeploymentOperationCommit, ReleaseAuditAck) {
        let prepared = self.repository.prepare_operation(request).await.unwrap();
        let mut guard = ManagedDeploymentAudit::begin(
            &self.audit,
            prepared.preview(),
            prepared.replayed(),
            expires(),
        )
        .await
        .unwrap();
        let actual = guard
            .commit(self.repository.as_ref(), prepared, expires())
            .unwrap();
        assert!(guard.matches(actual.value()));
        let ack = guard
            .finish(self.repository.as_ref(), Some(actual.value()), expires())
            .await;
        let (value, lease) = actual.into_parts();
        drop(lease);
        (value, ack)
    }
    pub async fn rows_after_terminal(&self) -> Vec<AuditStoredRecord> {
        let deadline = expires();
        while self.audit.snapshot().pending_attempts != 0 {
            assert!(Instant::now() < deadline);
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
        let ticket = loop {
            match self.audit.query(
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
                    tokio::task::yield_now().await
                }
                Err(error) => panic!("bounded query failed: {error:?}"),
            }
        };
        ticket.wait().await.unwrap().records().to_vec()
    }
    pub fn shutdown(&mut self) {
        self.audit.close();
        assert!(self.worker.join_until(expires()).unwrap());
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        self.audit.close();
    }
}
