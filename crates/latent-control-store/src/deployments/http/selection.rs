use super::super::{DirectoryDeploymentRepository, PinnedRouteResolver, PublicationView};
use crate::http_routes::{
    capacity, conflict, corrupt, definition::reserved_node_path, TriggerReadLease,
    TriggerTargetIdentity, MAX_DEFINITION_BYTES,
};
use latent_artifacts::{web::WebSelection, PublicationRef};
use latent_core::{DeploymentId, FunctionId, PlatformError, PlatformErrorCode, TriggerId};
use latent_ingress::http::{CanonicalTarget, Method};
use latent_manifest::{TriggerManifest, TriggerTarget};
use latent_routing::{InvocationTarget, ResolvedRevision, RevisionPolicySource};
use std::sync::Arc;

/// The selected authority variant is explicit. A static route never fabricates
/// an invocation revision, and an application route never carries web layout authority.
pub enum AcceptedHttpTarget {
    Application {
        revision: ResolvedRevision,
        catalog: PinnedRouteResolver,
    },
    StaticWeb {
        publication: PublicationRef,
        selection: WebSelection,
        mount_path: String,
        site_path: String,
    },
}
impl AcceptedHttpTarget {
    #[must_use]
    pub const fn revision(&self) -> Option<&ResolvedRevision> {
        match self {
            Self::Application { revision, .. } => Some(revision),
            Self::StaticWeb { .. } => None,
        }
    }
    #[must_use]
    pub const fn catalog(&self) -> Option<&PinnedRouteResolver> {
        match self {
            Self::Application { catalog, .. } => Some(catalog),
            Self::StaticWeb { .. } => None,
        }
    }
    #[must_use]
    pub const fn web_selection(&self) -> Option<&WebSelection> {
        match self {
            Self::Application { .. } => None,
            Self::StaticWeb { selection, .. } => Some(selection),
        }
    }
}

/// One accepted request's exact target. It cannot select another HTTP request.
/// The lease covers copied route metadata; static selection additionally owns
/// the web catalog's bounded current-admission lease.
pub struct AcceptedHttpRoute {
    trigger: TriggerId,
    trigger_generation: u64,
    state_version: u64,
    target: AcceptedHttpTarget,
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
    pub const fn target(&self) -> &AcceptedHttpTarget {
        &self.target
    }
    #[must_use]
    pub fn revision(&self) -> Option<&ResolvedRevision> {
        self.target.revision()
    }
    #[must_use]
    pub fn catalog(&self) -> Option<&PinnedRouteResolver> {
        self.target.catalog()
    }
    #[must_use]
    pub fn into_parts(self) -> (AcceptedHttpTarget, TriggerReadLease) {
        (self.target, self.lease)
    }
}

impl DirectoryDeploymentRepository {
    /// The coherent publication capture is this request's selection boundary.
    /// A stale winning match denies; it never falls back to a broader path.
    pub fn select_http(
        &self,
        request_target: &CanonicalTarget,
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
            .filter(|(_, row)| row.matcher.matches(request_target, method))
            .max_by_key(|(_, row)| row.matcher.precedence())
            .ok_or_else(|| {
                super::super::error(PlatformErrorCode::RouteUnavailable, "http-route-not-found")
            })?;
        let lease = self
            .http_budget
            .read_with_scratch(MAX_DEFINITION_BYTES + 64 * 1024, 16 * 1024)?;
        let target = match &row.target {
            expected @ TriggerTargetIdentity::Application { component, .. } => {
                let (_, revision, catalog) = self.http_target(&previous, &row.manifest)?;
                if &revision.release != component
                    || previous.http.data.records[index].generation == 0
                    || &previous.http.rows[index].target != expected
                {
                    return Err(corrupt());
                }
                self.binding_generations.retain(&previous.routes)?;
                AcceptedHttpTarget::Application { revision, catalog }
            }
            expected @ TriggerTargetIdentity::StaticWeb {
                publication,
                web_manifest_digest,
                assets_digest,
                web_generation,
            } => {
                if reserved_node_path(request_target.path()) {
                    return Err(super::super::error(
                        PlatformErrorCode::RouteUnavailable,
                        "http-static-reserved-node-path",
                    ));
                }
                let site_path = row.matcher.site_path(request_target).ok_or_else(corrupt)?;
                let selection = self.artifacts.select_web_publication(publication)?;
                if selection.publication() != publication
                    || selection.layout().manifest().static_routing.is_none()
                    || selection.layout().manifest_digest().as_str() != web_manifest_digest
                    || selection.layout().assets_digest().as_str() != assets_digest
                    || selection.eligibility().generation() != *web_generation
                    || &previous.http.rows[index].target != expected
                {
                    return Err(conflict());
                }
                AcceptedHttpTarget::StaticWeb {
                    publication: publication.clone(),
                    selection,
                    mount_path: row.matcher.path.clone(),
                    site_path,
                }
            }
        };
        Ok(AcceptedHttpRoute {
            trigger: row.manifest.id.clone(),
            trigger_generation: previous.http.data.records[index].generation,
            state_version: previous.transaction,
            target,
            lease,
        })
    }

    pub(super) fn http_target_bytes(
        view: &PublicationView,
        manifest: &TriggerManifest,
    ) -> Result<usize, PlatformError> {
        let TriggerTarget::Application(target) = &manifest.target else {
            return Err(conflict());
        };
        let id = DeploymentId(target.route.as_ref().ok_or_else(conflict)?.clone());
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
        let TriggerTarget::Application(manifest_target) = &manifest.target else {
            return Err(conflict());
        };
        let id = DeploymentId(manifest_target.route.as_ref().ok_or_else(conflict)?.clone());
        let record = view.routes.record_by_id(&id).ok_or_else(conflict)?;
        if record.deployment.metadata.tenant.as_ref() != Some(tenant)
            || record.deployment.service != manifest_target.service
            || record.publication.as_ref() != manifest_target.publication.as_ref()
            || Some(&record.revision.0) != manifest_target.revision.as_ref()
            || view.routes.versions.get(&id) != manifest_target.deployment_generation.as_ref()
        {
            return Err(conflict());
        }
        let publication = record
            .publication_reference(self.artifacts.as_ref())?
            .ok_or_else(conflict)?;
        if publication.scope.tenant() != Some(tenant) {
            return Err(conflict());
        }
        let invocation_target = InvocationTarget {
            tenant: tenant.clone(),
            service: manifest_target.service.clone(),
            contract: manifest_target.contract.clone(),
            function: FunctionId(manifest_target.function.clone()),
            route: manifest_target.route.clone(),
        };
        let resolved = view.routes.resolve(&invocation_target, None, self.config)?;
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
