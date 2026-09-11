//! Control-plane persistence interfaces and an embedded local deployment catalog.

#![forbid(unsafe_code)]

mod deployments;
mod scoped_routes;

pub use scoped_routes::{RouteReadLimits, ScopedRouteRequest, ScopedRouteSnapshot};

pub use deployments::{
    deployment_revision_id, DeploymentPage, DeploymentPageRequest, DirectoryDeploymentRepository,
    DirectoryDeploymentRepositoryConfig, PinnedRouteResolver,
};

#[cfg(feature = "catalog-observation")]
pub use deployments::{
    CatalogWorkCounts, CatalogWorkObserver, CatalogWorkOperation, CatalogWorkOutcome,
    CatalogWorkReceipt, CatalogWorkSnapshot,
};

use latent_artifacts::ArtifactDescriptor;
use latent_audit::AuditEvent;
use latent_core::{
    BindingId, BoxFuture, DeploymentId, NodeId, PlatformError, PolicyId, ReleaseDigest,
    RouteGeneration, ServiceId, TenantId, TriggerId,
};
use latent_manifest::{BindingManifest, DeploymentManifest, PolicyManifest, TriggerManifest};
use latent_node::{NodeDescriptor, NodeInventory};
use latent_policy::PolicyDecision;
use latent_routing::RouteSnapshot;

pub trait ReleaseCatalog: Send + Sync {
    fn put<'a>(
        &'a self,
        descriptor: ArtifactDescriptor,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn get<'a>(
        &'a self,
        digest: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<Option<ArtifactDescriptor>, PlatformError>>;

    fn list_for_service<'a>(
        &'a self,
        service: &'a ServiceId,
    ) -> BoxFuture<'a, Result<Vec<ArtifactDescriptor>, PlatformError>>;
}

/// Desired state and its last object mutation stamp, separate from content revision identity.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VersionedDeployment {
    pub manifest: DeploymentManifest,
    pub generation: u64,
}

/// The exact normalized record installed by an apply and its catalog publication generation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeploymentApplyReceipt {
    pub deployment: VersionedDeployment,
    pub catalog_generation: RouteGeneration,
}

/// The removed record's old stamp and the generation that published its deletion.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeploymentDeleteReceipt {
    pub deleted: VersionedDeployment,
    pub catalog_generation: RouteGeneration,
}

pub trait DeploymentStore: Send + Sync {
    /// Atomically checks the caller's object stamp and applies inside the explicit tenant.
    /// `None` is unconditional, zero requires absence, and a positive stamp requires equality.
    fn apply_versioned<'a>(
        &'a self,
        tenant: &'a TenantId,
        deployment: DeploymentManifest,
        expected_generation: Option<u64>,
    ) -> BoxFuture<'a, Result<DeploymentApplyReceipt, PlatformError>>;

    /// Returns only the requested tenant's record; adapters supply authenticated tenant scope.
    fn get_versioned<'a>(
        &'a self,
        tenant: &'a TenantId,
        id: &'a DeploymentId,
    ) -> BoxFuture<'a, Result<Option<VersionedDeployment>, PlatformError>>;

    fn list_page(
        &self,
        request: DeploymentPageRequest,
    ) -> BoxFuture<'_, Result<DeploymentPage, PlatformError>>;

    /// Checks the same precondition as apply, then requires a live record to delete.
    fn delete_versioned<'a>(
        &'a self,
        tenant: &'a TenantId,
        id: &'a DeploymentId,
        expected_generation: Option<u64>,
    ) -> BoxFuture<'a, Result<DeploymentDeleteReceipt, PlatformError>>;

    /// Trusted-local compatibility operation. Adapters should use explicit scoped methods.
    fn apply<'a>(
        &'a self,
        deployment: DeploymentManifest,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn get<'a>(
        &'a self,
        id: &'a DeploymentId,
    ) -> BoxFuture<'a, Result<Option<DeploymentManifest>, PlatformError>>;

    fn list<'a>(&'a self) -> BoxFuture<'a, Result<Vec<DeploymentManifest>, PlatformError>>;

    fn delete<'a>(&'a self, id: &'a DeploymentId) -> BoxFuture<'a, Result<(), PlatformError>>;
}

pub trait BindingStore: Send + Sync {
    fn apply<'a>(&'a self, binding: BindingManifest) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn get<'a>(
        &'a self,
        id: &'a BindingId,
    ) -> BoxFuture<'a, Result<Option<BindingManifest>, PlatformError>>;

    fn list<'a>(&'a self) -> BoxFuture<'a, Result<Vec<BindingManifest>, PlatformError>>;

    fn delete<'a>(&'a self, id: &'a BindingId) -> BoxFuture<'a, Result<(), PlatformError>>;
}

pub trait TriggerStore: Send + Sync {
    fn apply<'a>(&'a self, trigger: TriggerManifest) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn get<'a>(
        &'a self,
        id: &'a TriggerId,
    ) -> BoxFuture<'a, Result<Option<TriggerManifest>, PlatformError>>;

    fn list<'a>(&'a self) -> BoxFuture<'a, Result<Vec<TriggerManifest>, PlatformError>>;

    fn delete<'a>(&'a self, id: &'a TriggerId) -> BoxFuture<'a, Result<(), PlatformError>>;
}

pub trait ControlPolicyStore: Send + Sync {
    fn apply<'a>(&'a self, policy: PolicyManifest) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn get<'a>(
        &'a self,
        id: &'a PolicyId,
    ) -> BoxFuture<'a, Result<Option<PolicyManifest>, PlatformError>>;

    fn record_decision<'a>(
        &'a self,
        decision: PolicyDecision,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;
}

pub trait NodeInventoryStore: Send + Sync {
    fn register<'a>(
        &'a self,
        descriptor: NodeDescriptor,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn report<'a>(&'a self, inventory: NodeInventory) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn get<'a>(
        &'a self,
        id: &'a NodeId,
    ) -> BoxFuture<'a, Result<Option<NodeInventory>, PlatformError>>;
}

pub trait CompiledRouteStore: Send + Sync {
    /// Complete tenant-scoped read; implementations must bound selected data before cloning.
    fn scoped(
        &self,
        _request: ScopedRouteRequest,
    ) -> BoxFuture<'_, Result<ScopedRouteSnapshot, PlatformError>> {
        Box::pin(async {
            Err(PlatformError {
                code: latent_core::PlatformErrorCode::IncompatibleContract,
                message: "scoped-routes-unsupported".to_owned(),
                retryable: false,
                details: Vec::new(),
            })
        })
    }

    fn put<'a>(&'a self, snapshot: RouteSnapshot) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn current<'a>(&'a self) -> BoxFuture<'a, Result<RouteSnapshot, PlatformError>>;

    fn get<'a>(
        &'a self,
        generation: RouteGeneration,
    ) -> BoxFuture<'a, Result<Option<RouteSnapshot>, PlatformError>>;
}

pub trait ControlAuditStore: Send + Sync {
    fn append<'a>(&'a self, event: AuditEvent) -> BoxFuture<'a, Result<(), PlatformError>>;
}
