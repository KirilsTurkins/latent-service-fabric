//! Deterministic packaging of supplied bytes without compiling or invoking guests.
//! Checked content and type associations establish neither trust nor admission.

#![forbid(unsafe_code)]

mod assembly;
mod bundle;
mod directory;
mod input;
mod receipt;
mod sbom;
mod semantics;

pub use assembly::build_package;
pub use bundle::{inspect_bundle, BundleInput, PackageBlob, PackageBundle};
pub use directory::{
    decode_package_source, read_package_directory, read_package_input, write_package_directory,
};
pub use input::{LayerInput, PackageFile, PackageInput, PackageSource, PackagingLimits};
pub use receipt::{BuildInputIdentity, BuildReceipt, BUILD_INPUTS_PATH};
pub use sbom::{
    generate_cyclonedx_sbom, inspect_cyclonedx_sbom, SbomDocument, SbomEntryKind, SbomInspection,
    SbomInventory, SbomInventoryEntry, SbomLimits, CYCLONEDX_JSON_MEDIA_TYPE,
    CYCLONEDX_SPEC_VERSION,
};
pub use semantics::{validate_capsule, CheckedSurface, SemanticLimits, SurfaceCounts};

use latent_core::{PlatformError, PlatformErrorCode};

fn invalid(reason: &'static str) -> PlatformError {
    error(PlatformErrorCode::InvalidArgument, reason)
}
fn exceeded(reason: &'static str) -> PlatformError {
    error(PlatformErrorCode::ResourceExhausted, reason)
}
fn error(code: PlatformErrorCode, reason: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: reason.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}
