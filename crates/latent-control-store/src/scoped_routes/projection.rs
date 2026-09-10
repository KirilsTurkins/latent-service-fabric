//! Preflight owned DTO copies directly from trusted, borrowed catalog records.

use std::mem::size_of;

use latent_core::{
    Metadata, PlatformError, PlatformErrorCode, ReleaseDigest, RevisionId, ServiceId, TenantId,
};
use latent_routing::{RevisionRoute, RouteSnapshot, ServiceRoute};

use super::{
    check_selection, digest, exhausted, failure, Cost, RouteReadLimits, ScopedRouteRequest,
    ScopedRouteSnapshot,
};

pub(crate) struct ProjectionCost<'a> {
    tenant: &'a TenantId,
    cost: Cost,
    revisions: usize,
}

impl<'a> ProjectionCost<'a> {
    pub(crate) fn new(
        tenant: &'a TenantId,
        services: usize,
        limits: RouteReadLimits,
    ) -> Result<Self, PlatformError> {
        if services > limits.maximum_services {
            return Err(exhausted());
        }
        let mut cost = Cost { used: 512, limits };
        // The request tenant is moved into the result, including its spare capacity.
        cost.string(&tenant.0, false)?;
        cost.items(services, size_of::<ServiceRoute>())?;
        Ok(Self {
            tenant,
            cost,
            revisions: 0,
        })
    }

    pub(crate) fn route(
        &mut self,
        tenant: &TenantId,
        service: &ServiceId,
        id: &str,
        revisions: usize,
    ) -> Result<(), PlatformError> {
        self.cost.text(&tenant.0, tenant.0.len(), false)?;
        self.cost.text(&service.0, service.0.len(), false)?;
        self.cost.text(id, id.len(), false)?;
        if tenant != self.tenant {
            return Err(failure(
                PlatformErrorCode::InvalidArgument,
                "route-tenant-mismatch",
            ));
        }
        self.revisions = self
            .revisions
            .checked_add(revisions)
            .ok_or_else(exhausted)?;
        if self.revisions > self.cost.limits.maximum_revisions {
            return Err(exhausted());
        }
        self.cost.items(revisions, size_of::<RevisionRoute>())
    }

    pub(crate) fn revision(
        &mut self,
        revision: &RevisionId,
        release: &ReleaseDigest,
        attributes: &Metadata,
    ) -> Result<(), PlatformError> {
        self.cost.text(&revision.0, revision.0.len(), true)?;
        self.cost.text(&release.0, release.0.len(), true)?;
        if attributes.len() > self.cost.limits.maximum_attributes_per_revision {
            return Err(exhausted());
        }
        self.cost.items(attributes.len(), 4096)?;
        for (key, value) in attributes {
            self.cost.text(key, key.len(), false)?;
            self.cost.text(value, value.len(), false)?;
        }
        Ok(())
    }
}

/// Checks actual constructed capacities too; source spare capacity is not retained by cloning.
pub(crate) fn finish_projection(
    request: ScopedRouteRequest,
    snapshot: RouteSnapshot,
) -> Result<ScopedRouteSnapshot, PlatformError> {
    let mut cost = Cost {
        used: check_selection(&request.tenant, &snapshot.services, request.limits)?,
        limits: request.limits,
    };
    cost.items(
        snapshot.services.capacity() - snapshot.services.len(),
        size_of::<ServiceRoute>(),
    )?;
    let snapshot_digest = digest::calculate(&request.tenant, &snapshot);
    cost.items(snapshot_digest.capacity().saturating_sub(71), 1)?;
    Ok(ScopedRouteSnapshot {
        tenant: request.tenant,
        snapshot,
        snapshot_digest,
        retained_bytes: cost.used,
    })
}
