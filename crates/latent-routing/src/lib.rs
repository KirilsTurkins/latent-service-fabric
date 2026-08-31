//! Immutable route snapshots, binding resolution, and revision selection.

#![forbid(unsafe_code)]

use latent_core::{
    BindingId, BoxFuture, ContractId, FunctionId, Metadata, PlatformError, ReleaseDigest,
    RevisionId, RouteGeneration, RouteId, ServiceId, TenantId,
};
use latent_manifest::BindingMode;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InvocationTarget {
    pub tenant: TenantId,
    pub service: ServiceId,
    pub contract: ContractId,
    pub function: FunctionId,
    pub route: Option<String>,
}

/// The callable contract surface exposed by one routed revision.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RouteContract {
    pub contract: ContractId,
    pub functions: Vec<FunctionId>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RevisionRoute {
    pub revision: RevisionId,
    pub release: ReleaseDigest,
    pub weight: u16,
    pub contracts: Vec<RouteContract>,
    pub attributes: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ServiceRoute {
    pub id: RouteId,
    /// A service identifier is only unique inside this tenant scope.
    pub tenant: TenantId,
    pub service: ServiceId,
    /// `None` is the default route; named routes remain separately addressable.
    pub route: Option<String>,
    pub revisions: Vec<RevisionRoute>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BindingRoute {
    pub id: BindingId,
    pub consumer_tenant: TenantId,
    pub consumer_service: ServiceId,
    pub imported_contract: ContractId,
    pub provider_tenant: TenantId,
    pub provider_service: ServiceId,
    pub provider_contract: ContractId,
    pub mode: BindingMode,
    pub policy_digest: String,
}

/// A complete immutable local routing generation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RouteSnapshot {
    pub generation: RouteGeneration,
    pub generated_at_unix_millis: u64,
    /// BLAKE3 digest of the canonical snapshot contents, excluding this field.
    pub snapshot_digest: String,
    pub services: Vec<ServiceRoute>,
    pub bindings: Vec<BindingRoute>,
    pub policy_digests: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResolvedRevision {
    pub target: InvocationTarget,
    pub revision: RevisionId,
    pub release: ReleaseDigest,
    pub route_generation: RouteGeneration,
    pub attributes: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResolvedBinding {
    pub binding: BindingRoute,
    pub provider_revision: ResolvedRevision,
}

pub trait RouteResolver: Send + Sync {
    fn resolve(
        &self,
        target: &InvocationTarget,
        routing_key: Option<&str>,
    ) -> Result<ResolvedRevision, PlatformError>;

    fn resolve_binding(
        &self,
        consumer: &ResolvedRevision,
        imported_contract: &ContractId,
        routing_key: Option<&str>,
    ) -> Result<ResolvedBinding, PlatformError>;

    fn generation(&self) -> RouteGeneration;
}

pub trait RouteCompiler: Send + Sync {
    fn compile<'a>(
        &'a self,
        previous: Option<&'a RouteSnapshot>,
    ) -> BoxFuture<'a, Result<RouteSnapshot, PlatformError>>;
}

pub trait RouteSnapshotSource: Send + Sync {
    fn current<'a>(&'a self) -> BoxFuture<'a, Result<RouteSnapshot, PlatformError>>;

    /// Returns retained complete snapshots newer than `after`.
    ///
    /// Phase 1 implements this as a bounded local replay, not a cluster watch.
    fn watch<'a>(
        &'a self,
        after: RouteGeneration,
    ) -> BoxFuture<'a, Result<Vec<RouteSnapshot>, PlatformError>>;
}

pub trait RouteSnapshotPublisher: Send + Sync {
    fn publish<'a>(&'a self, snapshot: RouteSnapshot) -> BoxFuture<'a, Result<(), PlatformError>>;
}
