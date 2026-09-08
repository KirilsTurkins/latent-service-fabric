//! Complete tenant projections with bounded materialization and scoped integrity.

mod digest;

use std::mem::size_of;

use latent_core::{PlatformError, PlatformErrorCode, RouteGeneration, TenantId};
use latent_routing::{RevisionRoute, RouteSnapshot, ServiceRoute};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RouteReadLimits {
    pub maximum_services: usize,
    pub maximum_revisions: usize,
    pub maximum_attributes_per_revision: usize,
    pub maximum_string_bytes: usize,
    /// Conservative retained allocation cost, including owned spare capacity.
    pub maximum_bytes: usize,
}

impl RouteReadLimits {
    pub fn validate(&self) -> Result<(), PlatformError> {
        if self.maximum_services == 0
            || self.maximum_revisions == 0
            || self.maximum_attributes_per_revision == 0
            || self.maximum_string_bytes == 0
            || self.maximum_bytes < 512
            || self.maximum_bytes > isize::MAX as usize
        {
            return Err(failure(
                PlatformErrorCode::InvalidArgument,
                "invalid-route-read-limits",
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ScopedRouteRequest {
    pub tenant: TenantId,
    pub generation: Option<RouteGeneration>,
    pub limits: RouteReadLimits,
}

/// The complete current tenant projection, never a truncated global snapshot.
/// `snapshot_digest` uses the `latent.scoped-routes.v1` framed SHA-256 encoding.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ScopedRouteSnapshot {
    pub tenant: TenantId,
    pub snapshot: RouteSnapshot,
    pub snapshot_digest: String,
    pub retained_bytes: usize,
}

impl ScopedRouteSnapshot {
    /// Validate an injected source before converting or returning its projection.
    pub fn validate(&self, limits: RouteReadLimits) -> Result<(), PlatformError> {
        limits.validate()?;
        validate_tenant(&self.tenant, limits)?;
        if !self.snapshot.bindings.is_empty() || !self.snapshot.policy_digests.is_empty() {
            return Err(unsupported());
        }
        let mut cost = Cost {
            used: check_selection(&self.tenant, &self.snapshot.services, limits)?,
            limits,
        };
        cost.items(
            self.snapshot.services.capacity() - self.snapshot.services.len(),
            size_of::<ServiceRoute>(),
        )?;
        cost.items(
            self.snapshot.bindings.capacity(),
            size_of::<latent_routing::BindingRoute>(),
        )?;
        cost.items(self.snapshot.policy_digests.capacity(), size_of::<String>())?;
        cost.items(self.snapshot_digest.capacity().saturating_sub(71), 1)?;
        if self.snapshot.services.capacity() > limits.maximum_services
            || self.snapshot_digest.capacity() > limits.maximum_bytes
            || self.snapshot_digest.len() != 71
            || self.retained_bytes < cost.used
            || self.retained_bytes > limits.maximum_bytes
            || self.snapshot_digest != digest::calculate(&self.tenant, &self.snapshot)
        {
            return Err(failure(
                PlatformErrorCode::InvalidArgument,
                "invalid-scoped-route-snapshot",
            ));
        }
        Ok(())
    }
}

pub(crate) fn validate_request(request: &ScopedRouteRequest) -> Result<(), PlatformError> {
    request.limits.validate()?;
    validate_tenant(&request.tenant, request.limits)
}

fn validate_tenant(tenant: &TenantId, limits: RouteReadLimits) -> Result<(), PlatformError> {
    if tenant.0.capacity() > limits.maximum_bytes
        || tenant.0.is_empty()
        || tenant.0.len() > limits.maximum_string_bytes
        || tenant
            .0
            .chars()
            .any(|value| value.is_control() || value.is_whitespace())
    {
        return Err(failure(
            PlatformErrorCode::InvalidArgument,
            "invalid-route-tenant",
        ));
    }
    Ok(())
}

pub(crate) fn project(
    request: ScopedRouteRequest,
    snapshot: &RouteSnapshot,
    services: &[ServiceRoute],
) -> Result<ScopedRouteSnapshot, PlatformError> {
    if !snapshot.bindings.is_empty() || !snapshot.policy_digests.is_empty() {
        return Err(unsupported());
    }
    let retained_bytes = check_selection(&request.tenant, services, request.limits)?;
    let snapshot = RouteSnapshot {
        generation: snapshot.generation,
        generated_at_unix_millis: snapshot.generated_at_unix_millis,
        services: services.to_vec(),
        bindings: Vec::new(),
        policy_digests: Vec::new(),
    };
    let snapshot_digest = digest::calculate(&request.tenant, &snapshot);
    Ok(ScopedRouteSnapshot {
        tenant: request.tenant,
        snapshot,
        snapshot_digest,
        retained_bytes,
    })
}

fn check_selection(
    tenant: &TenantId,
    services: &[ServiceRoute],
    limits: RouteReadLimits,
) -> Result<usize, PlatformError> {
    if services.len() > limits.maximum_services {
        return Err(exhausted());
    }
    let mut cost = Cost { used: 512, limits };
    cost.string(&tenant.0, false)?;
    cost.items(services.len(), size_of::<ServiceRoute>())?;
    let mut revisions = 0_usize;
    for service in services {
        cost.string(&service.tenant.0, false)?;
        cost.string(&service.service.0, false)?;
        cost.string(&service.id.0, false)?;
        if service.tenant != *tenant {
            return Err(failure(
                PlatformErrorCode::InvalidArgument,
                "route-tenant-mismatch",
            ));
        }
        revisions = revisions
            .checked_add(service.revisions.len())
            .ok_or_else(exhausted)?;
        if revisions > limits.maximum_revisions {
            return Err(exhausted());
        }
        cost.items(service.revisions.capacity(), size_of::<RevisionRoute>())?;
        for revision in &service.revisions {
            cost.string(&revision.revision.0, true)?;
            cost.string(&revision.release.0, true)?;
            if revision.attributes.len() > limits.maximum_attributes_per_revision {
                return Err(exhausted());
            }
            // Bound BTreeMap node/slack costs conservatively before traversing it.
            cost.items(revision.attributes.len(), 4096)?;
            for (key, value) in &revision.attributes {
                cost.string(key, false)?;
                cost.string(value, false)?;
            }
        }
    }
    if services
        .windows(2)
        .any(|pair| (&pair[0].service.0, &pair[0].id.0) >= (&pair[1].service.0, &pair[1].id.0))
    {
        return Err(failure(
            PlatformErrorCode::InvalidArgument,
            "unordered-scoped-routes",
        ));
    }
    Ok(cost.used)
}

struct Cost {
    used: usize,
    limits: RouteReadLimits,
}
impl Cost {
    fn items(&mut self, count: usize, size: usize) -> Result<(), PlatformError> {
        self.used = count
            .checked_mul(size)
            .and_then(|bytes| self.used.checked_add(bytes))
            .filter(|bytes| *bytes <= self.limits.maximum_bytes)
            .ok_or_else(exhausted)?;
        Ok(())
    }
    fn string(&mut self, text: &String, generated: bool) -> Result<(), PlatformError> {
        let bound = if generated {
            self.limits.maximum_string_bytes.max(83)
        } else {
            self.limits.maximum_string_bytes
        };
        if text.len() > bound {
            return Err(exhausted());
        }
        self.items(text.capacity(), 1)
    }
}

fn exhausted() -> PlatformError {
    failure(
        PlatformErrorCode::ResourceExhausted,
        "scoped-route-read-limit",
    )
}
fn unsupported() -> PlatformError {
    failure(
        PlatformErrorCode::IncompatibleContract,
        "scoped-routes-unsupported",
    )
}
fn failure(code: PlatformErrorCode, message: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}
