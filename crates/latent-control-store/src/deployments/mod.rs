//! Embedded, tenant-safe deployment catalog and immutable route publication.

mod admission_fence;
mod compiler;
mod mutations;
mod observation;
mod pagination;
mod persistence;
mod recovery_admission;
mod scoped_routes;
#[cfg(test)]
mod tests;

use std::collections::hash_map::RandomState;
use std::collections::BTreeMap;
use std::fs::File;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, RwLock, RwLockReadGuard, TryLockError};
use std::time::{SystemTime, UNIX_EPOCH};

use latent_artifacts::{AdmissionAuthority, ArtifactRepository, ReleaseUseRecheck};
use latent_core::{
    BoxFuture, ContractId, ErrorDetail, Metadata, PlatformError, PlatformErrorCode, RevisionId,
    RouteGeneration,
};
use latent_manifest::{
    DeploymentManifest, JsonManifestCodec, ManifestCodec, ManifestValidator, ManifestViolation,
    Phase1ManifestValidator,
};
use latent_routing::{
    InvocationTarget, ResolvedBinding, ResolvedRevision, RouteCompiler, RouteResolver,
    RouteSnapshot, RouteSnapshotPublisher, RouteSnapshotSource,
};

use crate::CompiledRouteStore;
use compiler::{compile_versioned_with_runtime, CompiledCatalog};
use mutations::{CommitOutcome, ObjectPrecondition};
use observation::{count, CatalogWorkOperation as WorkOperation, Source, Work};
#[cfg(feature = "catalog-observation")]
pub use observation::{
    CatalogWorkCounts, CatalogWorkObserver, CatalogWorkOperation, CatalogWorkOutcome,
    CatalogWorkReceipt, CatalogWorkSnapshot,
};
pub use pagination::{DeploymentPage, DeploymentPageRequest};
use persistence::EncodedCatalog;

impl latent_routing::ActivationCatalogSource for DirectoryDeploymentRepository {
    fn pin(&self) -> Result<Arc<dyn latent_routing::ActivationCatalog>, PlatformError> {
        Ok(Arc::new(DirectoryDeploymentRepository::pin(self)?))
    }
}

/// Bounds retained desired state, serialized state, and weighted index entries.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DirectoryDeploymentRepositoryConfig {
    pub max_deployments: usize,
    pub max_state_bytes: usize,
    pub max_route_entries: usize,
    pub max_identifier_bytes: usize,
    pub max_routing_key_bytes: usize,
    pub max_page_size: u32,
    pub max_page_bytes: usize,
}

impl Default for DirectoryDeploymentRepositoryConfig {
    fn default() -> Self {
        Self {
            max_deployments: 100_000,
            max_state_bytes: 64 * 1024 * 1024,
            max_route_entries: 1_000_000,
            max_identifier_bytes: 1024,
            max_routing_key_bytes: 4096,
            max_page_size: 1000,
            max_page_bytes: 4 * 1024 * 1024,
        }
    }
}

/// Releases ownership even while a forked child still has a duplicate descriptor.
/// Construct only after acquisition succeeds, before fallible initialization.
struct OwnerLock(File);

impl Drop for OwnerLock {
    fn drop(&mut self) {
        // Closing alone leaves a Unix flock alive until all inherited handles
        // close. Explicit unlock releases our ownership before the file closes.
        let _ = self.0.unlock();
    }
}

/// One node-owned catalog. No runtime, task, thread, socket, or execution cell is created.
///
/// Writers compile outside the reader lock, then compare-and-swap the generation.
/// Concurrent writers may receive `state-conflict` and retry their transaction.
/// Management methods are trusted-local operations; authentication belongs to their adapter.
/// Management I/O is synchronous and must run on a control-plane worker, not an invocation worker.
/// Invocation reads use one nonblocking lock attempt followed by an immutable index lookup.
/// A contended publication returns retryable `unavailable`, never waits for control-plane I/O.
pub struct DirectoryDeploymentRepository {
    root: PathBuf,
    config: DirectoryDeploymentRepositoryConfig,
    artifacts: Arc<dyn ArtifactRepository>,
    admission: Option<Arc<dyn AdmissionAuthority>>,
    runtime_profile: Option<Arc<latent_manifest::RuntimeCompatibilityProfile>>,
    lifecycle: Option<latent_artifacts::LifecycleAuthorityHandle>,
    current: RwLock<Arc<CompiledCatalog>>,
    generation: AtomicU64,
    writer: Mutex<()>,
    pagination_fingerprint: RandomState,
    observation: Source,
    _owner_lock: OwnerLock,
    #[cfg(test)]
    fail_before_rename: std::sync::atomic::AtomicBool,
    #[cfg(test)]
    fail_parent_sync: std::sync::atomic::AtomicBool,
    #[cfg(test)]
    after_parent_sync: Mutex<Option<Box<dyn FnOnce() + Send>>>,
}

/// An owned read view that stays on its original generation after replacement or deletion.
/// Explicit pins retain that generation's metadata until their last owner drops the view.
#[derive(Clone)]
pub struct PinnedRouteResolver {
    catalog: Arc<CompiledCatalog>,
    config: DirectoryDeploymentRepositoryConfig,
}

impl DirectoryDeploymentRepository {
    /// Reports exact catalog-owner identity without checking any release grant.
    #[must_use]
    pub fn is_bound_to_catalog(&self, owner: &latent_artifacts::LifecycleAuthorityHandle) -> bool {
        self.lifecycle
            .as_ref()
            .is_some_and(|configured| configured.same_owner(owner))
    }

    /// Restores and verifies the latest complete state; never silently resets a corrupt catalog.
    /// Relative paths are anchored on first poll, before suspension. The retained
    /// canonical absolute root keeps later operations bound to the owned directory.
    pub async fn open(
        root: impl Into<PathBuf>,
        artifacts: Arc<dyn ArtifactRepository>,
        config: DirectoryDeploymentRepositoryConfig,
    ) -> Result<Self, PlatformError> {
        Self::open_inner(root, artifacts, config, Source::default(), None, None, None).await
    }

    /// Opens a catalog whose releases must belong to this exact live authority.
    pub async fn open_enforced(
        root: impl Into<PathBuf>,
        artifacts: Arc<dyn ArtifactRepository>,
        config: DirectoryDeploymentRepositoryConfig,
        authority: Arc<dyn AdmissionAuthority>,
    ) -> Result<Self, PlatformError> {
        Self::open_inner(
            root,
            artifacts,
            config,
            Source::default(),
            Some(authority),
            None,
            None,
        )
        .await
    }

    /// Opens with optional bounded work receipts, including recovery and failed initialization.
    /// The observer retains neither this repository nor any artifact or catalog payload.
    #[cfg(feature = "catalog-observation")]
    pub async fn open_observed(
        root: impl Into<PathBuf>,
        artifacts: Arc<dyn ArtifactRepository>,
        config: DirectoryDeploymentRepositoryConfig,
        observer: CatalogWorkObserver,
    ) -> Result<Self, PlatformError> {
        Self::open_inner(
            root,
            artifacts,
            config,
            Source::observed(observer),
            None,
            None,
            None,
        )
        .await
    }

    /// Restores a trusted-local catalog against one immutable host profile.
    pub async fn open_with_runtime(
        root: impl Into<PathBuf>,
        artifacts: Arc<dyn ArtifactRepository>,
        config: DirectoryDeploymentRepositoryConfig,
        profile: Arc<latent_manifest::RuntimeCompatibilityProfile>,
    ) -> Result<Self, PlatformError> {
        Self::open_inner(
            root,
            artifacts,
            config,
            Source::default(),
            None,
            Some(profile),
            None,
        )
        .await
    }

    /// Enforces both current release authority and declared host requirements.
    pub async fn open_enforced_with_runtime(
        root: impl Into<PathBuf>,
        artifacts: Arc<dyn ArtifactRepository>,
        config: DirectoryDeploymentRepositoryConfig,
        authority: Arc<dyn AdmissionAuthority>,
        profile: Arc<latent_manifest::RuntimeCompatibilityProfile>,
    ) -> Result<Self, PlatformError> {
        Self::open_inner(
            root,
            artifacts,
            config,
            Source::default(),
            Some(authority),
            Some(profile),
            None,
        )
        .await
    }

    #[cfg(feature = "catalog-observation")]
    pub async fn open_observed_with_runtime(
        root: impl Into<PathBuf>,
        artifacts: Arc<dyn ArtifactRepository>,
        config: DirectoryDeploymentRepositoryConfig,
        observer: CatalogWorkObserver,
        profile: Arc<latent_manifest::RuntimeCompatibilityProfile>,
    ) -> Result<Self, PlatformError> {
        Self::open_inner(
            root,
            artifacts,
            config,
            Source::observed(observer),
            None,
            Some(profile),
            None,
        )
        .await
    }

    /// Binds historical recovery and active routes to this exact catalog owner.
    pub async fn open_with_catalog(
        root: impl Into<PathBuf>,
        artifacts: Arc<dyn ArtifactRepository>,
        config: DirectoryDeploymentRepositoryConfig,
        lifecycle: latent_artifacts::LifecycleAuthorityHandle,
        profile: Arc<latent_manifest::RuntimeCompatibilityProfile>,
    ) -> Result<Self, PlatformError> {
        let admission = lifecycle.required_authority().cloned();
        Self::open_inner(
            root,
            artifacts,
            config,
            Source::default(),
            admission,
            Some(profile),
            Some(lifecycle),
        )
        .await
    }

    #[cfg(feature = "catalog-observation")]
    pub async fn open_observed_with_catalog(
        root: impl Into<PathBuf>,
        artifacts: Arc<dyn ArtifactRepository>,
        config: DirectoryDeploymentRepositoryConfig,
        observer: CatalogWorkObserver,
        lifecycle: latent_artifacts::LifecycleAuthorityHandle,
        profile: Arc<latent_manifest::RuntimeCompatibilityProfile>,
    ) -> Result<Self, PlatformError> {
        let admission = lifecycle.required_authority().cloned();
        Self::open_inner(
            root,
            artifacts,
            config,
            Source::observed(observer),
            admission,
            Some(profile),
            Some(lifecycle),
        )
        .await
    }

    async fn open_inner(
        root: impl Into<PathBuf>,
        artifacts: Arc<dyn ArtifactRepository>,
        config: DirectoryDeploymentRepositoryConfig,
        observation: Source,
        admission: Option<Arc<dyn AdmissionAuthority>>,
        runtime_profile: Option<Arc<latent_manifest::RuntimeCompatibilityProfile>>,
        lifecycle: Option<latent_artifacts::LifecycleAuthorityHandle>,
    ) -> Result<Self, PlatformError> {
        let mut work = observation.begin(WorkOperation::Open);
        let result = async {
            if config.max_deployments == 0
                || config.max_state_bytes < 1024
                || config.max_state_bytes > isize::MAX as usize
                || config.max_route_entries == 0
                || config.max_identifier_bytes == 0
                || config.max_routing_key_bytes == 0
                || !pagination::valid_page_config(config)
            {
                return Err(error(
                    PlatformErrorCode::InvalidArgument,
                    "invalid-catalog-limits",
                ));
            }
            let root = root.into();
            let (root, owner_lock) = persistence::own_root(&root)?;
            let restored = persistence::load(&root, config, &mut work)?;
            let needs_initial_state = restored.is_none();
            let (deployments, versions, generation, generated_at) = match &restored {
                Some(record) => {
                    let deployments = record.deployments(config)?;
                    let versions = record.object_generations(&deployments)?;
                    (
                        deployments
                            .into_iter()
                            .map(|(id, manifest)| (id, Arc::new(manifest)))
                            .collect(),
                        versions,
                        RouteGeneration(record.payload.generation),
                        record.payload.generated_at_unix_millis,
                    )
                }
                None => (BTreeMap::new(), BTreeMap::new(), RouteGeneration(0), 0),
            };
            let catalog = compiler::compile_versioned_inner(
                deployments,
                versions,
                generation,
                generated_at,
                artifacts.as_ref(),
                config,
                None,
                &mut work,
                true,
                runtime_profile.as_deref(),
                lifecycle.as_ref(),
            )
            .await?;
            if let Some(record) = restored {
                if record.payload.snapshot != persistence::catalog_snapshot_value(catalog.catalog())
                {
                    return Err(error(
                        PlatformErrorCode::CorruptArtifact,
                        "persisted-route-mismatch",
                    ));
                }
            }
            let (catalog, bytes) = catalog.into_parts();
            recovery_admission::check(true, || {
                catalog.check_admission_mode(admission.as_ref(), lifecycle.as_ref())
            })
            .await?;
            let repository = Self {
                root,
                config,
                artifacts,
                admission,
                runtime_profile,
                lifecycle,
                generation: AtomicU64::new(generation.0),
                current: RwLock::new(Arc::new(catalog)),
                writer: Mutex::new(()),
                pagination_fingerprint: RandomState::new(),
                observation: observation.clone(),
                _owner_lock: owner_lock,
                #[cfg(test)]
                fail_before_rename: std::sync::atomic::AtomicBool::new(false),
                #[cfg(test)]
                fail_parent_sync: std::sync::atomic::AtomicBool::new(false),
                #[cfg(test)]
                after_parent_sync: Mutex::new(None),
            };
            // A durable empty catalog makes subsequent loss distinguishable from first startup.
            let catalog = Arc::clone(&repository.read_catalog());
            let retry = recovery_admission::Retry::new(true);
            loop {
                let mut started = false;
                let result = catalog.with_current_admission(&mut |checker| {
                    started = true;
                    if needs_initial_state {
                        persistence::stage(&repository.root, &bytes, &mut work)?;
                        if let Some(checker) = checker {
                            checker.check()?;
                        }
                        persistence::replace(&repository.root)?;
                    }
                    persistence::sync_root(&repository.root)?;
                    if let Some(checker) = checker {
                        checker.check()?;
                    }
                    Ok(())
                });
                match result {
                    Err(failure) if !started && retry.pause(&failure).await => {}
                    result => {
                        result?;
                        break;
                    }
                }
            }
            drop(bytes);
            Ok(repository)
        }
        .await;
        work.finish(&result);
        result
    }

    /// Acquires an immutable read view without waiting on a writer.
    pub fn pin(&self) -> Result<PinnedRouteResolver, PlatformError> {
        let catalog = self.invocation_catalog()?;
        Ok(PinnedRouteResolver {
            catalog: Arc::clone(&catalog),
            config: self.config,
        })
    }

    fn invocation_catalog(
        &self,
    ) -> Result<RwLockReadGuard<'_, Arc<CompiledCatalog>>, PlatformError> {
        match self.current.try_read() {
            Ok(current) => Ok(current),
            Err(TryLockError::Poisoned(poisoned)) => Ok(poisoned.into_inner()),
            Err(TryLockError::WouldBlock) => Err(error(
                PlatformErrorCode::Unavailable,
                "snapshot-publication-busy",
            )),
        }
    }

    fn read_catalog(&self) -> Arc<CompiledCatalog> {
        Arc::clone(
            &self
                .current
                .read()
                .unwrap_or_else(std::sync::PoisonError::into_inner),
        )
    }

    fn commit(
        &self,
        expected: RouteGeneration,
        next: EncodedCatalog,
        work: &mut Work,
    ) -> Result<(), PlatformError> {
        self.commit_checked(expected, next, None, work)?.durability
    }

    fn commit_checked(
        &self,
        expected: RouteGeneration,
        next: EncodedCatalog,
        precondition: Option<&ObjectPrecondition>,
        work: &mut Work,
    ) -> Result<CommitOutcome, PlatformError> {
        let (next, bytes) = next.into_parts();
        next.check_admission_mode(self.admission.as_ref(), self.lifecycle.as_ref())?;
        let next = Arc::new(next);
        let mut outcome = None;
        next.with_current_admission(&mut |checker| {
            outcome = Some(self.commit_admitted(
                expected,
                Arc::clone(&next),
                &bytes,
                precondition,
                work,
                checker,
            )?);
            Ok(())
        })?;
        outcome.ok_or_else(|| {
            error(
                PlatformErrorCode::Internal,
                "route-admission-commit-missing",
            )
        })
    }

    fn commit_admitted(
        &self,
        expected: RouteGeneration,
        next: Arc<CompiledCatalog>,
        bytes: &[u8],
        precondition: Option<&ObjectPrecondition>,
        work: &mut Work,
        checker: Option<&dyn ReleaseUseRecheck>,
    ) -> Result<CommitOutcome, PlatformError> {
        // No await, compilation, or artifact access occurs with this writer guard held.
        let _writer = self
            .writer
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let current = self.read_catalog();
        if let Some(precondition) = precondition {
            precondition.check(&current)?;
        }
        if current.generation != expected {
            return Err(error(
                PlatformErrorCode::StateConflict,
                "stale-route-generation",
            ));
        }
        persistence::stage(&self.root, bytes, work)?;
        #[cfg(test)]
        if self.fail_before_rename.swap(false, Ordering::SeqCst) {
            return Err(error(
                PlatformErrorCode::Unavailable,
                "injected-before-rename",
            ));
        }
        if let Some(checker) = checker {
            checker.check()?;
        }
        persistence::replace(&self.root)?;
        // Rename is the visibility commit point. Even an uncertain directory fsync must
        // install the same complete state in memory, rather than continuing on the old state.
        let durable = self.sync_parent();
        let currentness = checker.map_or(Ok(()), ReleaseUseRecheck::check);
        let generation = next.generation.0;
        let old = {
            let mut current = self
                .current
                .write()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            let old = std::mem::replace(&mut *current, next);
            self.generation.store(generation, Ordering::Release);
            old
        };
        drop(old); // Potentially large destruction is deliberately outside the reader lock.
        Ok(CommitOutcome {
            durability: durable.and(currentness),
        })
    }

    fn sync_parent(&self) -> Result<(), PlatformError> {
        #[cfg(test)]
        if self.fail_parent_sync.swap(false, Ordering::SeqCst) {
            return Err(error(
                PlatformErrorCode::Unavailable,
                "commit-durability-uncertain",
            ));
        }
        let result = persistence::sync_root(&self.root);
        #[cfg(test)]
        if let Some(after) = self.after_parent_sync.lock().unwrap().take() {
            after();
        }
        result
    }
}

impl RouteCompiler for DirectoryDeploymentRepository {
    fn compile<'a>(
        &'a self,
        previous: Option<&'a RouteSnapshot>,
    ) -> BoxFuture<'a, Result<RouteSnapshot, PlatformError>> {
        Box::pin(async move {
            let mut work = self.observation.begin(WorkOperation::CompileSnapshot);
            let result = async {
                let current = self.read_catalog();
                let matches = previous.map_or(current.generation.0 == 0, |old| {
                    current.matches_snapshot(old)
                });
                if !matches {
                    return Err(error(
                        PlatformErrorCode::StateConflict,
                        "stale-route-generation",
                    ));
                }
                let next = compile_versioned_with_runtime(
                    current.deployments.clone(),
                    current.versions.clone(),
                    next_generation(current.generation)?,
                    now()?,
                    self.artifacts.as_ref(),
                    self.config,
                    Some(&current),
                    &mut work,
                    self.runtime_profile.as_deref(),
                    self.lifecycle.as_ref(),
                )
                .await?;
                Ok(next.into_catalog().snapshot())
            }
            .await;
            work.finish(&result);
            result
        })
    }
}

impl RouteSnapshotPublisher for DirectoryDeploymentRepository {
    fn publish<'a>(&'a self, snapshot: RouteSnapshot) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move {
            let mut work = self.observation.begin(WorkOperation::PublishSnapshot);
            let result = {
                let work = &mut work;
                async move {
                    let current = self.read_catalog();
                    if snapshot.generation != next_generation(current.generation)? {
                        return Err(error(
                            PlatformErrorCode::StateConflict,
                            "stale-route-generation",
                        ));
                    }
                    let compiled = compile_versioned_with_runtime(
                        current.deployments.clone(),
                        current.versions.clone(),
                        snapshot.generation,
                        snapshot.generated_at_unix_millis,
                        self.artifacts.as_ref(),
                        self.config,
                        Some(&current),
                        work,
                        self.runtime_profile.as_deref(),
                        self.lifecycle.as_ref(),
                    )
                    .await?;
                    if !compiled.catalog().matches_snapshot(&snapshot) {
                        return Err(error(
                            PlatformErrorCode::InvalidArgument,
                            "uncompiled-route-snapshot",
                        ));
                    }
                    self.commit(current.generation, compiled, work)
                }
            }
            .await;
            work.finish(&result);
            result
        })
    }
}

impl RouteSnapshotSource for DirectoryDeploymentRepository {
    fn current<'a>(&'a self) -> BoxFuture<'a, Result<RouteSnapshot, PlatformError>> {
        Box::pin(async move { Ok(self.read_catalog().snapshot()) })
    }

    fn watch<'a>(
        &'a self,
        after: RouteGeneration,
    ) -> BoxFuture<'a, Result<Vec<RouteSnapshot>, PlatformError>> {
        Box::pin(async move {
            let current = self.read_catalog();
            if after > current.generation {
                return Err(error(
                    PlatformErrorCode::InvalidArgument,
                    "future-route-generation",
                ));
            }
            Ok(if after < current.generation {
                vec![current.snapshot()]
            } else {
                Vec::new()
            })
        })
    }
}

impl CompiledRouteStore for DirectoryDeploymentRepository {
    fn scoped(
        &self,
        request: crate::ScopedRouteRequest,
    ) -> BoxFuture<'_, Result<crate::ScopedRouteSnapshot, PlatformError>> {
        Box::pin(async move { self.scoped_routes(request) })
    }

    fn put<'a>(&'a self, snapshot: RouteSnapshot) -> BoxFuture<'a, Result<(), PlatformError>> {
        RouteSnapshotPublisher::publish(self, snapshot)
    }

    fn current<'a>(&'a self) -> BoxFuture<'a, Result<RouteSnapshot, PlatformError>> {
        RouteSnapshotSource::current(self)
    }

    fn get<'a>(
        &'a self,
        generation: RouteGeneration,
    ) -> BoxFuture<'a, Result<Option<RouteSnapshot>, PlatformError>> {
        Box::pin(async move {
            let current = self.read_catalog();
            Ok((generation == current.generation).then(|| current.snapshot()))
        })
    }
}

impl RouteResolver for DirectoryDeploymentRepository {
    fn resolve(
        &self,
        target: &InvocationTarget,
        routing_key: Option<&str>,
    ) -> Result<ResolvedRevision, PlatformError> {
        // Borrow instead of pinning: a normal lookup never becomes the last owner that
        // has to destroy an entire retired catalog on the invocation worker.
        let (resolved, eligibility) = {
            let catalog = self.invocation_catalog()?;
            let resolved = catalog.resolve(target, routing_key, self.config)?;
            let eligibility = catalog.selected_eligibility(&resolved.release);
            (resolved, eligibility)
        };
        admission_fence::check_selected(eligibility.as_ref(), &target.tenant)?;
        Ok(resolved)
    }

    fn resolve_binding(
        &self,
        _consumer: &ResolvedRevision,
        _contract: &ContractId,
        _key: Option<&str>,
    ) -> Result<ResolvedBinding, PlatformError> {
        Err(error(
            PlatformErrorCode::RouteUnavailable,
            "local-bindings-not-configured",
        ))
    }

    fn generation(&self) -> RouteGeneration {
        RouteGeneration(self.generation.load(Ordering::Acquire))
    }
}

impl RouteResolver for PinnedRouteResolver {
    fn resolve(
        &self,
        target: &InvocationTarget,
        routing_key: Option<&str>,
    ) -> Result<ResolvedRevision, PlatformError> {
        let resolved = self.catalog.resolve(target, routing_key, self.config)?;
        admission_fence::check_selected(
            self.catalog
                .selected_eligibility(&resolved.release)
                .as_ref(),
            &target.tenant,
        )?;
        Ok(resolved)
    }

    fn resolve_binding(
        &self,
        _consumer: &ResolvedRevision,
        _contract: &ContractId,
        _key: Option<&str>,
    ) -> Result<ResolvedBinding, PlatformError> {
        Err(error(
            PlatformErrorCode::RouteUnavailable,
            "local-bindings-not-configured",
        ))
    }

    fn generation(&self) -> RouteGeneration {
        self.catalog.generation
    }
}

/// Versioned revision identity over the canonical deployment, excluding only route weight.
/// Release spelling is normalized; tenant, namespace, ID, service, policy and budgets remain bound.
pub fn deployment_revision_id(
    deployment: &DeploymentManifest,
) -> Result<RevisionId, PlatformError> {
    deployment_revision_id_observed(deployment, &mut Work::default())
}

fn deployment_revision_id_observed(
    deployment: &DeploymentManifest,
    work: &mut Work,
) -> Result<RevisionId, PlatformError> {
    Phase1ManifestValidator
        .validate_deployment(deployment)
        .map_err(manifest_error)?;
    let mut identity = deployment.clone();
    identity.route_weight = 1;
    identity.release.0.make_ascii_lowercase();
    count!(work, revision_identity_encodes, 1);
    let bytes = JsonManifestCodec::default()
        .encode_deployment(&identity)
        .map_err(manifest_error)?;
    let mut framed = b"lsf-deployment-revision-v1\0".to_vec();
    framed.extend_from_slice(&(bytes.len() as u64).to_be_bytes());
    framed.extend_from_slice(&bytes);
    Ok(RevisionId(format!(
        "revision-v1:{}",
        latent_artifacts::content_digest(&framed).0
    )))
}

fn next_generation(previous: RouteGeneration) -> Result<RouteGeneration, PlatformError> {
    previous
        .0
        .checked_add(1)
        .map(RouteGeneration)
        .ok_or_else(|| {
            error(
                PlatformErrorCode::ResourceExhausted,
                "route-generation-exhausted",
            )
        })
}

fn now() -> Result<u64, PlatformError> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()
        .and_then(|duration| u64::try_from(duration.as_millis()).ok())
        .ok_or_else(|| error(PlatformErrorCode::Internal, "invalid-system-clock"))
}

fn error(code: PlatformErrorCode, reason: &str) -> PlatformError {
    PlatformError {
        code,
        message: reason.to_owned(),
        retryable: matches!(
            code,
            PlatformErrorCode::Unavailable | PlatformErrorCode::StateConflict
        ),
        details: vec![ErrorDetail {
            kind: "deployment-catalog".to_owned(),
            fields: Metadata::from([("reason".to_owned(), reason.to_owned())]),
        }],
    }
}

fn manifest_error(violations: Vec<ManifestViolation>) -> PlatformError {
    let code = if violations
        .iter()
        .any(|v| v.code.contains("scope") || v.code == "namespace-requires-tenant")
    {
        PlatformErrorCode::PermissionDenied
    } else {
        PlatformErrorCode::InvalidArgument
    };
    PlatformError {
        code,
        message: "deployment or release failed Phase 1 validation".to_owned(),
        retryable: false,
        details: violations
            .into_iter()
            .map(|violation| ErrorDetail {
                kind: "manifest-violation".to_owned(),
                fields: Metadata::from([
                    ("path".to_owned(), violation.path),
                    ("code".to_owned(), violation.code),
                ]),
            })
            .collect(),
    }
}
