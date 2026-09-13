use std::net::{Ipv4Addr, SocketAddr};
use std::path::PathBuf;

use serde::Deserialize;

use super::MIB;

/// Local operator input. Required identity, storage and credentials have no
/// implicit defaults. Neither this type nor credential values implement Debug.
#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct NodeConfig {
    pub format_version: u32,
    pub data_directory: PathBuf,
    #[serde(default = "default_bind")]
    pub bind: SocketAddr,
    pub node_id: String,
    #[serde(default)]
    pub workers: WorkerConfig,
    #[serde(default = "default_cells")]
    pub cells: Vec<CellConfig>,
    #[serde(default)]
    pub execution: ExecutionConfig,
    #[serde(default)]
    pub engine: EngineConfig,
    #[serde(default)]
    pub limits: LimitConfig,
    #[serde(default)]
    pub cache: CacheConfig,
    #[serde(default)]
    pub catalogs: CatalogConfig,
    #[serde(default)]
    pub supply_chain: SupplyChainConfig,
    #[serde(default, deserialize_with = "super::aot::present")]
    pub isolated_aot: Option<super::IsolatedAotConfig>,
    #[serde(default, deserialize_with = "super::audit::present")]
    pub audit: Option<super::AuditConfig>,
    #[serde(default, deserialize_with = "super::rollouts::present")]
    pub rollouts: Option<super::RolloutConfig>,
    #[serde(default)]
    pub retention: RetentionConfig,
    #[serde(default)]
    pub telemetry: TelemetryConfig,
    pub credentials: Vec<CredentialConfig>,
    #[serde(default = "default_shutdown")]
    pub shutdown_grace_millis: u64,
}

/// Legacy catalogs remain explicitly local. Enforced roots persist their mode
/// and refuse a later local configuration, including an omitted field.
#[derive(Clone, Default, Deserialize)]
#[serde(tag = "mode", rename_all = "kebab-case", deny_unknown_fields)]
pub enum SupplyChainConfig {
    #[default]
    TrustedLocal,
    Enforced {
        #[serde(rename = "policyFile")]
        policy_file: PathBuf,
        #[serde(rename = "clockLeaseSeconds", default = "default_clock_lease")]
        clock_lease_seconds: u64,
    },
}
const fn default_clock_lease() -> u64 {
    5
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct WorkerConfig {
    pub runtime: usize,
    pub control: usize,
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CellConfig {
    pub class: String,
    pub capacity: u32,
    pub queue_capacity: u32,
    pub maximum_memory_bytes: u64,
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct ExecutionConfig {
    pub maximum_cpu_fuel: u64,
    pub maximum_wall_time_millis: u64,
    pub maximum_log_bytes: u64,
}

/// Bounded engine choices; omitted settings preserve the standalone defaults.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct EngineConfig {
    pub allocator: EngineAllocator,
    pub optimization: EngineOptimization,
}

#[derive(Clone, Copy, Debug, Default, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum EngineAllocator {
    #[default]
    OnDemand,
    Pooling,
}

#[derive(Clone, Copy, Debug, Default, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum EngineOptimization {
    #[default]
    Speed,
    SpeedAndSize,
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct LimitConfig {
    pub maximum_component_bytes: usize,
    pub maximum_payload_bytes: usize,
    pub maximum_connections: usize,
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct CacheConfig {
    pub entries: usize,
    pub source_bytes: usize,
    pub metadata_bytes: usize,
    pub compiled_image_bytes: usize,
    /// Total distinct compiler jobs, including assigned workers and queued jobs.
    pub preparations: usize,
    /// Fixed compiler workers; defaults to min(2, preparations).
    pub compiler_workers: Option<usize>,
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct CatalogConfig {
    pub release_entries: usize,
    pub release_index_bytes: usize,
    pub deployments: usize,
    pub deployment_state_bytes: usize,
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct RetentionConfig {
    pub terminal_entries: usize,
    pub terminal_ttl_millis: u64,
    pub bytes: usize,
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields, default)]
pub struct TelemetryConfig {
    pub queue_entries: usize,
    pub retained_entries: usize,
    pub retained_bytes: usize,
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CredentialConfig {
    pub token: String,
    pub subject: String,
    pub tenant: String,
    pub role: CredentialRole,
}

#[derive(Clone, Copy, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum CredentialRole {
    Invoke,
    Admin,
    Operator,
}

fn default_bind() -> SocketAddr {
    (Ipv4Addr::LOCALHOST, 50051).into()
}

fn default_cells() -> Vec<CellConfig> {
    vec![CellConfig {
        class: "standard".to_owned(),
        capacity: 2,
        queue_capacity: 16,
        maximum_memory_bytes: 64 * MIB as u64,
    }]
}

const fn default_shutdown() -> u64 {
    1000
}

#[path = "defaults.rs"]
mod defaults;
