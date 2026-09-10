//! Owned public DTOs are created only at their explicit management boundary.

use latent_core::{PlatformError, PlatformErrorCode, RouteId};
use latent_routing::{RevisionRoute, RouteSnapshot, ServiceRoute};

use super::super::compiler::{CompiledCatalog, RouteView};
use super::super::error;
use crate::scoped_routes::{finish_projection, ProjectionCost};
use crate::{ScopedRouteRequest, ScopedRouteSnapshot};

impl CompiledCatalog {
    pub(in crate::deployments) fn snapshot(&self) -> RouteSnapshot {
        self.project(self.route_views())
    }

    pub(in crate::deployments) fn matches_snapshot(&self, supplied: &RouteSnapshot) -> bool {
        supplied.generation == self.generation
            && supplied.generated_at_unix_millis == self.generated_at_unix_millis
            && supplied.bindings.is_empty()
            && supplied.policy_digests.is_empty()
            && supplied.services.len() == self.route_views().len()
            && self
                .route_views()
                .zip(&supplied.services)
                .all(|(route, supplied)| {
                    route.id() == supplied.id.0
                        && route.tenant() == &supplied.tenant
                        && route.service() == &supplied.service
                        && route.revisions().len() == supplied.revisions.len()
                        && route
                            .revisions()
                            .zip(&supplied.revisions)
                            .all(|(record, revision)| {
                                record.revision == revision.revision
                                    && record.deployment.release == revision.release
                                    && record.deployment.route_weight == revision.weight
                                    && record.attributes == revision.attributes
                            })
                })
    }

    pub(in crate::deployments) fn scoped_snapshot(
        &self,
        request: ScopedRouteRequest,
    ) -> Result<ScopedRouteSnapshot, PlatformError> {
        if request
            .generation
            .is_some_and(|generation| generation != self.generation)
        {
            return Err(error(
                PlatformErrorCode::NotFound,
                "route-generation-not-retained",
            ));
        }
        let routes = self.tenant_routes(&request.tenant);
        let mut cost = ProjectionCost::new(&request.tenant, routes.len(), request.limits)?;
        for route in routes {
            cost.route(
                route.tenant(),
                route.service(),
                route.id(),
                route.revisions().len(),
            )?;
            for record in route.revisions() {
                cost.revision(
                    &record.revision,
                    &record.deployment.release,
                    &record.attributes,
                )?;
            }
        }
        let snapshot = self.project(self.tenant_routes(&request.tenant));
        finish_projection(request, snapshot)
    }

    fn project<'a>(&self, routes: impl ExactSizeIterator<Item = RouteView<'a>>) -> RouteSnapshot {
        let mut services = Vec::with_capacity(routes.len());
        services.extend(routes.map(service));
        RouteSnapshot {
            generation: self.generation,
            generated_at_unix_millis: self.generated_at_unix_millis,
            services,
            bindings: Vec::new(),
            policy_digests: Vec::new(),
        }
    }
}

fn service(route: RouteView<'_>) -> ServiceRoute {
    let rows = route.revisions();
    let mut revisions = Vec::with_capacity(rows.len());
    revisions.extend(rows.map(|record| RevisionRoute {
        revision: record.revision.clone(),
        release: record.deployment.release.clone(),
        weight: record.deployment.route_weight,
        attributes: record.attributes.clone(),
    }));
    ServiceRoute {
        id: RouteId(route.id().to_owned()),
        tenant: route.tenant().clone(),
        service: route.service().clone(),
        revisions,
    }
}
