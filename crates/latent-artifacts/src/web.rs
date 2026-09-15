//! Exact web-package associations. Checked layout is historical metadata, never
//! a publisher proof, tenant admission, renderer permit or permission to serve.

mod admission;
mod build_outputs;
pub(crate) mod codec;
mod eligibility;
mod lifecycle;
mod model;
mod read;
#[cfg(test)]
mod tests;
#[cfg(test)]
pub(crate) use tests::browser_test_upload;
mod validate;

pub use admission::{VerifiedWebAdmission, WebAdmissionBinding, WebAdmissionGrant};
pub use build_outputs::{web_build_outputs, WebBuildOutputs};
pub use eligibility::WebUseEligibility;
pub(crate) use eligibility::{WebEpoch, WebGeneration};
pub use lifecycle::{
    WebLifecycleRecord, WebMutationResult, WebOperationReceipt, WebPublicationStatus,
};
pub use model::{
    CheckedWebLayout, WebApplicationManifest, WebAsset, WebRenderMode, WebRenderer,
    WebRendererProfile, WebRoute,
};
pub use read::{WebBlobRead, WebReadLimits, WebReadSnapshot, WebSelection};
pub(crate) use read::{WebReadBudget, WebReadPermit};
pub use validate::{asset_tree_digest, inspect_web_layout, renderer_profile_digest};

use latent_core::{PlatformError, PlatformErrorCode};

pub const WEB_MANIFEST_PATH: &str = "metadata/web-application.json";
pub const WEB_RELEASE_PROFILE: &str = "lsf.web-release.v1";
pub const WEB_CONTRACT: &str = "latent:web/application@0.1.0";
pub const WEB_WORLD: &str = "latent:web/application-service@0.1.0";
pub const IMMUTABLE_ASSET_PREFIX: &str = "/_lsf/assets/";
pub const MAX_WEB_MANIFEST_BYTES: usize = 64 * 1024;
pub const MAX_WEB_ASSETS: usize = 128;
pub const MAX_WEB_ROUTES: usize = 128;
pub const MAX_WEB_ASSET_BYTES: u64 = 8 * 1024 * 1024;
pub const MAX_WEB_ASSET_TREE_BYTES: u64 = 16 * 1024 * 1024;
pub const MAX_WEB_RENDERER_BYTES: u64 = 32 * 1024 * 1024;

fn invalid(reason: &'static str) -> PlatformError {
    failure(PlatformErrorCode::InvalidArgument, reason)
}

fn exhausted() -> PlatformError {
    failure(PlatformErrorCode::ResourceExhausted, "web-profile-limit")
}

pub(crate) fn incompatible() -> PlatformError {
    failure(
        PlatformErrorCode::IncompatibleContract,
        "web-profile-incompatible",
    )
}

fn failure(code: PlatformErrorCode, reason: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: reason.into(),
        retryable: false,
        details: Vec::new(),
    }
}
