//! Opaque protected-file provenance for the owning development stream node.
use super::{invalid, NodeConfig, StreamInstallation};
use latent_core::PlatformError;
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};

/// No Debug/Serde implementation: startup configuration contains credentials.
/// Only the protected loader creates this owner, and it retains no secret bytes.
pub struct StreamReloadGuard {
    path: PathBuf,
    static_digest: [u8; 32],
    startup_binding: [u8; 32],
}

fn static_digest(bytes: &[u8]) -> Result<[u8; 32], PlatformError> {
    let mut value: serde_json::Value =
        serde_json::from_slice(bytes).map_err(|_| invalid("streamReload.document"))?;
    for pointer in [
        "/providers/outboundStreams/identity/epoch",
        "/providers/outboundStreams/configuration/limits",
    ] {
        let field = value
            .pointer_mut(pointer)
            .ok_or_else(|| invalid("streamReload.installation"))?;
        *field = serde_json::Value::Null;
    }
    let canonical = serde_json::to_vec(&value).map_err(|_| invalid("streamReload.document"))?;
    Ok(Sha256::digest(canonical).into())
}

pub(super) fn capture(
    path: &Path,
    bytes: &[u8],
    config: &NodeConfig,
) -> Result<Option<StreamReloadGuard>, PlatformError> {
    if !cfg!(all(
        target_os = "linux",
        target_arch = "x86_64",
        feature = "development-outbound-streams"
    )) || config
        .providers
        .as_ref()
        .and_then(|p| p.outbound_streams.as_ref())
        .is_none()
    {
        return Ok(None);
    }
    Ok(Some(StreamReloadGuard {
        path: path.to_path_buf(),
        static_digest: static_digest(bytes)?,
        startup_binding: {
            let mut digest = Sha256::new();
            digest.update(path.as_os_str().as_encoded_bytes());
            digest.update([0]);
            digest.update(bytes);
            digest.finalize().into()
        },
    }))
}

impl StreamReloadGuard {
    pub(crate) fn binding(&self) -> [u8; 32] {
        self.startup_binding
    }

    #[cfg(feature = "development-outbound-streams")]
    pub(crate) fn belongs_to(&self, binding: Option<[u8; 32]>) -> bool {
        binding == Some(self.startup_binding)
    }

    /// Reopen through the maintained owner/mode/link/size checks. All other node
    /// fields, provider identities, exact destinations/resolution/address rules,
    /// and configured binding definitions stay exact. Only limits and epoch vary.
    pub fn replacement(&self) -> Result<StreamInstallation, PlatformError> {
        let (config, candidate) = super::input::load_with_stream_reload(&self.path)?;
        let candidate = candidate.ok_or_else(|| invalid("streamReload.profile-disabled"))?;
        if candidate.static_digest != self.static_digest {
            return Err(invalid("streamReload.static-configuration-changed"));
        }
        // Static settings were validated before this guard was bound to the
        // running node. Revalidate the provider input only: rederiving the whole
        // node would reopen unrelated TLS files and reconstruct immutable owners.
        // The same original feature/protected-input/profile/binding checks apply.
        super::providers::derive(&config)?
            .and_then(|p| p.outbound_streams)
            .ok_or_else(|| invalid("streamReload.installation"))
    }
}
