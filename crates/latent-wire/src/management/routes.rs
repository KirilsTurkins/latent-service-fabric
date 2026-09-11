use latent_control_store::{RouteReadLimits, ScopedRouteRequest, ScopedRouteSnapshot};
use latent_core::RouteGeneration;
use tonic::{Request, Response, Status};

use super::{errors, proto, ManagementOperation, ManagementServiceAdapter, RequestBudget};

#[tonic::async_trait]
impl proto::route_service_server::RouteService for ManagementServiceAdapter {
    type WatchRouteSnapshotsStream = tonic::codegen::BoxStream<proto::RouteSnapshot>;

    async fn get_route_snapshot(
        &self,
        mut request: Request<proto::GetRouteSnapshotRequest>,
    ) -> Result<Response<proto::GetRouteSnapshotResponse>, Status> {
        let principal = self.authenticate(&mut request, ManagementOperation::Tenant)?;
        RequestBudget::new::<proto::GetRouteSnapshotRequest>(&self.limits)?;
        self.check_encoded(request.get_ref())?;
        let tenant = principal.tenant.expect("authenticated tenant");
        let generation = request.into_inner().generation.map(RouteGeneration);
        let limits = RouteReadLimits {
            maximum_services: self.limits.max_route_services,
            maximum_revisions: self.limits.max_route_revisions,
            maximum_attributes_per_revision: self.limits.max_metadata_entries,
            maximum_string_bytes: self.limits.max_string_bytes,
            maximum_bytes: self.limits.max_response_bytes,
        };
        let result = self
            .services
            .routes
            .scoped(ScopedRouteRequest {
                tenant: tenant.clone(),
                generation,
                limits,
            })
            .await
            .map_err(|error| errors::platform_status(error, &self.limits))?;
        result
            .validate(limits)
            .map_err(|error| errors::platform_status(error, &self.limits))?;
        if result.tenant != tenant
            || generation.is_some_and(|value| value != result.snapshot.generation)
        {
            return Err(Status::internal("invalid scoped route response"));
        }
        let mut budget =
            RequestBudget::for_response::<proto::GetRouteSnapshotResponse>(&self.limits)?;
        budget.string(&result.tenant.0, self.limits.max_id_bytes)?;
        budget.string(&result.snapshot_digest, self.limits.max_id_bytes.max(71))?;
        budget.sequence(&result.snapshot.services, self.limits.max_route_services)?;
        for service in &result.snapshot.services {
            budget.string(&service.id.0, self.limits.max_string_bytes)?;
            budget.string(&service.service.0, self.limits.max_id_bytes)?;
            budget.string(&service.tenant.0, self.limits.max_id_bytes)?;
            budget.sequence(&service.revisions, self.limits.max_route_revisions)?;
            for revision in &service.revisions {
                budget.string(&revision.revision.0, self.limits.max_id_bytes.max(83))?;
                budget.string(&revision.release.0, self.limits.max_id_bytes.max(71))?;
                budget.btree_metadata(&revision.attributes, &self.limits)?;
            }
        }
        self.response(proto::GetRouteSnapshotResponse {
            snapshot: Some(to_proto(result)),
        })
    }

    async fn watch_route_snapshots(
        &self,
        _request: Request<proto::WatchRouteSnapshotsRequest>,
    ) -> Result<Response<Self::WatchRouteSnapshotsStream>, Status> {
        Err(Status::unimplemented(
            "route watches are not supported by a standalone node",
        ))
    }
}

fn to_proto(value: ScopedRouteSnapshot) -> proto::RouteSnapshot {
    proto::RouteSnapshot {
        generation: value.snapshot.generation.0,
        generated_at_unix_millis: value.snapshot.generated_at_unix_millis,
        services: value
            .snapshot
            .services
            .into_iter()
            .map(|service| proto::ServiceRoute {
                route_id: service.id.0,
                service: service.service.0,
                tenant: service.tenant.0,
                revisions: service
                    .revisions
                    .into_iter()
                    .map(|revision| proto::RevisionRoute {
                        revision_id: revision.revision.0,
                        release_digest: revision.release.0,
                        weight: u32::from(revision.weight),
                        attributes: revision.attributes.into_iter().collect(),
                    })
                    .collect(),
            })
            .collect(),
        bindings: Vec::new(),
        policy_digests: Vec::new(),
        snapshot_digest: value.snapshot_digest,
        tenant: Some(value.tenant.0),
    }
}
