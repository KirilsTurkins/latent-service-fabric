use serde::Deserialize;
use std::path::PathBuf;

const MIB: usize = 1024 * 1024;

/// Explicit operator-owned compiler approval and separate replaceable caches.
/// The key file contains exactly 32 private bytes; JSON never contains the key.
#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct IsolatedAotConfig {
    pub compiler_executable: PathBuf,
    pub compiler_digest: String,
    pub key_file: PathBuf,
    pub blob_root: PathBuf,
    pub receipt_root: PathBuf,
    #[serde(default)]
    pub process: AotProcessConfig,
    #[serde(default)]
    pub cache: AotCacheConfig,
    #[serde(default)]
    pub images: AotImageConfig,
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct AotProcessConfig {
    pub job_timeout_millis: u64,
    pub maximum_output_bytes: usize,
    pub address_space_bytes: u64,
}
impl Default for AotProcessConfig {
    fn default() -> Self {
        Self {
            job_timeout_millis: 30_000,
            maximum_output_bytes: 128 * MIB,
            address_space_bytes: (512 * MIB) as u64,
        }
    }
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct AotCacheConfig {
    pub entries: usize,
    pub disk_bytes: u64,
}
impl Default for AotCacheConfig {
    fn default() -> Self {
        Self {
            entries: 1024,
            disk_bytes: (256 * MIB) as u64,
        }
    }
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct AotImageConfig {
    pub maximum_images: usize,
    pub maximum_image_bytes: usize,
    pub maximum_total_bytes: usize,
}
impl Default for AotImageConfig {
    fn default() -> Self {
        Self {
            maximum_images: 64,
            maximum_image_bytes: 128 * MIB,
            maximum_total_bytes: 256 * MIB,
        }
    }
}
