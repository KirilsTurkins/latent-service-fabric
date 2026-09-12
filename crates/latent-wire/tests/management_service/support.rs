#[path = "support/inventory.rs"]
mod inventory;
#[path = "support/model.rs"]
mod model;
#[path = "support/transport.rs"]
mod transport;

use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use latent_artifacts::{
    ArtifactRepository, DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig,
};
use latent_control_store::{DirectoryDeploymentRepository, DirectoryDeploymentRepositoryConfig};
use latent_core::SystemActivationClock;
use latent_wire::invocation::LocalPrincipalPolicy;
use latent_wire::management::{
    proto, LocalManagementPolicy, ManagementLimits, ManagementServiceAdapter, ManagementServices,
};
use tonic::transport::Channel;

pub(super) use inventory::Inventory;
pub(super) use model::{artifact, deployment};
pub(super) use transport::request;

pub(super) struct Harness {
    pub artifacts: Arc<DirectoryArtifactRepository>,
    pub deployments: Arc<DirectoryDeploymentRepository>,
    pub inventory: Arc<Inventory>,
    pub channel: Channel,
    server: transport::Server,
    rollout_worker: Option<latent_rollout::RolloutWorker>,
    _root: TempRoot,
}

impl Harness {
    pub async fn new(limits: ManagementLimits) -> Self {
        Self::with_artifacts(limits, None).await
    }

    pub async fn with_artifacts(
        limits: ManagementLimits,
        source: Option<Arc<dyn ArtifactRepository>>,
    ) -> Self {
        Self::with_audit(limits, source, None).await
    }

    pub async fn with_audit(
        limits: ManagementLimits,
        source: Option<Arc<dyn ArtifactRepository>>,
        audit: Option<latent_audit::AuditHandle>,
    ) -> Self {
        Self::open(limits, source, audit, false, None).await
    }

    pub async fn with_rollouts(limits: ManagementLimits, audit: latent_audit::AuditHandle) -> Self {
        Self::open(limits, None, Some(audit), true, None).await
    }

    pub async fn with_canary(
        limits: ManagementLimits,
        audit: latent_audit::AuditHandle,
        hub: latent_telemetry::BoundedPhase2CanaryOutcomeWindow,
    ) -> Self {
        Self::open(limits, None, Some(audit), true, Some(hub)).await
    }

    async fn open(
        limits: ManagementLimits,
        source: Option<Arc<dyn ArtifactRepository>>,
        audit: Option<latent_audit::AuditHandle>,
        enabled: bool,
        canary: Option<latent_telemetry::BoundedPhase2CanaryOutcomeWindow>,
    ) -> Self {
        let root = TempRoot::new();
        let artifacts = Arc::new(
            DirectoryArtifactRepository::open(
                root.0.join("releases"),
                DirectoryArtifactRepositoryConfig::default(),
            )
            .unwrap(),
        );
        let deployments = DirectoryDeploymentRepository::open(
            root.0.join("deployments"),
            artifacts.clone(),
            DirectoryDeploymentRepositoryConfig::default(),
        )
        .await
        .unwrap();
        let deployments = Arc::new(match canary {
            Some(hub) => deployments.with_canary(hub).unwrap(),
            None => deployments,
        });
        let (rollouts, rollout_worker) = if enabled {
            let (handle, mut worker) = latent_rollout::RolloutCoordinator::start(
                deployments.clone(),
                audit.clone().unwrap(),
                latent_rollout::CoordinatorLimits::default(),
                &tokio::runtime::Handle::current(),
            )
            .unwrap();
            worker
                .wait_started(std::time::Instant::now() + std::time::Duration::from_secs(5))
                .await
                .unwrap();
            (Some(handle), Some(worker))
        } else {
            (None, None)
        };
        let inventory = Arc::new(Inventory::new());
        let services = ManagementServices {
            rollouts,
            audit,
            artifacts: source.unwrap_or_else(|| artifacts.clone()),
            deployments: deployments.clone(),
            routes: deployments.clone(),
            inventory: inventory.clone(),
            principals: Arc::new(LocalPrincipalPolicy),
            authorization: Arc::new(LocalManagementPolicy),
            clock: Arc::new(SystemActivationClock),
        };
        let adapter = ManagementServiceAdapter::new(services, limits).unwrap();
        let (channel, server) = transport::Server::start(adapter).await;
        Self {
            artifacts,
            deployments,
            inventory,
            channel,
            server,
            rollout_worker,
            _root: root,
        }
    }

    pub fn deployments_client(
        &self,
    ) -> proto::deployment_service_client::DeploymentServiceClient<Channel> {
        proto::deployment_service_client::DeploymentServiceClient::new(self.channel.clone())
    }

    pub fn releases_client(&self) -> proto::release_service_client::ReleaseServiceClient<Channel> {
        proto::release_service_client::ReleaseServiceClient::new(self.channel.clone())
    }

    pub fn routes_client(&self) -> proto::route_service_client::RouteServiceClient<Channel> {
        proto::route_service_client::RouteServiceClient::new(self.channel.clone())
    }

    pub fn nodes_client(&self) -> proto::node_service_client::NodeServiceClient<Channel> {
        proto::node_service_client::NodeServiceClient::new(self.channel.clone())
    }

    pub async fn shutdown(mut self) {
        self.server.shutdown().await;
        if let Some(worker) = &mut self.rollout_worker {
            assert!(worker
                .join_until(std::time::Instant::now() + std::time::Duration::from_secs(5))
                .await
                .unwrap());
        }
    }
}

struct TempRoot(PathBuf);

impl TempRoot {
    fn new() -> Self {
        static NEXT: AtomicUsize = AtomicUsize::new(0);
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let nonce = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "latent-management-{}-{nonce}-{serial}",
            std::process::id()
        ));
        std::fs::create_dir(&path).unwrap();
        Self(path)
    }
}

impl Drop for TempRoot {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
