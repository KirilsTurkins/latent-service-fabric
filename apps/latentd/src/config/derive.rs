use std::collections::BTreeMap;
use std::time::Duration;

use latent_artifacts::DirectoryArtifactRepositoryConfig;
use latent_control_store::DirectoryDeploymentRepositoryConfig;
use latent_core::{NodeId, PlatformError};
use latent_node::{NodeDescriptor, StandaloneInventoryConfig};
use latent_scheduler::LocalSchedulerConfig;
use latent_telemetry::{LocalSinkConfig, SharedActivationObserverConfig, TelemetryPipelineConfig};

use crate::standalone::transport::{TransportConfig, TransportCredential};

use super::{
    invalid, policy, runtime, validation, NodeConfig, NodeSettings, IDENTIFIER_BYTES,
    LOAD_MAXIMUM_AGE, MIB, TRUST_CLASS,
};

pub(super) fn settings(config: &NodeConfig) -> Result<NodeSettings, PlatformError> {
    let capacity = validation::validate(config)?;
    let admission = policy::admission(config, &capacity)?;
    let invocation = runtime::invocation(config, &capacity)?;
    let management = runtime::management(config, &invocation)?;
    let classes = config
        .cells
        .iter()
        .map(|cell| Ok((validation::class(&cell.class)?, cell.queue_capacity)))
        .collect::<Result<BTreeMap<_, _>, PlatformError>>()?;
    let maximum_rpcs = capacity.reservations as usize + config.workers.control + 4;
    let transport = transport(config, maximum_rpcs);
    transport.validate().map_err(|_| invalid("transport"))?;
    let telemetry = TelemetryPipelineConfig {
        queue_capacity: config.telemetry.queue_entries,
        ..TelemetryPipelineConfig::default()
    };
    telemetry.validate().map_err(|_| invalid("telemetry"))?;
    let wasmtime = runtime::wasmtime(config, &capacity)?;
    let runtime_profile = std::sync::Arc::new(wasmtime.detected_runtime_profile()?);
    let artifacts = artifact_limits(config, management.max_page_size);
    let isolated_aot = config
        .isolated_aot
        .as_ref()
        .map(|aot| super::aot::derive(aot, config, artifacts))
        .transpose()?;
    let mut node = descriptor(config);
    node.cpu_features = runtime_profile
        .cpu_features()
        .iter()
        .map(ToString::to_string)
        .collect();
    Ok(NodeSettings {
        data_directory: config.data_directory.as_path().to_path_buf(),
        supply_chain: super::supply_chain::derive(&config.supply_chain)?,
        isolated_aot,
        audit: super::audit::derive(config.audit.as_ref())?,
        rollouts: super::rollouts::derive(config.rollouts.as_ref(), config.audit.is_some())?,
        node,
        runtime_workers: config.workers.runtime,
        control_workers: config.workers.control,
        artifacts,
        deployments: DirectoryDeploymentRepositoryConfig {
            max_deployments: config.catalogs.deployments,
            max_state_bytes: config.catalogs.deployment_state_bytes,
            max_identifier_bytes: IDENTIFIER_BYTES,
            max_page_size: management.max_page_size,
            max_page_bytes: MIB,
            ..DirectoryDeploymentRepositoryConfig::default()
        },
        admission,
        scheduler: LocalSchedulerConfig {
            node: NodeId(config.node_id.clone()),
            queue_capacity_per_class: classes.clone(),
            starvation_after: Duration::from_millis(100),
        },
        wasmtime,
        runtime_profile,
        manager: runtime::manager(config, &capacity),
        invocation,
        management,
        telemetry,
        local_sink: LocalSinkConfig {
            maximum_entries: config.telemetry.retained_entries,
            maximum_bytes: config.telemetry.retained_bytes,
        },
        observer: SharedActivationObserverConfig {
            maximum_active_correlations: maximum_rpcs,
            ..SharedActivationObserverConfig::default()
        },
        inventory: StandaloneInventoryConfig {
            cell_classes: classes.into_keys().collect(),
            maximum_cache_descriptors: 0,
            maximum_load_age: LOAD_MAXIMUM_AGE,
            ..StandaloneInventoryConfig::default()
        },
        transport,
        shutdown_grace: Duration::from_millis(config.shutdown_grace_millis),
        load_sample_interval: Duration::from_millis(250),
    })
}

fn artifact_limits(config: &NodeConfig, page_size: u32) -> DirectoryArtifactRepositoryConfig {
    DirectoryArtifactRepositoryConfig {
        max_index_entries: config.catalogs.release_entries,
        max_index_bytes: config.catalogs.release_index_bytes,
        max_component_bytes: config.limits.maximum_component_bytes,
        max_page_size: page_size as usize,
        max_page_bytes: MIB,
        max_recovery_directories: config.catalogs.release_entries + 16,
        ..DirectoryArtifactRepositoryConfig::default()
    }
}

fn descriptor(config: &NodeConfig) -> NodeDescriptor {
    NodeDescriptor {
        id: NodeId(config.node_id.clone()),
        architecture: std::env::consts::ARCH.to_owned(),
        operating_system: std::env::consts::OS.to_owned(),
        cpu_features: Vec::new(),
        trust_classes: vec![TRUST_CLASS.to_owned()],
        region: None,
        zone: None,
        // Startup replaces a port-zero endpoint with the actual bound address.
        endpoint: format!("http://{}", config.bind),
        identity: config.node_id.clone(),
        attributes: BTreeMap::new(),
    }
}

fn transport(config: &NodeConfig, maximum_rpcs: usize) -> TransportConfig {
    TransportConfig {
        bind: config.bind,
        maximum_connections: config.limits.maximum_connections,
        maximum_rpcs,
        reserved_cancel_status_rpcs: 4,
        maximum_control_jobs: config.workers.control,
        maximum_header_bytes: 16 * 1024,
        maximum_streams_per_connection: 32,
        request_timeout: Duration::from_millis(config.execution.maximum_wall_time_millis),
        shutdown_timeout: Duration::from_millis(config.shutdown_grace_millis),
        credentials: config
            .credentials
            .iter()
            .map(|credential| TransportCredential {
                token: credential.token.clone(),
                principal: policy::principal(credential),
            })
            .collect(),
    }
}
