//! Bounded immutable package format. Validation establishes layout and content
//! associations, never publisher trust, semantic guest validity, or admission.

mod codec;
mod limits;
mod model;
mod parse;
mod paths;
mod validate;
mod wit_lock;

pub use codec::{
    decode_config, decode_manifest, decode_referrer, encode_config, encode_manifest,
    encode_referrer, inspect_package, verify_layer_bytes, PackageLayout,
};
pub use limits::PackageLimits;
pub use model::{
    ArtifactDescriptor, EvidenceKind, LayerRole, PackageConfig, PackageKind, PackageLayer,
    PackageManifest, PackageSubject, ReferrerManifest,
};
pub use wit_lock::{
    decode_wit_lock, encode_wit_lock, validate_wit_lock, WitLock, WitLockedPackage,
};

use latent_core::{ArtifactBlobDigest, PackageDigest, PlatformError, PlatformErrorCode};
use sha2::{Digest, Sha256};

pub const OCI_MANIFEST_MEDIA_TYPE: &str = "application/vnd.oci.image.manifest.v1+json";
pub const PACKAGE_CONFIG_MEDIA_TYPE: &str = "application/vnd.latent.package.config.v1+json";
pub const EMPTY_CONFIG_MEDIA_TYPE: &str = "application/vnd.oci.empty.v1+json";
pub const COMPONENT_MEDIA_TYPE: &str = "application/wasm";
pub const CAPSULE_MANIFEST_MEDIA_TYPE: &str = "application/vnd.latent.capsule.manifest.v1+json";
pub const CONTRACTS_MEDIA_TYPE: &str = "application/vnd.latent.contracts.v1+json";
pub const WIT_LOCK_MEDIA_TYPE: &str = "application/vnd.latent.wit-lock.v1+json";
pub const LAYER_PATH_ANNOTATION: &str = "org.opencontainers.image.title";
pub const LAYER_ROLE_ANNOTATION: &str = "dev.latent.layer.role";

/// Content identity of the exact received manifest bytes, without normalization.
#[must_use]
pub fn package_digest(bytes: &[u8]) -> PackageDigest {
    format!("sha256:{:x}", Sha256::digest(bytes))
        .parse()
        .expect("SHA-256")
}

/// Content identity of raw config or layer bytes. No archive extraction is implied.
#[must_use]
pub fn artifact_blob_digest(bytes: &[u8]) -> ArtifactBlobDigest {
    format!("sha256:{:x}", Sha256::digest(bytes))
        .parse()
        .expect("SHA-256")
}

fn invalid(reason: &'static str) -> PlatformError {
    failure(PlatformErrorCode::InvalidArgument, reason)
}
fn exceeded(reason: &'static str) -> PlatformError {
    failure(PlatformErrorCode::ResourceExhausted, reason)
}
fn corrupt(reason: &'static str) -> PlatformError {
    failure(PlatformErrorCode::CorruptArtifact, reason)
}
fn failure(code: PlatformErrorCode, reason: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: reason.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}
