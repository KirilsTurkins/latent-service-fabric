//! Embedded, tenant-safe deployment catalog and immutable route publication.

mod compiler;
mod persistence;
#[cfg(test)]
mod tests;

use std::collections::{BTreeMap, BTreeSet};
use std::fs::File;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, RwLock, TryLockError};
use std::time::{SystemTime, UNIX_EPOCH};

use latent_artifacts::ArtifactRepository;
use latent_core::{
    BoxFuture, ContractId, DeploymentId, ErrorDetail, Metadata, PlatformError, PlatformErrorCode,
    RevisionId, RouteGeneration,
};
use latent_manifest::{
    DeploymentManifest, JsonManifestCodec, ManifestCodec, ManifestValidator, ManifestViolation,
    Phase1ManifestValidator,
};
use latent_routing::{
    InvocationTarget, ResolvedBinding, ResolvedRevision, RouteCompiler, RouteResolver, RouteSnapshot,
    RouteSnapshotPublisher, RouteSnapshotSource,
};

use crate::{CompiledRouteStore, DeploymentStore};
use compiler::{compile, CompiledCatalog};

/// Bounds retained desired state, serialized state, and weighted index entries.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DirectoryDeploymentRepositoryConfig {
    pub max_deployments: usize,
    pub max_state_bytes: usize,
    pub max_route_entries: usize,
    pub max_identifier_bytes: usize,
    pub max_routing_key_bytes: usize,
}

impl Default for DirectoryDeploymentRepositoryConfig {
    fn default() -> Self {
        Self {
            max_deployments: 100_000,
            max_state_bytes: 64 * 1024 * 1024,
            max_route_entries: 1_000_000,
            max_identifier_bytes: 1024,
            max_routing_key_bytes: 4096,
        }
    }
}

/// One node-owned catalog. No runtime, task, thread, socket, or execution cell is created.
///
/// Writers compile outside the reader lock, then compare-and-swap the generation.
/// Concurrent writers may receive `state-conflict` and retry their transaction.
/// Management methods are trusted-local operations; authentication belongs to their adapter.
/// Invocation reads use one nonblocking lock attempt followed by an immutable index lookup.
/// A contended publication returns retryable `unavailable`, never waits for control-plane I/O.
pub struct DirectoryDeploymentRepository {
    root: PathBuf,
    config: DirectoryDeploymentRepositoryConfig,
    artifacts: Arc<dyn ArtifactRepository>,
    current: RwLock<Arc<CompiledCatalog>>,
    generation: AtomicU64,
    writer: Mutex<()>,
    _owner_lock: File,
    #[cfg(test)]
    fail_before_rename: std::sync::atomic::AtomicBool,
    #[cfg(test)]
    fail_parent_sync: std::sync::atomic::AtomicBool,
}

/// An owned read view that stays on its original generation after replacement or deletion.
#[derive(Clone)]
pub struct PinnedRouteResolver {
    catalog: Arc<CompiledCatalog>,
    config: DirectoryDeploymentRepositoryConfig,
}

impl DirectoryDeploymentRepository {
    /// Restores and verifies the latest complete state; never silently resets a corrupt catalog.
    pub async fn open(
        root: impl Into<PathBuf>,
        artifacts: Arc<dyn ArtifactRepository>,
        config: DirectoryDeploymentRepositoryConfig,
    ) -> Result<Self, PlatformError> {
        if config.max_deployments == 0
            || config.max_state_bytes < 1024
            || config.max_state_bytes > isize::MAX as usize
            || config.max_route_entries == 0
            || config.max_identifier_bytes == 0
            || config.max_routing_key_bytes == 0
        {
            return Err(error(PlatformErrorCode::InvalidArgument, "invalid-catalog-limits"));
        }
        let root = root.into();
        let owner_lock = persistence::own_root(&root)?;
        let restored = persistence::load(&root, config)?;
        let (deployments, generation, generated_at) = match &restored {
            Some(record) => (
                record.deployments(config)?,
                RouteGeneration(record.payload.generation),
                record.payload.generated_at_unix_millis,
            ),
            None => (BTreeMap::new(), RouteGeneration(0), 0),
        };
        let catalog = compile(deployments, generation, generated_at, artifacts.as_ref(), config)
            .await?;
        if let Some(record) = restored {
            if record.payload.snapshot != persistence::snapshot_value(&catalog.snapshot) {
                return Err(error(PlatformErrorCode::CorruptArtifact, "persisted-route-mismatch"));
            }
        }
        let repository = Self {
            root,
            config,
            artifacts,
            generation: AtomicU64::new(generation.0),
            current: RwLock::new(Arc::new(catalog)),
            writer: Mutex::new(()),
            _owner_lock: owner_lock,
            #[cfg(test)]
            fail_before_rename: std::sync::atomic::AtomicBool::new(false),
            #[cfg(test)]
            fail_parent_sync: std::sync::atomic::AtomicBool::new(false),
        };
        // A durable empty catalog makes subsequent loss distinguishable from first startup.
        if !repository.root.join(persistence::STATE_FILE).exists() {
            let bytes = persistence::encode(&repository.read_catalog(), config)?;
            persistence::stage(&repository.root, &bytes)?;
            persistence::replace(&repository.root)?;
            persistence::sync_root(&repository.root)?;
        }
        Ok(repository)
    }

    /// Atomically applies a batch. Repeated IDs in a batch are rejected, not last-write-wins.
    /// Existing IDs may be updated only inside their original tenant/namespace/service scope.
    pub async fn apply_many(
        &self,
        deployments: Vec<DeploymentManifest>,
    ) -> Result<RouteGeneration, PlatformError> {
        if deployments.is_empty() {
            return Ok(self.read_catalog().snapshot.generation);
        }
        if deployments.len() > self.config.max_deployments {
            return Err(error(PlatformErrorCode::ResourceExhausted, "deployment-count-limit"));
        }
        let previous = self.read_catalog();
        let mut next = previous.deployments.clone();
        let mut seen = BTreeSet::new();
        for mut deployment in deployments {
            Phase1ManifestValidator.validate_deployment(&deployment).map_err(manifest_error)?;
            JsonManifestCodec::default().encode_deployment(&deployment).map_err(manifest_error)?;
            deployment.release.0.make_ascii_lowercase();
            if deployment.id.0 == "default" {
                return Err(error(PlatformErrorCode::AlreadyExists, "reserved-default-route"));
            }
            if !seen.insert(deployment.id.clone()) {
                return Err(error(PlatformErrorCode::AlreadyExists, "duplicate-deployment-id"));
            }
            if let Some(old) = next.get(&deployment.id) {
                if old.metadata.tenant != deployment.metadata.tenant
                    || old.metadata.namespace != deployment.metadata.namespace
                    || old.service != deployment.service
                {
                    return Err(error(PlatformErrorCode::PermissionDenied, "deployment-scope-conflict"));
                }
            }
            next.insert(deployment.id.clone(), deployment);
        }
        let generation = next_generation(previous.snapshot.generation)?;
        let compiled = compile(next, generation, now()?, self.artifacts.as_ref(), self.config).await?;
        self.commit(previous.snapshot.generation, compiled)?;
        Ok(generation)
    }

    /// Acquires an immutable read view without waiting on a writer.
    pub fn pin(&self) -> Result<PinnedRouteResolver, PlatformError> {
        let catalog = match self.current.try_read() {
            Ok(current) => Arc::clone(&current),
            Err(TryLockError::Poisoned(poisoned)) => Arc::clone(&poisoned.into_inner()),
            Err(TryLockError::WouldBlock) => {
                return Err(error(PlatformErrorCode::Unavailable, "snapshot-publication-busy"));
            }
        };
        Ok(PinnedRouteResolver { catalog, config: self.config })
    }

    fn read_catalog(&self) -> Arc<CompiledCatalog> {
        Arc::clone(&self.current.read().unwrap_or_else(std::sync::PoisonError::into_inner))
    }

    fn commit(&self, expected: RouteGeneration, next: CompiledCatalog) -> Result<(), PlatformError> {
        // No await, compilation, or artifact access occurs with this writer guard held.
        let _writer = self.writer.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        if self.read_catalog().snapshot.generation != expected {
            return Err(error(PlatformErrorCode::StateConflict, "stale-route-generation"));
        }
        let bytes = persistence::encode(&next, self.config)?;
        let next = Arc::new(next);
        persistence::stage(&self.root, &bytes)?;
        #[cfg(test)]
        if self.fail_before_rename.swap(false, Ordering::SeqCst) {
            return Err(error(PlatformErrorCode::Unavailable, "injected-before-rename"));
        }
        persistence::replace(&self.root)?;
        // Rename is the visibility commit point. Even an uncertain directory fsync must
        // install the same complete state in memory, rather than continuing on the old state.
        let durable = self.sync_parent();
        let generation = next.snapshot.generation.0;
        let old = {
            let mut current = self.current.write().unwrap_or_else(std::sync::PoisonError::into_inner);
            let old = std::mem::replace(&mut *current, next);
            self.generation.store(generation, Ordering::Release);
            old
        };
        drop(old); // Potentially large destruction is deliberately outside the reader lock.
        durable
    }

    fn sync_parent(&self) -> Result<(), PlatformError> {
        #[cfg(test)]
        if self.fail_parent_sync.swap(false, Ordering::SeqCst) {
            return Err(error(PlatformErrorCode::Unavailable, "commit-durability-uncertain"));
        }
        persistence::sync_root(&self.root)
    }
}

impl DeploymentStore for DirectoryDeploymentRepository {
    fn apply<'a>(&'a self, deployment: DeploymentManifest) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move { self.apply_many(vec![deployment]).await.map(|_| ()) })
    }

    fn get<'a>(&'a self, id: &'a DeploymentId) -> BoxFuture<'a, Result<Option<DeploymentManifest>, PlatformError>> {
        Box::pin(async move { Ok(self.read_catalog().deployments.get(id).cloned()) })
    }

    fn list<'a>(&'a self) -> BoxFuture<'a, Result<Vec<DeploymentManifest>, PlatformError>> {
        Box::pin(async move { Ok(self.read_catalog().deployments.values().cloned().collect()) })
    }

    fn delete<'a>(&'a self, id: &'a DeploymentId) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move {
            let previous = self.read_catalog();
            let mut next = previous.deployments.clone();
            if next.remove(id).is_none() {
                return Err(error(PlatformErrorCode::NotFound, "deployment-not-found"));
            }
            let generation = next_generation(previous.snapshot.generation)?;
            let compiled = compile(next, generation, now()?, self.artifacts.as_ref(), self.config).await?;
            self.commit(previous.snapshot.generation, compiled)
        })
    }
}

impl RouteCompiler for DirectoryDeploymentRepository {
    fn compile<'a>(&'a self, previous: Option<&'a RouteSnapshot>) -> BoxFuture<'a, Result<RouteSnapshot, PlatformError>> {
        Box::pin(async move {
            let current = self.read_catalog();
            let matches = previous.map_or(current.snapshot.generation.0 == 0, |old| old == &current.snapshot);
            if !matches {
                return Err(error(PlatformErrorCode::StateConflict, "stale-route-generation"));
            }
            let next = compile(
                current.deployments.clone(),
                next_generation(current.snapshot.generation)?,
                now()?,
                self.artifacts.as_ref(),
                self.config,
            ).await?;
            Ok(next.snapshot)
        })
    }
}

impl RouteSnapshotPublisher for DirectoryDeploymentRepository {
    fn publish<'a>(&'a self, snapshot: RouteSnapshot) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move {
            let current = self.read_catalog();
            if snapshot.generation != next_generation(current.snapshot.generation)? {
                return Err(error(PlatformErrorCode::StateConflict, "stale-route-generation"));
            }
            let compiled = compile(
                current.deployments.clone(),
                snapshot.generation,
                snapshot.generated_at_unix_millis,
                self.artifacts.as_ref(),
                self.config,
            ).await?;
            if compiled.snapshot != snapshot {
                return Err(error(PlatformErrorCode::InvalidArgument, "uncompiled-route-snapshot"));
            }
            self.commit(current.snapshot.generation, compiled)
        })
    }
}

impl RouteSnapshotSource for DirectoryDeploymentRepository {
    fn current<'a>(&'a self) -> BoxFuture<'a, Result<RouteSnapshot, PlatformError>> {
        Box::pin(async move { Ok(self.read_catalog().snapshot.clone()) })
    }

    fn watch<'a>(&'a self, after: RouteGeneration) -> BoxFuture<'a, Result<Vec<RouteSnapshot>, PlatformError>> {
        Box::pin(async move {
            let current = self.read_catalog();
            if after > current.snapshot.generation {
                return Err(error(PlatformErrorCode::InvalidArgument, "future-route-generation"));
            }
            Ok(if after < current.snapshot.generation { vec![current.snapshot.clone()] } else { Vec::new() })
        })
    }
}

impl CompiledRouteStore for DirectoryDeploymentRepository {
    fn put<'a>(&'a self, snapshot: RouteSnapshot) -> BoxFuture<'a, Result<(), PlatformError>> {
        RouteSnapshotPublisher::publish(self, snapshot)
    }

    fn current<'a>(&'a self) -> BoxFuture<'a, Result<RouteSnapshot, PlatformError>> {
        RouteSnapshotSource::current(self)
    }

    fn get<'a>(&'a self, generation: RouteGeneration) -> BoxFuture<'a, Result<Option<RouteSnapshot>, PlatformError>> {
        Box::pin(async move {
            let current = self.read_catalog();
            Ok((generation == current.snapshot.generation).then(|| current.snapshot.clone()))
        })
    }
}

impl RouteResolver for DirectoryDeploymentRepository {
    fn resolve(&self, target: &InvocationTarget, routing_key: Option<&str>) -> Result<ResolvedRevision, PlatformError> {
        self.pin()?.resolve(target, routing_key)
    }

    fn resolve_binding(&self, _consumer: &ResolvedRevision, _contract: &ContractId, _key: Option<&str>) -> Result<ResolvedBinding, PlatformError> {
        Err(error(PlatformErrorCode::RouteUnavailable, "local-bindings-not-configured"))
    }

    fn generation(&self) -> RouteGeneration {
        RouteGeneration(self.generation.load(Ordering::Acquire))
    }
}

impl RouteResolver for PinnedRouteResolver {
    fn resolve(&self, target: &InvocationTarget, routing_key: Option<&str>) -> Result<ResolvedRevision, PlatformError> {
        self.catalog.resolve(target, routing_key, self.config)
    }

    fn resolve_binding(&self, _consumer: &ResolvedRevision, _contract: &ContractId, _key: Option<&str>) -> Result<ResolvedBinding, PlatformError> {
        Err(error(PlatformErrorCode::RouteUnavailable, "local-bindings-not-configured"))
    }

    fn generation(&self) -> RouteGeneration {
        self.catalog.snapshot.generation
    }
}

/// Versioned revision identity over the canonical deployment, excluding only route weight.
/// Release spelling is normalized; tenant, namespace, ID, service, policy and budgets remain bound.
pub fn deployment_revision_id(deployment: &DeploymentManifest) -> Result<RevisionId, PlatformError> {
    Phase1ManifestValidator.validate_deployment(deployment).map_err(manifest_error)?;
    let mut identity = deployment.clone();
    identity.route_weight = 1;
    identity.release.0.make_ascii_lowercase();
    let bytes = JsonManifestCodec::default().encode_deployment(&identity).map_err(manifest_error)?;
    let mut framed = b"lsf-deployment-revision-v1\0".to_vec();
    framed.extend_from_slice(&(bytes.len() as u64).to_be_bytes());
    framed.extend_from_slice(&bytes);
    Ok(RevisionId(format!("revision-v1:{}", latent_artifacts::content_digest(&framed).0)))
}

fn next_generation(previous: RouteGeneration) -> Result<RouteGeneration, PlatformError> {
    previous.0.checked_add(1).map(RouteGeneration).ok_or_else(|| {
        error(PlatformErrorCode::ResourceExhausted, "route-generation-exhausted")
    })
}

fn now() -> Result<u64, PlatformError> {
    SystemTime::now().duration_since(UNIX_EPOCH).ok()
        .and_then(|duration| u64::try_from(duration.as_millis()).ok())
        .ok_or_else(|| error(PlatformErrorCode::Internal, "invalid-system-clock"))
}

fn error(code: PlatformErrorCode, reason: &str) -> PlatformError {
    PlatformError {
        code,
        message: reason.to_owned(),
        retryable: matches!(code, PlatformErrorCode::Unavailable | PlatformErrorCode::StateConflict),
        details: vec![ErrorDetail {
            kind: "deployment-catalog".to_owned(),
            fields: Metadata::from([("reason".to_owned(), reason.to_owned())]),
        }],
    }
}

fn manifest_error(violations: Vec<ManifestViolation>) -> PlatformError {
    let code = if violations.iter().any(|v| v.code.contains("scope") || v.code == "namespace-requires-tenant") {
        PlatformErrorCode::PermissionDenied
    } else {
        PlatformErrorCode::InvalidArgument
    };
    PlatformError {
        code,
        message: "deployment or release failed Phase 1 validation".to_owned(),
        retryable: false,
        details: violations.into_iter().map(|violation| ErrorDetail {
            kind: "manifest-violation".to_owned(),
            fields: Metadata::from([
                ("path".to_owned(), violation.path),
                ("code".to_owned(), violation.code),
            ]),
        }).collect(),
    }
}
