use latent_core::{PlatformError, PlatformErrorCode};

use super::{error, DirectoryDeploymentRepository};
use crate::{ScopedRouteRequest, ScopedRouteSnapshot};

impl DirectoryDeploymentRepository {
    pub fn scoped_routes(
        &self,
        request: ScopedRouteRequest,
    ) -> Result<ScopedRouteSnapshot, PlatformError> {
        crate::scoped_routes::validate_request(&request)?;
        // Acquire only one immutable generation. No global snapshot is cloned.
        let catalog = self.read_catalog();
        let snapshot = &catalog.snapshot;
        if request
            .generation
            .is_some_and(|value| value != snapshot.generation)
        {
            return Err(error(
                PlatformErrorCode::NotFound,
                "route-generation-not-retained",
            ));
        }
        let start = snapshot
            .services
            .partition_point(|value| value.tenant.0 < request.tenant.0);
        let end = snapshot
            .services
            .partition_point(|value| value.tenant.0 <= request.tenant.0);
        crate::scoped_routes::project(request, snapshot, &snapshot.services[start..end])
    }
}
