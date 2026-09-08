use latent_artifacts::DirectoryArtifactRepositoryConfig;
use latent_control_store::DirectoryDeploymentRepositoryConfig;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

pub(super) const MAX_COMPONENT: usize = 64 * 1024 * 1024;
pub(super) const MAX_DOCUMENT: usize = 1024 * 1024;
pub(super) const FIXTURE_SCHEMA: &str = "latent.artifact-identity.fixture.v1";
pub(super) const HOLD_MILLIS: u64 = 100;

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Fixture {
    pub schema: String,
    pub size: String,
    pub component_digest: String,
    pub component_bytes: String,
    pub source_component_digest: String,
    pub source_component_bytes: String,
    pub capsule_sha256: String,
    pub contracts_sha256: String,
    pub deployment_sha256: String,
    pub tenant: String,
    pub service: String,
    pub deployment_id: String,
    pub contract: String,
    pub function: String,
    pub revision_id: String,
    pub route_generation: String,
    pub configuration: Value,
}

pub(super) fn artifact_config() -> DirectoryArtifactRepositoryConfig {
    DirectoryArtifactRepositoryConfig {
        max_index_entries: 4,
        max_index_bytes: 4 * 1024 * 1024,
        max_page_size: 4,
        max_page_bytes: MAX_DOCUMENT,
        max_descriptor_bytes: 64 * 1024,
        max_metadata_bytes: MAX_DOCUMENT,
        max_component_bytes: MAX_COMPONENT,
        max_recovery_directories: 4,
    }
}

pub(super) fn deployment_config() -> DirectoryDeploymentRepositoryConfig {
    DirectoryDeploymentRepositoryConfig {
        max_deployments: 4,
        max_state_bytes: 4 * 1024 * 1024,
        max_route_entries: 64,
        max_identifier_bytes: 512,
        max_routing_key_bytes: 512,
        max_page_size: 4,
        max_page_bytes: MAX_DOCUMENT,
    }
}

pub(super) fn configuration() -> Value {
    let a = artifact_config();
    let d = deployment_config();
    json!({
        "artifacts": {
            "max_index_entries": a.max_index_entries, "max_index_bytes": a.max_index_bytes,
            "max_page_size": a.max_page_size, "max_page_bytes": a.max_page_bytes,
            "max_descriptor_bytes": a.max_descriptor_bytes, "max_metadata_bytes": a.max_metadata_bytes,
            "max_component_bytes": a.max_component_bytes,
            "max_recovery_directories": a.max_recovery_directories,
        },
        "deployments": {
            "max_deployments": d.max_deployments, "max_state_bytes": d.max_state_bytes,
            "max_route_entries": d.max_route_entries, "max_identifier_bytes": d.max_identifier_bytes,
            "max_routing_key_bytes": d.max_routing_key_bytes, "max_page_size": d.max_page_size,
            "max_page_bytes": d.max_page_bytes,
        },
    })
}
