#[path = "projection.rs"]
mod projection;

use latent_core::PlatformError;

use super::DirectoryDeploymentRepository;
use crate::{ScopedRouteRequest, ScopedRouteSnapshot};

impl DirectoryDeploymentRepository {
    pub fn scoped_routes(
        &self,
        request: ScopedRouteRequest,
    ) -> Result<ScopedRouteSnapshot, PlatformError> {
        crate::scoped_routes::validate_request(&request)?;
        // Acquire only one immutable generation, then visit the selected tenant.
        self.read_catalog().scoped_snapshot(request)
    }
}
