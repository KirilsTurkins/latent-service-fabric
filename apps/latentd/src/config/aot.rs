//! Explicit isolated compilation settings; no native key material in JSON.
mod key;
mod limits;
mod model;
mod paths;
#[cfg(test)]
mod tests;

use latent_artifacts::DirectoryArtifactRepositoryConfig;
use latent_core::{ArtifactBlobDigest, PlatformError, PlatformErrorCode};
use latent_wasmtime::{NativeAotSettings, TrustedAotCompilerAuthority};
use serde::{Deserialize, Deserializer};
use std::path::Path;

use super::{invalid, NodeConfig};
pub use model::{AotCacheConfig, AotImageConfig, AotProcessConfig, IsolatedAotConfig};

pub(super) fn present<'de, D: Deserializer<'de>>(
    decoder: D,
) -> Result<Option<IsolatedAotConfig>, D::Error> {
    IsolatedAotConfig::deserialize(decoder).map(Some)
}

pub(super) fn anchor(config: &mut IsolatedAotConfig, parent: &Path) -> Result<(), PlatformError> {
    paths::check(&config.compiler_executable, true)?;
    for path in [
        &mut config.key_file,
        &mut config.blob_root,
        &mut config.receipt_root,
    ] {
        paths::check(path, false)?;
        if path.is_relative() {
            *path = parent.join(&*path);
        }
        paths::check(path, true)?;
    }
    Ok(())
}

pub(super) fn derive(
    config: &IsolatedAotConfig,
    node: &NodeConfig,
    artifacts: DirectoryArtifactRepositoryConfig,
) -> Result<NativeAotSettings, PlatformError> {
    supported()?;
    let (process, raw, receipts, images) = limits::derive(config, node, artifacts)?;
    let digest = digest(&config.compiler_digest)?;
    paths::check(&config.compiler_executable, true)?;
    let roots = paths::Roots::check(config, &node.data_directory)?;
    let secret = key::read(&roots.key)?;
    let authority =
        TrustedAotCompilerAuthority::new("lsf-isolated-aot-v1", secret, process.compiler)?;
    Ok(NativeAotSettings {
        audit: None,
        executable: config.compiler_executable.as_path().to_path_buf(),
        approved_digest: digest,
        authority,
        process,
        cache: latent_wasmtime::NativeAotCacheConfig {
            blob_root: roots.blobs,
            receipt_root: roots.receipts,
            raw,
            receipts,
        },
        images,
    })
}

fn digest(value: &str) -> Result<[u8; 32], PlatformError> {
    // Check the borrowed spelling before the strict digest newtype allocates.
    if value.len() != 71 {
        return Err(invalid("isolatedAot.compilerDigest"));
    }
    let checked: ArtifactBlobDigest = value
        .parse()
        .map_err(|_| invalid("isolatedAot.compilerDigest"))?;
    let mut digest = [0; 32];
    for (output, pair) in digest
        .iter_mut()
        .zip(checked.as_str().as_bytes()[7..].chunks_exact(2))
    {
        let hex = |byte: u8| {
            if byte <= b'9' {
                byte - b'0'
            } else {
                byte - b'a' + 10
            }
        };
        *output = hex(pair[0]) * 16 + hex(pair[1]);
    }
    Ok(digest)
}

fn supported() -> Result<(), PlatformError> {
    if cfg!(all(target_os = "linux", target_arch = "x86_64")) {
        Ok(())
    } else {
        Err(PlatformError {
            code: PlatformErrorCode::IncompatibleContract,
            message: "isolated-aot-node-platform-unsupported".into(),
            retryable: false,
            details: Vec::new(),
        })
    }
}
