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
        let root = TempRoot::new();
        let artifacts = Arc::new(
            DirectoryArtifactRepository::open(
                root.0.join("releases"),
                DirectoryArtifactRepositoryConfig::default(),
            )
            .unwrap(),
        );
        let deployments = Arc::new(
            DirectoryDeploymentRepository::open(
                root.0.join("deployments"),
                artifacts.clone(),
                DirectoryDeploymentRepositoryConfig::default(),
            )
            .await
            .unwrap(),
        );
        let inventory = Arc::new(Inventory::new());
        let services = ManagementServices {
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

    pub async fn shutdown(self) {
        self.server.shutdown().await;
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
