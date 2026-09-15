use super::super::{DirectoryDeploymentRepository, PinnedRouteResolver, PublicationView};
use crate::http_routes::{capacity, conflict, corrupt, TriggerReadLease, MAX_DEFINITION_BYTES};
use latent_artifacts::PublicationRef;
use latent_core::{DeploymentId, FunctionId, PlatformError, PlatformErrorCode, TriggerId};
use latent_ingress::http::{CanonicalTarget, Method};
use latent_manifest::TriggerManifest;
use latent_routing::{InvocationTarget, ResolvedRevision, RevisionPolicySource};
use std::sync::Arc;

/// One accepted request's exact target. It cannot select another HTTP request.
/// The lease covers the copied target while the catalog owns shared route data.
pub struct AcceptedHttpRoute {
    trigger: TriggerId,
    trigger_generation: u64,
    state_version: u64,
    revision: ResolvedRevision,
    catalog: PinnedRouteResolver,
    lease: TriggerReadLease,
}
impl AcceptedHttpRoute {
    #[must_use]
    pub fn trigger(&self) -> &TriggerId {
        &self.trigger
    }
    #[must_use]
    pub fn trigger_generation(&self) -> u64 {
        self.trigger_generation
    }
    #[must_use]
    pub fn state_version(&self) -> u64 {
        self.state_version
    }
    #[must_use]
    pub fn revision(&self) -> &ResolvedRevision {
        &self.revision
    }
    #[must_use]
    pub fn catalog(&self) -> &PinnedRouteResolver {
        &self.catalog
    }
    #[must_use]
    pub fn into_parts(self) -> (ResolvedRevision, PinnedRouteResolver, TriggerReadLease) {
        (self.revision, self.catalog, self.lease)
    }
}
impl DirectoryDeploymentRepository {
    /// The coherent publication capture is this request's selection boundary.
    /// A stale specific match denies; it never falls back to a broader path.
    pub fn select_http(
        &self,
        target: &CanonicalTarget,
        method: Method,
    ) -> Result<AcceptedHttpRoute, PlatformError> {
        let previous = self.invocation_catalog()?.capture();
        if !previous.confirmed {
            return Err(super::unavailable());
        }
        let (index, row) = previous
            .http
            .rows
            .iter()
            .enumerate()
            .filter(|(_, row)| row.matcher.matches(target, method))
            .max_by_key(|(_, row)| row.matcher.precedence())
            .ok_or_else(|| {
                super::super::error(PlatformErrorCode::RouteUnavailable, "http-route-not-found")
            })?;
        let bytes = Self::http_target_bytes(&previous, &row.manifest)?;
        let lease = self
            .http_budget
            .read_with_scratch(bytes + MAX_DEFINITION_BYTES, 16 * 1024)?;
        let (_, revision, catalog) = self.http_target(&previous, &row.manifest)?;
        if revision.release != previous.http.data.records[index].component {
            return Err(corrupt());
        }
        self.binding_generations.retain(&previous.routes)?;
        Ok(AcceptedHttpRoute {
            trigger: row.manifest.id.clone(),
            trigger_generation: previous.http.data.records[index].generation,
            state_version: previous.transaction,
            revision,
            catalog,
            lease,
        })
    }
    pub(super) fn http_target_bytes(
        view: &PublicationView,
        manifest: &TriggerManifest,
    ) -> Result<usize, PlatformError> {
        let id = DeploymentId(manifest.target.route.as_ref().ok_or_else(conflict)?.clone());
        let record = view.routes.record_by_id(&id).ok_or_else(conflict)?;
        let bytes = record.attributes.iter().fold(4096usize, |n, (k, v)| {
            n.saturating_add(k.capacity() + v.capacity() + 128)
        });
        if bytes > 64 * 1024 {
            return Err(capacity());
        }
        Ok(bytes)
    }
    pub(super) fn http_target(
        &self,
        view: &PublicationView,
        manifest: &TriggerManifest,
    ) -> Result<(PublicationRef, ResolvedRevision, PinnedRouteResolver), PlatformError> {
        Self::http_target_bytes(view, manifest)?;
        let tenant = manifest.metadata.tenant.as_ref().ok_or_else(conflict)?;
        let id = DeploymentId(manifest.target.route.as_ref().ok_or_else(conflict)?.clone());
        let record = view.routes.record_by_id(&id).ok_or_else(conflict)?;
        if record.deployment.metadata.tenant.as_ref() != Some(tenant)
            || record.deployment.service != manifest.target.service
            || record.publication != manifest.target.publication
            || Some(&record.revision.0) != manifest.target.revision.as_ref()
            || view.routes.versions.get(&id) != manifest.target.deployment_generation.as_ref()
        {
            return Err(conflict());
        }
        let publication = record
            .publication_reference(self.artifacts.as_ref())?
            .ok_or_else(conflict)?;
        if publication.scope.tenant() != Some(tenant) {
            return Err(conflict());
        }
        let target = InvocationTarget {
            tenant: tenant.clone(),
            service: manifest.target.service.clone(),
            contract: manifest.target.contract.clone(),
            function: FunctionId(manifest.target.function.clone()),
            route: manifest.target.route.clone(),
        };
        let resolved = view.routes.resolve(&target, None, self.config)?;
        if resolved.publication.as_ref() != Some(&publication.id)
            || resolved.revision != record.revision
            || resolved.release != record.deployment.release
        {
            return Err(conflict());
        }
        let catalog = PinnedRouteResolver {
            catalog: Arc::clone(&view.routes),
            config: self.config,
        };
        catalog.admission_policy(&resolved)?;
        Ok((publication, resolved, catalog))
    }
}
