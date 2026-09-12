//! Bounded isolated compilation and authenticated local native-output ownership.
//! Native loading and persistent cache recovery are separate from compilation.

mod identity;
mod limits;
pub(crate) mod ownership;
pub(crate) mod profile;
pub(crate) mod protocol;
pub(crate) mod sandbox;
mod seal;
pub(crate) mod supervisor;
mod worker;

pub use identity::AotCompatibilityKey;
pub use limits::AotCompilerLimits;
pub use ownership::{AotResourceLimits, AotResourceSnapshot};
pub use profile::ValidatedAotProfile;
pub use sandbox::SandboxLimits as AotSandboxLimits;
pub use seal::{TrustedAotCompilerAuthority, TrustedAotOutput};
pub use supervisor::{AotCompilationJob, AotJobControl, AotProcessLimits, IsolatedAotCompiler};
pub use worker::run_aot_compiler_worker;

use latent_core::{ArtifactBlobDigest, PlatformError, PlatformErrorCode};
use sha2::{Digest, Sha256};

/// Conservative per-output bound for fixed identities, scope, receipt and boxes.
/// The output-byte owner reserves this in addition to the native byte allowance.
pub(crate) const AOT_OUTPUT_METADATA_BYTES: usize = 16 * 1024;

fn error(code: PlatformErrorCode, message: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}
fn invalid() -> PlatformError {
    error(PlatformErrorCode::InvalidArgument, "invalid-aot-input")
}
fn exhausted() -> PlatformError {
    error(PlatformErrorCode::ResourceExhausted, "aot-resource-limit")
}
fn mismatch() -> PlatformError {
    error(
        PlatformErrorCode::PermissionDenied,
        "aot-output-authority-mismatch",
    )
}
fn frame(digest: &mut Sha256, bytes: &[u8]) {
    digest.update((bytes.len() as u64).to_le_bytes());
    digest.update(bytes);
}
fn blob(bytes: [u8; 32]) -> ArtifactBlobDigest {
    let mut text = String::with_capacity(71);
    text.push_str("sha256:");
    for byte in bytes {
        use std::fmt::Write as _;
        write!(&mut text, "{byte:02x}").expect("String formatting");
    }
    text.parse().expect("canonical SHA-256")
}

#[cfg(test)]
mod tests;
