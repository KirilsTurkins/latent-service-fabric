use super::*;
use latent_artifacts::DirectoryArtifactRepositoryConfig;
use serde_json::{json, Value};
use std::path::Path;
use tempfile::TempDir;

mod input;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod key;
mod limits;

fn document(root: &Path) -> Value {
    json!({"formatVersion":1,"dataDirectory":root.join("data"),"nodeId":"aot-config",
        "bind":"127.0.0.1:0", "credentials":[{
            "token":"test-aot-token-00000000000000000000000",
            "subject":"operator","tenant":"tests","role":"operator"}],
        "isolatedAot":{
            "compilerExecutable":root.join("compiler"),
            "compilerDigest":format!("sha256:{}", "ab".repeat(32)),
            "keyFile":root.join("private/key"),
            "blobRoot":root.join("cache/blobs"),
            "receiptRoot":root.join("cache/receipts")}})
}

fn parsed(root: &Path) -> NodeConfig {
    serde_json::from_value(document(root)).unwrap()
}

fn check_limits(config: &NodeConfig) -> Result<super::limits::Limits, PlatformError> {
    super::limits::derive(
        config.isolated_aot.as_ref().unwrap(),
        config,
        DirectoryArtifactRepositoryConfig {
            max_component_bytes: config.limits.maximum_component_bytes,
            ..DirectoryArtifactRepositoryConfig::default()
        },
    )
}
