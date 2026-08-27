//! Shared Phase 0 runtime, artifact-preparation, and activation composition.
//!
//! This module is intentionally the single composition path used by the
//! `latentd phase0-spike` executable and the retained Phase 0 baseline.  It is
//! public only within the `latentd` package boundary so the benchmark can use
//! the exact executable wiring rather than reconstructing a near-equivalent
//! runtime.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use latent_activation::{ActivationEnvelope, TraceContext};
use latent_artifacts::{ArtifactDescriptor, CapsuleArtifact};
use latent_core::{
    ActivationId, ArtifactReference, CapabilityId, ContractId, FunctionId, InvocationPrincipal,
    Metadata, NodeId, PlatformError, PlatformErrorCode, PrincipalKind, ReleaseDigest,
    ResourceBudget, ServiceId, SpanId, TenantId, TraceId,
};
use latent_executor::{BoundImport, ExecutionBackend, PreparationKey, PreparedComponent};
use latent_manifest::{
    CapsuleManifest, ContractExport, ContractImport, ExecutionBackendKind, ExecutionRequirements,
    ObjectMetadata, StateModel, ThreadingModel,
};
use latent_node::{Phase0ActivationRunner, Phase0ActivationRunnerConfig};
use latent_routing::InvocationTarget;
use latent_scheduler::{CellClass, CellPool, FixedCellPool, FixedCellPoolConfig};
use latent_wasmtime::{
    Phase0InstanceAllocator, Phase0WasmtimeBackend, Phase0WasmtimeConfig,
    Phase0WasmtimeEngineFactory, PreparedCacheSnapshot, CONTEXT_IMPORT, ECHO_EXPORT,
    ECHO_SUCCESS_MEDIA_TYPE, LOG_IMPORT,
};
use serde::Deserialize;
use sha2::{Digest as _, Sha256};
use tokio::runtime::Builder;

pub const PHASE0_EPOCH_TICK_INTERVAL_MILLIS: u64 = 1;
pub const PHASE0_RUNTIME_WORKER_START_TIMEOUT_MILLIS: u64 = 2_000;

/// The immutable runtime/pool configuration shared by the executable and
/// retained benchmark.  The caller owns policy validation; this type only
/// makes the concrete composition explicit.
#[derive(Debug, Clone)]
pub struct Phase0RuntimeConfig {
    pub node_id: NodeId,
    pub pool_capacity: u32,
    pub pool_queue_capacity: u32,
    pub runtime_workers: usize,
}

/// Tokio lifecycle observations used to prove the configured worker topology.
#[derive(Clone, Debug, Default)]
pub struct Phase0RuntimeWorkerMonitor {
    started: Arc<AtomicUsize>,
    stopped: Arc<AtomicUsize>,
}

impl Phase0RuntimeWorkerMonitor {
    fn worker_started(&self) {
        self.started.fetch_add(1, Ordering::AcqRel);
    }

    fn worker_stopped(&self) {
        self.stopped.fetch_add(1, Ordering::AcqRel);
    }

    #[must_use]
    pub fn active_workers(&self) -> usize {
        self.started
            .load(Ordering::Acquire)
            .saturating_sub(self.stopped.load(Ordering::Acquire))
    }
}

/// The exact Phase 0 runtime composition used by both supported consumers.
pub struct Phase0RuntimeComposition {
    pub runtime: tokio::runtime::Runtime,
    pub pool: Arc<FixedCellPool>,
    pub workers: Phase0RuntimeWorkerMonitor,
}

pub fn construct_runtime_composition(
    config: &Phase0RuntimeConfig,
) -> Result<Phase0RuntimeComposition, PlatformError> {
    if config.pool_capacity == 0 || config.pool_queue_capacity == 0 || config.runtime_workers == 0 {
        return Err(composition_error(
            PlatformErrorCode::InvalidArgument,
            "Phase 0 runtime capacity and worker configuration must be non-zero",
        ));
    }

    let workers = Phase0RuntimeWorkerMonitor::default();
    let started_workers = workers.clone();
    let stopped_workers = workers.clone();
    let runtime = Builder::new_multi_thread()
        .worker_threads(config.runtime_workers)
        .thread_name("latentd-phase0-worker")
        .on_thread_start(move || started_workers.worker_started())
        .on_thread_stop(move || stopped_workers.worker_stopped())
        .enable_time()
        .build()
        .map_err(|error| {
            composition_error(
                PlatformErrorCode::Internal,
                &format!("failed to construct the fixed Tokio runtime: {error}"),
            )
        })?;
    let pool = FixedCellPool::new(FixedCellPoolConfig::new(
        config.node_id.clone(),
        CellClass::Standard,
        config.pool_capacity,
        config.pool_queue_capacity,
    ))
    .map(Arc::new)?;

    Ok(Phase0RuntimeComposition {
        runtime,
        pool,
        workers,
    })
}

/// Waits for the lifecycle hooks, rather than using a readiness sleep.
pub async fn wait_for_runtime_workers(
    workers: &Phase0RuntimeWorkerMonitor,
    expected: usize,
) -> Result<(), PlatformError> {
    let deadline = tokio::time::Instant::now()
        + Duration::from_millis(PHASE0_RUNTIME_WORKER_START_TIMEOUT_MILLIS);
    loop {
        if workers.active_workers() == expected {
            return Ok(());
        }
        if tokio::time::Instant::now() >= deadline {
            return Err(composition_error(
                PlatformErrorCode::Internal,
                &format!(
                    "fixed Tokio runtime did not start its configured worker count: expected {expected}, observed {}",
                    workers.active_workers()
                ),
            ));
        }
        tokio::task::yield_now().await;
    }
}

/// Configuration for the shared artifact-to-prepared-runner path.
#[derive(Debug, Clone)]
pub struct Phase0PreparationConfig {
    pub capsule: PathBuf,
    pub component: Option<PathBuf>,
    pub component_maximum_bytes: usize,
    pub prepared_cache_maximum_entries: usize,
    pub prepared_cache_maximum_bytes: usize,
    /// The ordinary Phase 0 path uses a bounded node-owned cache.  The
    /// profiling harness alone may disable reuse to compare a cold prepare.
    pub prepared_cache_enabled: bool,
    pub invocation_log_maximum_entries: usize,
    pub invocation_log_maximum_bytes: usize,
    pub retained_log_maximum_entries: usize,
    pub retained_log_maximum_bytes: usize,
    /// The largest invocation memory grant that this retained composition will accept.
    pub requested_memory_bytes: u64,
    /// The largest invocation fuel grant that this retained composition will accept.
    pub requested_fuel: u64,
    /// Explicit allocator choice for bounded profiling experiments. The normal
    /// executable path uses on-demand allocation.
    pub wasmtime_instance_allocator: Phase0InstanceAllocator,
    /// Explicitly select Wasmtime's initialized-memory COW behavior so an
    /// experiment cannot be confused with an ambient default.
    pub wasmtime_copy_on_write_images: bool,
    /// The pool experiment may reserve no more than this many concurrently
    /// instantiable resources. It tracks the fixed cell capacity.
    pub wasmtime_pooling_maximum_instances: u32,
}

#[derive(Debug)]
pub struct Phase0LoadedArtifact {
    pub artifact: CapsuleArtifact,
    pub component_path: PathBuf,
    pub component_bytes: u64,
}

pub struct Phase0PreparedBackend {
    pub loaded: Phase0LoadedArtifact,
    pub backend: Arc<Phase0WasmtimeBackend>,
    /// The exact key used for the first preparation.  Keeping it with the
    /// prepared result lets the benchmark make a narrow same-key reuse probe
    /// instead of inferring cache behaviour from an unrelated phase total.
    pub preparation_key: PreparationKey,
    pub prepared: PreparedComponent,
    pub cache_after_prepare: PreparedCacheSnapshot,
    pub timings: Phase0PreparationTimings,
}

#[derive(Debug, Clone, Copy, Default)]
pub struct Phase0PreparationTimings {
    pub capsule_validation_and_load_micros: u64,
    pub wasmtime_engine_construction_micros: u64,
    pub component_preparation_micros: u64,
}

/// Loads and validates the capsule, constructs the concrete backend profile,
/// and prepares exactly one bounded cached component.
pub async fn prepare_phase0_backend(
    config: &Phase0PreparationConfig,
) -> Result<Phase0PreparedBackend, PlatformError> {
    let load_started = Instant::now();
    let loaded = load_phase0_artifact(config)?;
    validate_requested_budget(config, &loaded.artifact.manifest)?;
    let capsule_validation_and_load_micros = elapsed_micros(load_started);

    let declared = &loaded.artifact.manifest.execution.resource_budget_ceiling;
    let engine_started = Instant::now();
    let factory = Phase0WasmtimeEngineFactory::new(Phase0WasmtimeConfig {
        maximum_component_bytes: config.component_maximum_bytes,
        maximum_memory_bytes: declared.memory_bytes,
        maximum_fuel: declared.cpu_fuel,
        prepared_cache_maximum_entries: config.prepared_cache_maximum_entries,
        prepared_cache_maximum_source_bytes: config.prepared_cache_maximum_bytes,
        prepared_cache_enabled: config.prepared_cache_enabled,
        invocation_log_maximum_entries: config.invocation_log_maximum_entries,
        invocation_log_maximum_bytes: config.invocation_log_maximum_bytes,
        retained_log_maximum_entries: config.retained_log_maximum_entries,
        retained_log_maximum_bytes: config.retained_log_maximum_bytes,
        epoch_tick_interval_millis: PHASE0_EPOCH_TICK_INTERVAL_MILLIS,
        instance_allocator: config.wasmtime_instance_allocator,
        copy_on_write_images: config.wasmtime_copy_on_write_images,
        pooling_maximum_instances: match config.wasmtime_instance_allocator {
            Phase0InstanceAllocator::OnDemand => 1,
            Phase0InstanceAllocator::Pooling => config.wasmtime_pooling_maximum_instances,
        },
        ..Phase0WasmtimeConfig::default()
    })?;
    let preparation_key =
        factory.preparation_key(loaded.artifact.descriptor.release_digest.clone());
    let backend = Arc::new(factory.create_backend_instance());
    drop(factory);
    let wasmtime_engine_construction_micros = elapsed_micros(engine_started);

    let preparation_started = Instant::now();
    let prepared = backend.prepare(&loaded.artifact, &preparation_key).await?;
    let component_preparation_micros = elapsed_micros(preparation_started);
    let cache_after_prepare = backend.cache_snapshot();

    Ok(Phase0PreparedBackend {
        loaded,
        backend,
        preparation_key,
        prepared,
        cache_after_prepare,
        timings: Phase0PreparationTimings {
            capsule_validation_and_load_micros,
            wasmtime_engine_construction_micros,
            component_preparation_micros,
        },
    })
}

/// Builds the same Phase 0 activation runner and binding set used by the
/// executable.  Callers may wrap the pool/backend only for observation.
pub fn create_phase0_activation_runner(
    pool: Arc<dyn CellPool>,
    backend: Arc<dyn ExecutionBackend>,
    prepared: PreparedComponent,
) -> Result<Arc<Phase0ActivationRunner>, PlatformError> {
    Phase0ActivationRunner::new(
        Phase0ActivationRunnerConfig::default(),
        pool,
        backend,
        prepared,
        phase0_bound_imports(),
    )
    .map(Arc::new)
}

#[must_use]
pub fn phase0_bound_imports() -> Vec<BoundImport> {
    vec![
        BoundImport {
            capability: CapabilityId("context".to_owned()),
            contract: CONTEXT_IMPORT.to_owned(),
            opaque_handle: "phase0-activation-context".to_owned(),
        },
        BoundImport {
            capability: CapabilityId("log".to_owned()),
            contract: LOG_IMPORT.to_owned(),
            opaque_handle: "phase0-bounded-log".to_owned(),
        },
    ]
}

/// Common envelope construction for all Phase 0 activations.
#[derive(Debug, Clone)]
pub struct Phase0InvocationConfig<'a> {
    pub activation_id: ActivationId,
    pub input: &'a str,
    pub memory_bytes: u64,
    pub fuel: u64,
    pub deadline_unix_millis: u64,
    pub surface: &'a str,
    pub mode: &'a str,
    pub principal_subject: &'a str,
    pub default_tenant: &'a str,
    pub trace_id: &'a str,
    pub span_id: &'a str,
}

#[must_use]
pub fn phase0_activation_envelope(
    manifest: &CapsuleManifest,
    config: &Phase0InvocationConfig<'_>,
) -> ActivationEnvelope {
    let tenant = manifest
        .metadata
        .tenant
        .clone()
        .unwrap_or_else(|| TenantId(config.default_tenant.to_owned()));
    let mut budget = manifest.execution.resource_budget_ceiling.clone();
    budget.cpu_fuel = config.fuel;
    budget.memory_bytes = config.memory_bytes;
    budget.wall_deadline_unix_millis = Some(config.deadline_unix_millis);

    ActivationEnvelope {
        activation_id: config.activation_id.clone(),
        parent_activation_id: None,
        root_activation_id: config.activation_id.clone(),
        principal: InvocationPrincipal {
            subject: config.principal_subject.to_owned(),
            kind: PrincipalKind::User,
            tenant: Some(tenant.clone()),
            service: None,
            claims: Metadata::from([
                ("role".to_owned(), config.mode.to_owned()),
                ("surface".to_owned(), config.surface.to_owned()),
            ]),
        },
        target: InvocationTarget {
            tenant,
            service: ServiceId("echo".to_owned()),
            contract: ContractId(ECHO_EXPORT.to_owned()),
            function: FunctionId("echo".to_owned()),
            route: None,
        },
        resolved_revision: None,
        deadline_unix_millis: Some(config.deadline_unix_millis),
        priority: 0,
        trace: TraceContext {
            trace_id: TraceId(config.trace_id.to_owned()),
            span_id: SpanId(config.span_id.to_owned()),
            trace_flags: 1,
            baggage: Metadata::from([("surface".to_owned(), config.surface.to_owned())]),
        },
        idempotency_key: None,
        retry_attempt: 0,
        budget,
        metadata: Metadata::from([
            ("mode".to_owned(), config.mode.to_owned()),
            ("production-ready".to_owned(), "false".to_owned()),
        ]),
        input: config.input.as_bytes().to_vec(),
        input_media_type: ECHO_SUCCESS_MEDIA_TYPE.to_owned(),
    }
}

fn load_phase0_artifact(
    config: &Phase0PreparationConfig,
) -> Result<Phase0LoadedArtifact, PlatformError> {
    let manifest_path = if config.capsule.is_dir() {
        config.capsule.join("capsule.json")
    } else {
        config.capsule.clone()
    };
    if !manifest_path.is_file() {
        return Err(composition_error(
            PlatformErrorCode::NotFound,
            &format!(
                "capsule manifest is not a readable file: {}",
                manifest_path.display()
            ),
        ));
    }

    let manifest_bytes = fs::read(&manifest_path).map_err(|error| {
        composition_error(
            PlatformErrorCode::CorruptArtifact,
            &format!("failed to read capsule manifest: {error}"),
        )
    })?;
    let document: CapsuleDocument = serde_json::from_slice(&manifest_bytes).map_err(|error| {
        composition_error(
            PlatformErrorCode::CorruptArtifact,
            &format!("capsule manifest is not valid JSON for the Phase 0 composition: {error}"),
        )
    })?;
    let manifest = document.into_manifest()?;
    let base_directory = manifest_path.parent().unwrap_or_else(|| Path::new("."));
    let component_path = match &config.component {
        Some(path) => path.clone(),
        None => manifest
            .metadata
            .annotations
            .get("latent.dev/artifact")
            .map(|path| base_directory.join(path))
            .ok_or_else(|| {
                composition_error(
                    PlatformErrorCode::InvalidArgument,
                    "--component is required when the capsule lacks latent.dev/artifact",
                )
            })?,
    };
    if !component_path.is_file() {
        return Err(composition_error(
            PlatformErrorCode::NotFound,
            &format!(
                "component is not a readable file: {}",
                component_path.display()
            ),
        ));
    }

    let metadata = fs::metadata(&component_path).map_err(|error| {
        composition_error(
            PlatformErrorCode::CorruptArtifact,
            &format!("failed to inspect component file: {error}"),
        )
    })?;
    let component_bytes = metadata.len();
    let maximum = u64::try_from(config.component_maximum_bytes).unwrap_or(u64::MAX);
    if component_bytes == 0 || component_bytes > maximum {
        return Err(composition_error(
            PlatformErrorCode::ResourceExhausted,
            "component size is zero or exceeds the shared Phase 0 component limit",
        ));
    }
    let prepared_cache_maximum =
        u64::try_from(config.prepared_cache_maximum_bytes).unwrap_or(u64::MAX);
    if component_bytes > prepared_cache_maximum {
        return Err(composition_error(
            PlatformErrorCode::ResourceExhausted,
            "component cannot fit in the bounded shared Phase 0 prepared cache",
        ));
    }

    let bytes = fs::read(&component_path).map_err(|error| {
        composition_error(
            PlatformErrorCode::CorruptArtifact,
            &format!("failed to read component file: {error}"),
        )
    })?;
    let actual_digest = component_digest(&bytes);
    if manifest.component_digest.0 != actual_digest {
        return Err(composition_error(
            PlatformErrorCode::CorruptArtifact,
            "component digest does not match capsule metadata",
        ));
    }

    let size_bytes = u64::try_from(bytes.len()).map_err(|_| {
        composition_error(
            PlatformErrorCode::ResourceExhausted,
            "component size cannot be represented by the artifact descriptor",
        )
    })?;
    let descriptor = ArtifactDescriptor {
        reference: ArtifactReference(format!("file://{}", component_path.display())),
        release_digest: manifest.component_digest.clone(),
        media_type: "application/vnd.wasm.component.v1+wasm".to_owned(),
        size_bytes,
        publisher: None,
        layers: Vec::new(),
        annotations: manifest.metadata.annotations.clone(),
    };

    Ok(Phase0LoadedArtifact {
        artifact: CapsuleArtifact {
            descriptor,
            manifest,
            contracts: Vec::new(),
            component_bytes: bytes,
        },
        component_path,
        component_bytes: size_bytes,
    })
}

fn validate_requested_budget(
    config: &Phase0PreparationConfig,
    manifest: &CapsuleManifest,
) -> Result<(), PlatformError> {
    let declared = &manifest.execution.resource_budget_ceiling;
    if declared.memory_bytes == 0 || declared.cpu_fuel == 0 {
        return Err(composition_error(
            PlatformErrorCode::InvalidArgument,
            "capsule declares a zero memory or fuel ceiling",
        ));
    }
    if config.requested_memory_bytes > declared.memory_bytes
        || config.requested_fuel > declared.cpu_fuel
    {
        return Err(composition_error(
            PlatformErrorCode::InvalidArgument,
            "requested invocation budget exceeds the capsule-declared ceiling",
        ));
    }
    Ok(())
}

fn elapsed_micros(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX)
}

fn component_digest(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    format!(
        "sha256:{}",
        digest
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>()
    )
}

fn composition_error(code: PlatformErrorCode, message: &str) -> PlatformError {
    PlatformError {
        code,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct CapsuleDocument {
    api_version: String,
    kind: String,
    metadata: MetadataDocument,
    component: ComponentDocument,
    exports: Vec<String>,
    imports: Vec<ImportDocument>,
    execution: ExecutionDocument,
    compatibility: CompatibilityDocument,
}

#[derive(Debug, Deserialize)]
struct MetadataDocument {
    name: String,
    #[serde(default)]
    tenant: Option<String>,
    #[serde(default)]
    namespace: Option<String>,
    #[serde(default)]
    labels: BTreeMap<String, String>,
    #[serde(default)]
    annotations: BTreeMap<String, String>,
}

#[derive(Debug, Deserialize)]
struct ComponentDocument {
    digest: String,
    version: String,
    world: String,
}

#[derive(Debug, Deserialize)]
struct ImportDocument {
    contract: String,
    optional: bool,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ExecutionDocument {
    backend: String,
    threading: String,
    state_model: String,
    limits: LimitsDocument,
    host_call_depth_maximum: u32,
    component_call_depth_maximum: u32,
    snapshot_eligible: bool,
    fusion_eligible: bool,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct LimitsDocument {
    cpu_fuel: u64,
    memory_bytes: u64,
    wall_deadline_unix_millis: Option<u64>,
    child_calls: u32,
    outbound_requests: u32,
    state_read_bytes: u64,
    state_write_bytes: u64,
    blob_read_bytes: u64,
    blob_write_bytes: u64,
    log_bytes: u64,
    effect_count: u32,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct CompatibilityDocument {
    minimum_fabric_version: String,
}

impl CapsuleDocument {
    fn into_manifest(self) -> Result<CapsuleManifest, PlatformError> {
        if self.kind != "Capsule" {
            return Err(composition_error(
                PlatformErrorCode::InvalidArgument,
                "capsule document kind must be Capsule",
            ));
        }
        if self.metadata.name.trim().is_empty()
            || self.component.digest.trim().is_empty()
            || self.component.version.trim().is_empty()
            || self.component.world.trim().is_empty()
        {
            return Err(composition_error(
                PlatformErrorCode::InvalidArgument,
                "capsule identity and component fields must be non-empty",
            ));
        }
        let backend = match self.execution.backend.as_str() {
            "wasm-component" => ExecutionBackendKind::WasmComponent,
            _ => {
                return Err(composition_error(
                    PlatformErrorCode::IncompatibleContract,
                    "the Phase 0 composition supports only the wasm-component backend",
                ));
            }
        };
        let threading = match self.execution.threading.as_str() {
            "single-threaded" => ThreadingModel::SingleThreaded,
            "reentrant" => ThreadingModel::Reentrant,
            "cooperative" => ThreadingModel::Cooperative,
            _ => {
                return Err(composition_error(
                    PlatformErrorCode::IncompatibleContract,
                    "capsule declares an unknown threading model",
                ));
            }
        };
        let state_model = match self.execution.state_model.as_str() {
            "stateless" => StateModel::Stateless,
            "transactional-keyed" => StateModel::TransactionalKeyed,
            "entity" => StateModel::Entity,
            "durable-workflow" => StateModel::DurableWorkflow,
            _ => {
                return Err(composition_error(
                    PlatformErrorCode::IncompatibleContract,
                    "capsule declares an unknown state model",
                ));
            }
        };
        let limits = self.execution.limits;
        Ok(CapsuleManifest {
            api_version: self.api_version,
            metadata: ObjectMetadata {
                name: self.metadata.name,
                tenant: self.metadata.tenant.map(TenantId),
                namespace: self.metadata.namespace,
                labels: self.metadata.labels,
                annotations: self.metadata.annotations,
            },
            semantic_version: self.component.version,
            component_digest: ReleaseDigest(self.component.digest),
            world: ContractId(self.component.world),
            exports: self
                .exports
                .into_iter()
                .map(|contract| ContractExport {
                    contract: ContractId(contract),
                })
                .collect(),
            imports: self
                .imports
                .into_iter()
                .map(|import| ContractImport {
                    contract: ContractId(import.contract),
                    optional: import.optional,
                })
                .collect(),
            execution: ExecutionRequirements {
                backend,
                threading,
                state_model,
                resource_budget_ceiling: ResourceBudget {
                    cpu_fuel: limits.cpu_fuel,
                    memory_bytes: limits.memory_bytes,
                    wall_deadline_unix_millis: limits.wall_deadline_unix_millis,
                    child_calls: limits.child_calls,
                    outbound_requests: limits.outbound_requests,
                    state_read_bytes: limits.state_read_bytes,
                    state_write_bytes: limits.state_write_bytes,
                    blob_read_bytes: limits.blob_read_bytes,
                    blob_write_bytes: limits.blob_write_bytes,
                    log_bytes: limits.log_bytes,
                    effect_count: limits.effect_count,
                },
                host_call_depth_maximum: self.execution.host_call_depth_maximum,
                component_call_depth_maximum: self.execution.component_call_depth_maximum,
                snapshot_eligible: self.execution.snapshot_eligible,
                fusion_eligible: self.execution.fusion_eligible,
            },
            minimum_fabric_version: self.compatibility.minimum_fabric_version,
        })
    }
}
