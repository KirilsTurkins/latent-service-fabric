//! Control-plane persistence interfaces for desired state and compiled route state.

#![forbid(unsafe_code)]

mod embedded;

pub use embedded::{EmbeddedCatalogOptions, EmbeddedDeploymentCatalog, ROUTE_ANNOTATION_KEY};

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

pub trait DeploymentStore: Send + Sync {
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

/// Additive tenant-filtered deployment listing for bounded standalone management callers.
pub trait TenantDeploymentStore: DeploymentStore {
    fn list_for_tenant<'a>(
        &'a self,
        tenant: &'a TenantId,
    ) -> BoxFuture<'a, Result<Vec<DeploymentManifest>, PlatformError>>;
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
