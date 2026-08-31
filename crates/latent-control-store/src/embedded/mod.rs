mod compiler;
mod model;
mod persistence;

#[cfg(test)]
mod fault_injection {
    use std::collections::BTreeSet;
    use std::path::{Path, PathBuf};
    use std::sync::{Mutex, OnceLock};

    #[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
    pub(super) enum FaultPoint {
        CommitDirectorySyncAfterMarkerRename,
        ReplacePublished,
    }

    static FAILURES: OnceLock<Mutex<BTreeSet<(PathBuf, FaultPoint)>>> = OnceLock::new();

    pub(super) fn fail_once(root: &Path, point: FaultPoint) {
        FAILURES
            .get_or_init(|| Mutex::new(BTreeSet::new()))
            .lock()
            .expect("fault-injection lock")
            .insert((root.to_path_buf(), point));
    }

    pub(super) fn take(root: &Path, point: FaultPoint) -> bool {
        FAILURES
            .get_or_init(|| Mutex::new(BTreeSet::new()))
            .lock()
            .expect("fault-injection lock")
            .remove(&(root.to_path_buf(), point))
    }
}

#[cfg(test)]
mod review_tests;
#[cfg(test)]
mod tests;

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::{Arc, RwLock};

use latent_artifacts::ArtifactRepository;
use latent_core::{
    BoxFuture, DeploymentId, ErrorDetail, Metadata, PlatformError, PlatformErrorCode,
    RouteGeneration, TenantId,
};
use latent_manifest::DeploymentManifest;
use latent_routing::{
    InvocationTarget, ResolvedBinding, ResolvedRevision, RouteCompiler, RouteResolver,
    RouteSnapshot, RouteSnapshotPublisher, RouteSnapshotSource,
};
use tokio::sync::Mutex;

use crate::{CompiledRouteStore, DeploymentStore, TenantDeploymentStore};
use compiler::{
    compile_deployments, empty_snapshot, ArtifactReleaseInspector, ReleaseInspector, RouteIndex,
};
use model::PersistedCatalogState;

/// Deployment annotation selecting a named route instead of the default route.
pub const ROUTE_ANNOTATION_KEY: &str = "latent.dev/route";

/// Explicit resource bounds for the standalone embedded catalog.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EmbeddedCatalogOptions {
    pub max_deployments: usize,
    pub max_state_file_bytes: u64,
    pub retained_generations: usize,
}

impl Default for EmbeddedCatalogOptions {
    fn default() -> Self {
        Self {
            max_deployments: 200_000,
            max_state_file_bytes: 256 * 1024 * 1024,
            retained_generations: 64,
        }
    }
}

struct PublishedState {
    deployments: Arc<BTreeMap<DeploymentId, DeploymentManifest>>,
    snapshot: Arc<RouteSnapshot>,
    index: Arc<RouteIndex>,
}

struct Inner {
    root: PathBuf,
    releases: Arc<dyn ReleaseInspector>,
    options: EmbeddedCatalogOptions,
    mutation: Mutex<()>,
    published: RwLock<Arc<PublishedState>>,
}

/// A process-local deployment repository and immutable route table backed by one directory.
///
/// Mutations serialize through one catalog mutex. Readers hold the `RwLock` only long enough
/// to clone an `Arc`, then resolve against an immutable generation without observing partial
/// state. No listener, worker, process, or other per-service runtime resource is created.
#[derive(Clone)]
pub struct EmbeddedDeploymentCatalog {
    inner: Arc<Inner>,
}

impl EmbeddedDeploymentCatalog {
    pub async fn open(
        root: impl AsRef<Path>,
        artifacts: Arc<dyn ArtifactRepository>,
    ) -> Result<Self, PlatformError> {
        Self::open_with_options(root, artifacts, EmbeddedCatalogOptions::default()).await
    }

    pub async fn open_with_options(
        root: impl AsRef<Path>,
        artifacts: Arc<dyn ArtifactRepository>,
        options: EmbeddedCatalogOptions,
    ) -> Result<Self, PlatformError> {
        let inspector: Arc<dyn ReleaseInspector> =
            Arc::new(ArtifactReleaseInspector::new(artifacts));
        Self::open_with_release_inspector(root, inspector, options).await
    }

    async fn open_with_release_inspector(
        root: impl AsRef<Path>,
        releases: Arc<dyn ReleaseInspector>,
        options: EmbeddedCatalogOptions,
    ) -> Result<Self, PlatformError> {
        validate_options(&options)?;
        let root = root.as_ref().to_path_buf();
        persistence::initialize(&root)?;

        let (deployments, snapshot) = match persistence::load_latest(&root, &options)? {
            Some(state) => state.into_domain()?,
            None => (BTreeMap::new(), empty_snapshot()),
        };
        if deployments.len() > options.max_deployments {
            return Err(platform_error(
                PlatformErrorCode::ResourceExhausted,
                "deployment-count-limit",
                "the restored embedded catalog exceeds its configured entry bound",
                stable_fields([
                    ("count", deployments.len().to_string()),
                    ("limit", options.max_deployments.to_string()),
                ]),
            ));
        }
        let snapshot = Arc::new(snapshot);
        let index = Arc::new(RouteIndex::build(Arc::clone(&snapshot))?);
        let published = Arc::new(PublishedState {
            deployments: Arc::new(deployments),
            snapshot,
            index,
        });

        Ok(Self {
            inner: Arc::new(Inner {
                root,
                releases,
                options,
                mutation: Mutex::new(()),
                published: RwLock::new(published),
            }),
        })
    }

    pub async fn apply_manifest(
        &self,
        deployment: DeploymentManifest,
    ) -> Result<RouteGeneration, PlatformError> {
        let _mutation = self.inner.mutation.lock().await;
        let current = self.published()?;
        let mut deployments = (*current.deployments).clone();

        if let Some(existing) = deployments.get(&deployment.id) {
            if existing == &deployment {
                return Err(platform_error(
                    PlatformErrorCode::AlreadyExists,
                    "duplicate-deployment-id",
                    "the deployment catalog already contains this exact deployment ID",
                    stable_fields([("deployment_id", deployment.id.0.clone())]),
                ));
            }
            if !same_route_identity(existing, &deployment) {
                return Err(platform_error(
                    PlatformErrorCode::StateConflict,
                    "deployment-identity-conflict",
                    "a deployment ID can only replace state within the same tenant, namespace, service, and route identity",
                    stable_fields([("deployment_id", deployment.id.0.clone())]),
                ));
            }
        }
        deployments.insert(deployment.id.clone(), deployment);
        self.commit_candidate(deployments, &current.snapshot).await
    }

    pub async fn delete_manifest(
        &self,
        id: &DeploymentId,
    ) -> Result<RouteGeneration, PlatformError> {
        let _mutation = self.inner.mutation.lock().await;
        let current = self.published()?;
        let mut deployments = (*current.deployments).clone();
        if deployments.remove(id).is_none() {
            return Err(platform_error(
                PlatformErrorCode::NotFound,
                "deployment-not-found",
                "the requested deployment is not present in the embedded catalog",
                stable_fields([("deployment_id", id.0.clone())]),
            ));
        }
        self.commit_candidate(deployments, &current.snapshot).await
    }

    pub fn deployment(
        &self,
        id: &DeploymentId,
    ) -> Result<Option<DeploymentManifest>, PlatformError> {
        Ok(self.published()?.deployments.get(id).cloned())
    }

    pub fn deployments(
        &self,
        tenant: Option<&TenantId>,
    ) -> Result<Vec<DeploymentManifest>, PlatformError> {
        Ok(self
            .published()?
            .deployments
            .values()
            .filter(|deployment| {
                tenant.is_none_or(|tenant| deployment.metadata.tenant.as_ref() == Some(tenant))
            })
            .cloned()
            .collect())
    }

    pub fn snapshot(&self) -> Result<RouteSnapshot, PlatformError> {
        Ok((*self.published()?.snapshot).clone())
    }

    pub fn generation(&self) -> Result<RouteGeneration, PlatformError> {
        Ok(self.published()?.snapshot.generation)
    }

    pub fn resolve_target(
        &self,
        target: &InvocationTarget,
        routing_key: Option<&str>,
    ) -> Result<ResolvedRevision, PlatformError> {
        self.published()?.index.resolve(target, routing_key)
    }

    pub fn resolve_target_binding(
        &self,
        consumer: &ResolvedRevision,
        imported_contract: &latent_core::ContractId,
        routing_key: Option<&str>,
    ) -> Result<ResolvedBinding, PlatformError> {
        self.published()?
            .index
            .resolve_binding(consumer, imported_contract, routing_key)
    }

    pub fn retained_snapshot(
        &self,
        generation: RouteGeneration,
    ) -> Result<Option<RouteSnapshot>, PlatformError> {
        let state =
            persistence::load_generation(&self.inner.root, generation, &self.inner.options)?;
        state
            .map(PersistedCatalogState::into_domain)
            .transpose()
            .and_then(|state| {
                state
                    .map(|(_, snapshot)| {
                        RouteIndex::build(Arc::new(snapshot.clone()))?;
                        Ok(snapshot)
                    })
                    .transpose()
            })
    }

    async fn commit_candidate(
        &self,
        deployments: BTreeMap<DeploymentId, DeploymentManifest>,
        previous: &RouteSnapshot,
    ) -> Result<RouteGeneration, PlatformError> {
        let snapshot = compile_deployments(
            &deployments,
            self.inner.releases.as_ref(),
            Some(previous),
            &self.inner.options,
        )
        .await?;
        let snapshot = Arc::new(snapshot);
        let index = Arc::new(RouteIndex::build(Arc::clone(&snapshot))?);
        let persisted = PersistedCatalogState::from_domain(&deployments, &snapshot);
        persistence::commit(&self.inner.root, persisted, &self.inner.options)?;

        let generation = snapshot.generation;
        self.publish_committed_state(Arc::new(PublishedState {
            deployments: Arc::new(deployments),
            snapshot,
            index,
        }));
        // Retention is maintenance after the complete generation became durable and visible.
        // A pruning failure must not turn a successful transaction into an apparent failure.
        let _ = persistence::cleanup_retained(&self.inner.root, &self.inner.options);
        Ok(generation)
    }

    async fn publish_snapshot(&self, snapshot: RouteSnapshot) -> Result<(), PlatformError> {
        let _mutation = self.inner.mutation.lock().await;
        let current = self.published()?;
        let expected = current
            .snapshot
            .generation
            .0
            .checked_add(1)
            .ok_or_else(|| {
                platform_error(
                    PlatformErrorCode::ResourceExhausted,
                    "route-generation-exhausted",
                    "the local route generation counter cannot be incremented",
                    Metadata::new(),
                )
            })?;
        if snapshot.generation.0 != expected {
            return Err(platform_error(
                PlatformErrorCode::StateConflict,
                "non-monotonic-route-generation",
                "a published route snapshot must be exactly the next local generation",
                stable_fields([
                    ("current", current.snapshot.generation.0.to_string()),
                    ("received", snapshot.generation.0.to_string()),
                    ("expected", expected.to_string()),
                ]),
            ));
        }
        let snapshot = Arc::new(snapshot);
        let index = Arc::new(RouteIndex::build(Arc::clone(&snapshot))?);
        let persisted = PersistedCatalogState::from_domain(current.deployments.as_ref(), &snapshot);
        persistence::commit(&self.inner.root, persisted, &self.inner.options)?;
        self.publish_committed_state(Arc::new(PublishedState {
            deployments: Arc::clone(&current.deployments),
            snapshot,
            index,
        }));
        let _ = persistence::cleanup_retained(&self.inner.root, &self.inner.options);
        Ok(())
    }

    fn published(&self) -> Result<Arc<PublishedState>, PlatformError> {
        let guard = match self.inner.published.read() {
            Ok(guard) => guard,
            Err(poisoned) => poisoned.into_inner(),
        };
        Ok(Arc::clone(&guard))
    }

    fn replace_published(&self, state: Arc<PublishedState>) -> Result<(), PlatformError> {
        #[cfg(test)]
        if fault_injection::take(
            &self.inner.root,
            fault_injection::FaultPoint::ReplacePublished,
        ) {
            return Err(lock_poisoned("replace-published-catalog-injected"));
        }

        let mut guard = self
            .inner
            .published
            .write()
            .map_err(|_| lock_poisoned("replace-published-catalog"))?;
        *guard = state;
        Ok(())
    }

    fn publish_committed_state(&self, state: Arc<PublishedState>) {
        if self.replace_published(Arc::clone(&state)).is_ok() {
            return;
        }

        // The marker rename is the transaction commit point. Once it succeeds, the
        // in-memory view must be reconciled to that generation before the caller returns.
        // Recovering a poisoned guard is safe here because the complete replacement state
        // was independently compiled, indexed, and durably committed.
        let mut guard = match self.inner.published.write() {
            Ok(guard) => guard,
            Err(poisoned) => poisoned.into_inner(),
        };
        *guard = state;
    }
}

impl DeploymentStore for EmbeddedDeploymentCatalog {
    fn apply<'a>(
        &'a self,
        deployment: DeploymentManifest,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move { self.apply_manifest(deployment).await.map(|_| ()) })
    }

    fn get<'a>(
        &'a self,
        id: &'a DeploymentId,
    ) -> BoxFuture<'a, Result<Option<DeploymentManifest>, PlatformError>> {
        Box::pin(async move { self.deployment(id) })
    }

    fn list<'a>(&'a self) -> BoxFuture<'a, Result<Vec<DeploymentManifest>, PlatformError>> {
        Box::pin(async move { self.deployments(None) })
    }

    fn delete<'a>(&'a self, id: &'a DeploymentId) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move { self.delete_manifest(id).await.map(|_| ()) })
    }
}

impl TenantDeploymentStore for EmbeddedDeploymentCatalog {
    fn list_for_tenant<'a>(
        &'a self,
        tenant: &'a TenantId,
    ) -> BoxFuture<'a, Result<Vec<DeploymentManifest>, PlatformError>> {
        Box::pin(async move { self.deployments(Some(tenant)) })
    }
}

impl RouteCompiler for EmbeddedDeploymentCatalog {
    fn compile<'a>(
        &'a self,
        previous: Option<&'a RouteSnapshot>,
    ) -> BoxFuture<'a, Result<RouteSnapshot, PlatformError>> {
        Box::pin(async move {
            let current = self.published()?;
            let previous = previous.unwrap_or(&current.snapshot);
            compile_deployments(
                current.deployments.as_ref(),
                self.inner.releases.as_ref(),
                Some(previous),
                &self.inner.options,
            )
            .await
        })
    }
}

impl RouteSnapshotSource for EmbeddedDeploymentCatalog {
    fn current<'a>(&'a self) -> BoxFuture<'a, Result<RouteSnapshot, PlatformError>> {
        Box::pin(async move { self.snapshot() })
    }

    fn watch<'a>(
        &'a self,
        after: RouteGeneration,
    ) -> BoxFuture<'a, Result<Vec<RouteSnapshot>, PlatformError>> {
        Box::pin(async move {
            persistence::load_after(&self.inner.root, after, &self.inner.options)?
                .into_iter()
                .map(|state| {
                    let (_, snapshot) = state.into_domain()?;
                    RouteIndex::build(Arc::new(snapshot.clone()))?;
                    Ok(snapshot)
                })
                .collect()
        })
    }
}

impl RouteSnapshotPublisher for EmbeddedDeploymentCatalog {
    fn publish<'a>(&'a self, snapshot: RouteSnapshot) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move { self.publish_snapshot(snapshot).await })
    }
}

impl RouteResolver for EmbeddedDeploymentCatalog {
    fn resolve(
        &self,
        target: &InvocationTarget,
        routing_key: Option<&str>,
    ) -> Result<ResolvedRevision, PlatformError> {
        self.resolve_target(target, routing_key)
    }

    fn resolve_binding(
        &self,
        consumer: &ResolvedRevision,
        imported_contract: &latent_core::ContractId,
        routing_key: Option<&str>,
    ) -> Result<ResolvedBinding, PlatformError> {
        self.resolve_target_binding(consumer, imported_contract, routing_key)
    }

    fn generation(&self) -> RouteGeneration {
        self.published()
            .map_or(RouteGeneration(0), |state| state.index.generation())
    }
}

impl CompiledRouteStore for EmbeddedDeploymentCatalog {
    fn put<'a>(&'a self, snapshot: RouteSnapshot) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move { self.publish_snapshot(snapshot).await })
    }

    fn current<'a>(&'a self) -> BoxFuture<'a, Result<RouteSnapshot, PlatformError>> {
        Box::pin(async move { self.snapshot() })
    }

    fn get<'a>(
        &'a self,
        generation: RouteGeneration,
    ) -> BoxFuture<'a, Result<Option<RouteSnapshot>, PlatformError>> {
        Box::pin(async move { self.retained_snapshot(generation) })
    }
}

fn same_route_identity(left: &DeploymentManifest, right: &DeploymentManifest) -> bool {
    left.metadata.tenant == right.metadata.tenant
        && left.metadata.namespace == right.metadata.namespace
        && left.service == right.service
        && normalized_annotation(left) == normalized_annotation(right)
}

fn normalized_annotation(deployment: &DeploymentManifest) -> Option<String> {
    deployment
        .metadata
        .annotations
        .get(ROUTE_ANNOTATION_KEY)
        .and_then(|value| {
            let value = value.trim();
            (!value.is_empty()).then(|| value.to_owned())
        })
}

fn validate_options(options: &EmbeddedCatalogOptions) -> Result<(), PlatformError> {
    if options.max_deployments == 0
        || options.max_state_file_bytes == 0
        || options.retained_generations == 0
    {
        return Err(platform_error(
            PlatformErrorCode::InvalidArgument,
            "invalid-embedded-catalog-options",
            "all embedded catalog bounds must be greater than zero",
            stable_fields([
                ("max_deployments", options.max_deployments.to_string()),
                (
                    "max_state_file_bytes",
                    options.max_state_file_bytes.to_string(),
                ),
                (
                    "retained_generations",
                    options.retained_generations.to_string(),
                ),
            ]),
        ));
    }
    Ok(())
}

fn lock_poisoned(operation: &str) -> PlatformError {
    platform_error(
        PlatformErrorCode::Internal,
        "embedded-catalog-lock-poisoned",
        "the embedded catalog publication lock was poisoned",
        stable_fields([("operation", operation.to_owned())]),
    )
}

pub(crate) fn platform_error(
    code: PlatformErrorCode,
    kind: impl Into<String>,
    message: impl Into<String>,
    fields: Metadata,
) -> PlatformError {
    PlatformError {
        code,
        message: message.into(),
        retryable: false,
        details: vec![ErrorDetail {
            kind: kind.into(),
            fields,
        }],
    }
}

pub(crate) fn stable_fields<I, K, V>(fields: I) -> Metadata
where
    I: IntoIterator<Item = (K, V)>,
    K: Into<String>,
    V: Into<String>,
{
    fields
        .into_iter()
        .map(|(key, value)| (key.into(), value.into()))
        .collect()
}
