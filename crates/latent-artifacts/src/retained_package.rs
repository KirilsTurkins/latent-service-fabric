//! Sealed historical package bytes for bounded control-plane comparison.
use latent_core::{PackageDigest, ReleaseDigest, TenantId};

use crate::PackageAdmissionUpload;

/// Owned exact manifest, configuration and named layer bytes.
pub type RetainedPackageParts = (Vec<u8>, Vec<u8>, Vec<(String, Vec<u8>)>);

/// Exact retained package input, without detached evidence or execution authority.
/// Only a directory catalog that checked COMPLETE and all package/metadata
/// associations constructs this source. Consumers still inspect package semantics
/// and require current lifecycle/admission at their actual mutation boundary.
#[derive(Debug)]
pub struct RetainedPackageSource {
    pub(crate) tenant: TenantId,
    pub(crate) package: PackageDigest,
    pub(crate) component: ReleaseDigest,
    pub(crate) input: PackageAdmissionUpload,
}

impl RetainedPackageSource {
    #[must_use]
    pub fn tenant(&self) -> &TenantId {
        &self.tenant
    }
    #[must_use]
    pub fn package(&self) -> &PackageDigest {
        &self.package
    }
    #[must_use]
    pub fn component(&self) -> &ReleaseDigest {
        &self.component
    }

    /// Charges retained capacities, not just logical byte lengths.
    #[must_use]
    pub fn retained_bytes(&self) -> usize {
        self.input.layers.iter().fold(
            std::mem::size_of::<Self>()
                .saturating_add(self.tenant.0.capacity())
                .saturating_add(self.package.as_str().len())
                .saturating_add(self.component.0.capacity())
                .saturating_add(self.input.manifest.capacity())
                .saturating_add(self.input.configuration.capacity())
                .saturating_add(
                    self.input
                        .layers
                        .capacity()
                        .saturating_mul(std::mem::size_of::<(String, Vec<u8>)>()),
                ),
            |total, (path, bytes)| {
                total
                    .saturating_add(path.capacity())
                    .saturating_add(bytes.capacity())
            },
        )
    }

    /// Transfers raw package input without cloning the component or WIT sources.
    #[must_use]
    pub fn into_parts(self) -> RetainedPackageParts {
        (
            self.input.manifest,
            self.input.configuration,
            self.input.layers,
        )
    }
}
