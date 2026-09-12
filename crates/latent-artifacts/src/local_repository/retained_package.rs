use latent_core::{PlatformError, PlatformErrorCode, ReleaseDigest, TenantId};

use super::{
    admission, corrupt, error, resource_exhausted, DirectoryArtifactRepository, Retention,
};
use crate::{LifecycleScope, RetainedPackageSource};

impl DirectoryArtifactRepository {
    pub(super) fn retained_package(
        &self,
        tenant: &TenantId,
        release: &ReleaseDigest,
        maximum_bytes: usize,
    ) -> Result<Option<RetainedPackageSource>, PlatformError> {
        // Bound borrowed identities and the complete prospective retained source
        // before any directory read or copy. This is an explicit control read.
        if maximum_bytes == 0 || maximum_bytes > 64 * 1024 * 1024 {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "package-source-byte-limit",
            ));
        }
        if tenant.0.capacity() > 512 || release.0.capacity() > 71 {
            return Err(resource_exhausted("package-source-identity-limit"));
        }
        LifecycleScope::Tenant(tenant.clone()).validate()?;
        let _work = self
            .admission_work
            .try_lock()
            .map_err(|_| resource_exhausted("admission-work-busy"))?;
        let row = self.life_store().record(release)?;
        let Some(row) = row.filter(|value| value.scope.tenant() == Some(tenant)) else {
            return Ok(None);
        };
        let Some(expected_package) = row.package.as_ref() else {
            return Ok(None);
        };
        let directory = self.entry_path(release)?;
        let mut read_limits = self.repository_read_limits();
        read_limits.maximum_component_bytes =
            read_limits.maximum_component_bytes.min(maximum_bytes);
        let verified =
            self.load_complete_entry_with_limits(&directory, Retention::Metadata, read_limits)?;
        self.verify_admission_index(release, &verified)?;
        let stored = verified
            .admission
            .as_ref()
            .ok_or_else(|| corrupt("retained-package-missing"))?;
        let limits = self
            .admission
            .as_ref()
            .ok_or_else(|| corrupt("retained-package-mode"))?
            .limits;
        let binding = stored.binding(&directory, limits)?;
        if &binding.tenant != tenant
            || &binding.release != release
            || &binding.package != expected_package
        {
            return Err(corrupt("retained-package-source-identity"));
        }
        let input = stored.package_input(&directory, maximum_bytes)?;
        admission::association::verify(&binding, &input, &verified.metadata, &self.codec)?;
        let source = RetainedPackageSource {
            tenant: binding.tenant,
            package: binding.package,
            component: binding.release,
            input,
        };
        if source.retained_bytes() > maximum_bytes {
            return Err(resource_exhausted("package-source-retention-limit"));
        }
        Ok(Some(source))
    }
}
