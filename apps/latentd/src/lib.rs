//! Explicit composition root for the non-production Phase 0 activation spike.
//!
//! `latentd phase0-spike invoke-once` is intentionally finite. It wires the
//! fixed cell pool, Wasmtime containment backend, activation runner, bounded
//! preparation cache, bounded logs, deadlines, and cancellation into one local
//! executable path. It is not a Phase 1 management or invocation API.

#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::fs;
use std::io::{self, Write as _};
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use clap::{error::ErrorKind, Args, Parser, Subcommand};
use latent_activation::{ActivationEnvelope, ActivationManager, ActivationOutcome, TraceContext};
use latent_artifacts::{ArtifactDescriptor, CapsuleArtifact};
use latent_core::{
    ActivationId, ActivationTerminalState, ArtifactReference, BudgetConsumption, CapabilityId,
    ContractId, ErrorDetail, FunctionId, InvocationPrincipal, Metadata, NodeId, PlatformError,
    PlatformErrorCode, PrincipalKind, ReleaseDigest, ResourceBudget, ServiceId, SpanId, TenantId,
    TraceId,
};
use latent_executor::{BoundImport, ExecutionBackend};
use latent_manifest::{
    CapsuleManifest, ContractExport, ContractImport, ExecutionBackendKind, ExecutionRequirements,
    ObjectMetadata, StateModel, ThreadingModel,
};
use latent_node::{ActivationRunnerSnapshot, Phase0ActivationRunner, Phase0ActivationRunnerConfig};
use latent_routing::InvocationTarget;
use latent_scheduler::{CellClass, CellPool, CellPoolSnapshot, FixedCellPool, FixedCellPoolConfig};
use latent_wasmtime::{
    CapturedLog, Phase0WasmtimeConfig, Phase0WasmtimeEngineFactory, PreparedCacheSnapshot,
    RuntimeResourceSnapshot, CONTEXT_IMPORT, ECHO_DOMAIN_ERROR_MEDIA_TYPE, ECHO_EXPORT,
    ECHO_SUCCESS_MEDIA_TYPE, LOG_IMPORT,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest as _, Sha256};
use tokio::runtime::Builder;

pub const EXIT_SUCCESS: u8 = 0;
pub const EXIT_DOMAIN_ERROR: u8 = 10;
pub const EXIT_TIMEOUT_OR_CANCELLED: u8 = 11;
pub const EXIT_GUEST_TRAP: u8 = 12;
pub const EXIT_INVALID_COMPONENT_OR_CONFIGURATION: u8 = 13;
pub const EXIT_INTERNAL_SPIKE_FAILURE: u8 = 14;

const RESULT_SCHEMA_VERSION: &str = "latent.phase0.spike.result.v1";
const SURFACE_NAME: &str = "latentd.phase0-spike.invoke-once";
const DEFAULT_ACTIVATION_ID: &str = "phase0-spike-0000000000000001";
const SPIKE_NODE_ID: &str = "phase0-spike-node-0";
const SPIKE_TRACE_ID: &str = "phase0-spike-trace-0000000000000001";
const SPIKE_SPAN_ID: &str = "phase0-span-0001";
const SPIKE_WARNING: &str = "latentd Phase 0 spike: local validation surface only; not production-ready and not Phase 1 API compatible";
const MAX_DIAGNOSTIC_BYTES: usize = 512;
const MAX_ACTIVATION_ID_BYTES: usize = 128;
const MAX_RUNTIME_WORKERS: usize = 64;
const MAX_POOL_CAPACITY: u32 = 4096;
const MAX_QUEUE_CAPACITY: u32 = 65_536;
const MAX_COMPONENT_LIMIT_BYTES: usize = 1024 * 1024 * 1024;
const EPOCH_TICK_INTERVAL_MILLIS: u64 = 1;

#[derive(Debug, Parser)]
#[command(
    name = "latentd",
    version,
    about = "Latent Service Fabric data-plane runtime",
    long_about = "Latent Service Fabric data-plane runtime. The only implemented command is an explicitly non-production Phase 0 spike surface."
)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Subcommand)]
enum Command {
    #[command(
        name = "phase0-spike",
        visible_alias = "spike",
        about = "Run the finite, non-production Phase 0 activation spike"
    )]
    Phase0Spike(Phase0SpikeArgs),
}

#[derive(Debug, Args)]
struct Phase0SpikeArgs {
    #[command(subcommand)]
    command: Phase0Command,
}

#[derive(Debug, Subcommand)]
enum Phase0Command {
    #[command(
        name = "invoke-once",
        about = "Prepare one local capsule, invoke echo once, report cleanup, and exit"
    )]
    InvokeOnce(InvokeOnceArgs),
}

#[derive(Debug, Args)]
struct InvokeOnceArgs {
    /// Generated capsule directory or capsule.json path.
    #[arg(long, value_name = "PATH")]
    capsule: PathBuf,

    /// Component path override. Otherwise latent.dev/artifact is resolved beside the capsule.
    #[arg(long, value_name = "PATH")]
    component: Option<PathBuf>,

    /// UTF-8 input passed to examples:echo/api@0.1.0#echo.
    #[arg(long, value_name = "TEXT")]
    input: String,

    /// Immutable number of generic execution cells.
    #[arg(long, default_value_t = 1)]
    pool_capacity: u32,

    /// Immutable number of queued acquisitions.
    #[arg(long, default_value_t = 16)]
    pool_queue_capacity: u32,

    /// Immutable Tokio worker count, fixed before the capsule is loaded.
    #[arg(long, default_value_t = 1)]
    runtime_workers: usize,

    /// Per-activation aggregate linear-memory grant.
    #[arg(long, default_value_t = 4_194_304)]
    memory_bytes: u64,

    /// Per-activation Wasmtime fuel grant.
    #[arg(long, default_value_t = 1_000_000)]
    fuel: u64,

    /// Wall-clock activation timeout.
    #[arg(long, default_value_t = 1_000)]
    timeout_ms: u64,

    /// Optional explicit cancellation delay used by containment validation.
    #[arg(long)]
    cancel_after_ms: Option<u64>,

    /// Maximum accepted component file size.
    #[arg(long, default_value_t = 16_777_216)]
    component_max_bytes: usize,

    /// Maximum number of prepared components retained by this finite process.
    #[arg(long, default_value_t = 1)]
    prepared_cache_entries: usize,

    /// Maximum source bytes retained by the prepared-component cache.
    #[arg(long, default_value_t = 16_777_216)]
    prepared_cache_bytes: usize,

    /// Maximum guest log records retained for this process.
    #[arg(long, default_value_t = 8)]
    log_max_entries: usize,

    /// Maximum guest log bytes retained for this process.
    #[arg(long, default_value_t = 16_384)]
    log_max_bytes: usize,

    /// Deterministic activation identifier for the invocation.
    #[arg(long, default_value = DEFAULT_ACTIVATION_ID)]
    activation_id: String,
}

#[derive(Debug)]
struct ValidatedConfig {
    capsule: PathBuf,
    component: Option<PathBuf>,
    input: String,
    pool_capacity: u32,
    pool_queue_capacity: u32,
    runtime_workers: usize,
    memory_bytes: u64,
    fuel: u64,
    timeout_ms: u64,
    cancel_after_ms: Option<u64>,
    component_max_bytes: usize,
    prepared_cache_entries: usize,
    prepared_cache_bytes: usize,
    log_max_entries: usize,
    log_max_bytes: usize,
    activation_id: ActivationId,
}

impl TryFrom<InvokeOnceArgs> for ValidatedConfig {
    type Error = PlatformError;

    fn try_from(arguments: InvokeOnceArgs) -> Result<Self, Self::Error> {
        if arguments.pool_capacity == 0 || arguments.pool_capacity > MAX_POOL_CAPACITY {
            return Err(configuration_error(
                "pool capacity must be between 1 and 4096",
                [("pool_capacity", arguments.pool_capacity.to_string())],
            ));
        }
        if arguments.pool_queue_capacity == 0 || arguments.pool_queue_capacity > MAX_QUEUE_CAPACITY
        {
            return Err(configuration_error(
                "pool queue capacity must be between 1 and 65536",
                [(
                    "pool_queue_capacity",
                    arguments.pool_queue_capacity.to_string(),
                )],
            ));
        }
        if arguments.runtime_workers == 0 || arguments.runtime_workers > MAX_RUNTIME_WORKERS {
            return Err(configuration_error(
                "runtime worker count must be between 1 and 64",
                [("runtime_workers", arguments.runtime_workers.to_string())],
            ));
        }
        if arguments.memory_bytes == 0 {
            return Err(configuration_error(
                "memory grant must be greater than zero",
                [("memory_bytes", arguments.memory_bytes.to_string())],
            ));
        }
        if arguments.fuel == 0 {
            return Err(configuration_error(
                "fuel grant must be greater than zero",
                [("fuel", arguments.fuel.to_string())],
            ));
        }
        if arguments.timeout_ms == 0 {
            return Err(configuration_error(
                "invocation timeout must be greater than zero",
                [("timeout_ms", arguments.timeout_ms.to_string())],
            ));
        }
        if arguments.cancel_after_ms == Some(0) {
            return Err(configuration_error(
                "explicit cancellation delay must be greater than zero",
                [("cancel_after_ms", "0".to_owned())],
            ));
        }
        if arguments.component_max_bytes == 0
            || arguments.component_max_bytes > MAX_COMPONENT_LIMIT_BYTES
        {
            return Err(configuration_error(
                "component byte limit must be between 1 and 1073741824",
                [(
                    "component_max_bytes",
                    arguments.component_max_bytes.to_string(),
                )],
            ));
        }
        if arguments.prepared_cache_entries == 0 || arguments.prepared_cache_bytes == 0 {
            return Err(configuration_error(
                "prepared cache entry and byte limits must be greater than zero",
                [
                    (
                        "prepared_cache_entries",
                        arguments.prepared_cache_entries.to_string(),
                    ),
                    (
                        "prepared_cache_bytes",
                        arguments.prepared_cache_bytes.to_string(),
                    ),
                ],
            ));
        }
        if arguments.log_max_entries == 0 || arguments.log_max_bytes == 0 {
            return Err(configuration_error(
                "bounded log entry and byte limits must be greater than zero",
                [
                    ("log_max_entries", arguments.log_max_entries.to_string()),
                    ("log_max_bytes", arguments.log_max_bytes.to_string()),
                ],
            ));
        }
        if arguments.activation_id.trim().is_empty()
            || arguments.activation_id.len() > MAX_ACTIVATION_ID_BYTES
        {
            return Err(configuration_error(
                "activation ID must contain between 1 and 128 UTF-8 bytes",
                [(
                    "activation_id_bytes",
                    arguments.activation_id.len().to_string(),
                )],
            ));
        }

        Ok(Self {
            capsule: arguments.capsule,
            component: arguments.component,
            input: arguments.input,
            pool_capacity: arguments.pool_capacity,
            pool_queue_capacity: arguments.pool_queue_capacity,
            runtime_workers: arguments.runtime_workers,
            memory_bytes: arguments.memory_bytes,
            fuel: arguments.fuel,
            timeout_ms: arguments.timeout_ms,
            cancel_after_ms: arguments.cancel_after_ms,
            component_max_bytes: arguments.component_max_bytes,
            prepared_cache_entries: arguments.prepared_cache_entries,
            prepared_cache_bytes: arguments.prepared_cache_bytes,
            log_max_entries: arguments.log_max_entries,
            log_max_bytes: arguments.log_max_bytes,
            activation_id: ActivationId(arguments.activation_id),
        })
    }
}

#[derive(Debug, Serialize)]
struct SpikeResult {
    schema_version: &'static str,
    surface: &'static str,
    production_ready: bool,
    phase1_api_compatible: bool,
    activation_id: String,
    outcome: String,
    terminal_state: Option<String>,
    output: Option<OutputReport>,
    error: Option<ErrorReport>,
    elapsed_time_micros: u64,
    consumption: ConsumptionReport,
    cell: CellReport,
    logs: Vec<LogReport>,
    topology: TopologyReport,
    preparation: PreparationReport,
    shutdown: ShutdownReport,
}

#[derive(Debug, Serialize)]
struct OutputReport {
    media_type: String,
    utf8: String,
    bytes: usize,
}

#[derive(Debug, Serialize)]
struct ErrorReport {
    kind: String,
    code: String,
    message: String,
    retryable: bool,
    details: Vec<ErrorDetailReport>,
}

#[derive(Debug, Serialize)]
struct ErrorDetailReport {
    kind: String,
    fields: Metadata,
}

#[derive(Debug, Default, Serialize)]
struct ConsumptionReport {
    cpu_fuel: u64,
    peak_memory_bytes: u64,
    wall_time_micros: u64,
    child_calls: u32,
    outbound_requests: u32,
    state_read_bytes: u64,
    state_write_bytes: u64,
    blob_read_bytes: u64,
    blob_write_bytes: u64,
    log_bytes: u64,
    effect_count: u32,
}

#[derive(Debug, Serialize)]
struct CellReport {
    disposition: String,
    pool_before: Option<PoolSnapshotReport>,
    pool_after: Option<PoolSnapshotReport>,
}

#[derive(Debug, Clone, Serialize)]
struct PoolSnapshotReport {
    class: String,
    capacity: u32,
    available: u32,
    queue_depth: u32,
    active_leases: u32,
    quarantined: u32,
}

#[derive(Debug, Serialize)]
struct LogReport {
    activation_id: String,
    level: String,
    message: String,
    fields: Metadata,
}

#[derive(Debug, Clone, Serialize)]
struct TopologyReport {
    initialized: bool,
    runtime_workers: usize,
    wasmtime_epoch_ticker_threads: u32,
    pool_capacity: u32,
    pool_queue_capacity: u32,
    listener_socket_count: u32,
    unchanged: bool,
}

#[derive(Debug, Default, Serialize)]
struct PreparationReport {
    component_bytes: u64,
    cache_after_prepare: CacheSnapshotReport,
    cache_after_release: CacheSnapshotReport,
}

#[derive(Debug, Default, Serialize)]
struct CacheSnapshotReport {
    entries: usize,
    source_bytes: usize,
    maximum_entries: usize,
    maximum_source_bytes: usize,
}

#[derive(Debug, Default, Serialize)]
struct ShutdownReport {
    clean: bool,
    runtime_stopped: bool,
    active_leases: u32,
    queued_waiters: u32,
    cancellation_registrations: u64,
    running_invocations: u64,
    retained_log_entries: usize,
    prepared_cache_entries: usize,
    backend_resources: RuntimeResourceReport,
}

#[derive(Debug, Default, Serialize)]
struct RuntimeResourceReport {
    active_invocations: u64,
    live_stores: u64,
    live_host_states: u64,
    live_component_instances: u64,
    live_temporary_buffers: u64,
    live_cancellation_probes: u64,
    stores_created: u64,
}

struct ProcessReport {
    result: SpikeResult,
    exit_code: u8,
}

enum EntryOutcome {
    Report(ProcessReport),
    Printed(ExitCode),
}

pub fn main_entry() -> ExitCode {
    let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(run_entry));
    match outcome {
        Ok(EntryOutcome::Printed(code)) => code,
        Ok(EntryOutcome::Report(report)) => emit_report(report),
        Err(payload) => {
            let message = panic_message(&payload);
            eprintln!("internal Phase 0 spike panic: {message}");
            emit_report(internal_uninitialized_report(
                DEFAULT_ACTIVATION_ID,
                format!("Phase 0 spike panicked: {message}"),
            ))
        }
    }
}

fn run_entry() -> EntryOutcome {
    let cli = match Cli::try_parse_from(std::env::args_os()) {
        Ok(cli) => cli,
        Err(error)
            if matches!(
                error.kind(),
                ErrorKind::DisplayHelp | ErrorKind::DisplayVersion
            ) =>
        {
            let _ = error.print();
            return EntryOutcome::Printed(ExitCode::SUCCESS);
        }
        Err(error) => {
            eprint!("{error}");
            return EntryOutcome::Report(invalid_uninitialized_report(
                DEFAULT_ACTIVATION_ID,
                bounded_text(&error.to_string(), MAX_DIAGNOSTIC_BYTES),
            ));
        }
    };

    eprintln!("{SPIKE_WARNING}");
    match cli.command {
        Command::Phase0Spike(Phase0SpikeArgs {
            command: Phase0Command::InvokeOnce(arguments),
        }) => match ValidatedConfig::try_from(arguments) {
            Ok(config) => EntryOutcome::Report(run_validated(config)),
            Err(error) => {
                eprintln!(
                    "configuration rejected before runtime initialization: {}",
                    error.message
                );
                EntryOutcome::Report(platform_uninitialized_report(
                    DEFAULT_ACTIVATION_ID,
                    error,
                    EXIT_INVALID_COMPONENT_OR_CONFIGURATION,
                    "invalid_component_or_configuration",
                ))
            }
        },
    }
}

fn run_validated(config: ValidatedConfig) -> ProcessReport {
    let topology = TopologyReport {
        initialized: false,
        runtime_workers: config.runtime_workers,
        wasmtime_epoch_ticker_threads: 1,
        pool_capacity: config.pool_capacity,
        pool_queue_capacity: config.pool_queue_capacity,
        listener_socket_count: 0,
        unchanged: false,
    };

    let runtime = match Builder::new_multi_thread()
        .worker_threads(config.runtime_workers)
        .thread_name("latentd-phase0-worker")
        .enable_time()
        .build()
    {
        Ok(runtime) => runtime,
        Err(error) => {
            return platform_uninitialized_report(
                &config.activation_id.0,
                spike_error(
                    PlatformErrorCode::Internal,
                    format!("failed to construct the fixed Tokio runtime: {error}"),
                    "phase0-spike.runtime-build-failed",
                    [("runtime_workers", config.runtime_workers.to_string())],
                ),
                EXIT_INTERNAL_SPIKE_FAILURE,
                "internal_spike_failure",
            );
        }
    };

    let pool = match FixedCellPool::new(FixedCellPoolConfig::new(
        NodeId(SPIKE_NODE_ID.to_owned()),
        CellClass::Standard,
        config.pool_capacity,
        config.pool_queue_capacity,
    )) {
        Ok(pool) => Arc::new(pool),
        Err(error) => {
            drop(runtime);
            return platform_uninitialized_report(
                &config.activation_id.0,
                error,
                EXIT_INVALID_COMPONENT_OR_CONFIGURATION,
                "invalid_component_or_configuration",
            );
        }
    };

    let mut initialized_topology = topology;
    initialized_topology.initialized = true;
    let mut report = runtime.block_on(execute_once(
        &config,
        Arc::clone(&pool),
        initialized_topology,
    ));
    drop(runtime);
    report.result.shutdown.runtime_stopped = true;
    recompute_shutdown(&mut report.result.shutdown);
    report
}

async fn execute_once(
    config: &ValidatedConfig,
    pool: Arc<FixedCellPool>,
    topology: TopologyReport,
) -> ProcessReport {
    let pool_before = pool.observations();
    let loaded = match load_artifact(config) {
        Ok(loaded) => loaded,
        Err(error) => {
            return preflight_failure(config, topology, pool_before, pool.observations(), 0, error);
        }
    };

    if let Err(error) = validate_requested_budget(config, &loaded.artifact.manifest) {
        return preflight_failure(
            config,
            topology,
            pool_before,
            pool.observations(),
            loaded.component_bytes,
            error,
        );
    }

    let declared_budget = &loaded.artifact.manifest.execution.resource_budget_ceiling;
    let wasmtime_config = Phase0WasmtimeConfig {
        maximum_component_bytes: config.component_max_bytes,
        maximum_memory_bytes: declared_budget.memory_bytes,
        maximum_fuel: declared_budget.cpu_fuel,
        prepared_cache_maximum_entries: config.prepared_cache_entries,
        prepared_cache_maximum_source_bytes: config.prepared_cache_bytes,
        invocation_log_maximum_entries: config.log_max_entries,
        invocation_log_maximum_bytes: config.log_max_bytes,
        retained_log_maximum_entries: config.log_max_entries,
        retained_log_maximum_bytes: config.log_max_bytes,
        epoch_tick_interval_millis: EPOCH_TICK_INTERVAL_MILLIS,
        ..Phase0WasmtimeConfig::default()
    };
    let factory = match Phase0WasmtimeEngineFactory::new(wasmtime_config) {
        Ok(factory) => factory,
        Err(error) => {
            return preflight_failure(
                config,
                topology,
                pool_before,
                pool.observations(),
                loaded.component_bytes,
                error,
            );
        }
    };
    let preparation_key =
        factory.preparation_key(loaded.artifact.descriptor.release_digest.clone());
    let backend = Arc::new(factory.create_backend_instance());
    drop(factory);

    let prepared = match backend.prepare(&loaded.artifact, &preparation_key).await {
        Ok(prepared) => prepared,
        Err(error) => {
            let resources = backend.resource_snapshot();
            let cache = backend.cache_snapshot();
            let logs = backend.log_sink();
            logs.clear();
            return preflight_failure_with_backend(
                config,
                topology,
                pool_before,
                pool.observations(),
                loaded.component_bytes,
                cache,
                resources,
                error,
            );
        }
    };
    let cache_after_prepare = backend.cache_snapshot();

    let backend_for_runner: Arc<dyn ExecutionBackend> = backend.clone();
    let pool_for_runner: Arc<dyn CellPool> = pool.clone();
    let runner = match Phase0ActivationRunner::new(
        Phase0ActivationRunnerConfig::default(),
        pool_for_runner,
        backend_for_runner,
        prepared.clone(),
        bound_imports(),
    ) {
        Ok(runner) => Arc::new(runner),
        Err(error) => {
            let release_error = backend.release(prepared).await.err();
            let error = release_error.map_or(error, |release_error| {
                cleanup_error("prepared-component release", release_error)
            });
            let cache_after_release = backend.cache_snapshot();
            return preflight_failure_with_preparation(
                config,
                topology,
                pool_before,
                pool.observations(),
                loaded.component_bytes,
                cache_after_prepare,
                cache_after_release,
                backend.resource_snapshot(),
                error,
            );
        }
    };

    let deadline = match now_unix_millis().checked_add(config.timeout_ms) {
        Some(deadline) => deadline,
        None => {
            let _ = backend.release(prepared).await;
            return preflight_failure_with_preparation(
                config,
                topology,
                pool_before,
                pool.observations(),
                loaded.component_bytes,
                cache_after_prepare,
                backend.cache_snapshot(),
                backend.resource_snapshot(),
                configuration_error(
                    "invocation timeout overflows the Unix millisecond deadline",
                    [("timeout_ms", config.timeout_ms.to_string())],
                ),
            );
        }
    };
    let envelope = activation_envelope(config, &loaded.artifact.manifest, deadline);

    let started = Instant::now();
    let invocation = runner.invoke(envelope);
    tokio::pin!(invocation);
    let outcome = if let Some(cancel_after_ms) = config.cancel_after_ms {
        tokio::select! {
            biased;
            outcome = &mut invocation => outcome,
            () = tokio::time::sleep(Duration::from_millis(cancel_after_ms)) => {
                if let Err(error) = runner
                    .cancel(&config.activation_id, "phase0-spike explicit cancellation")
                    .await
                {
                    eprintln!(
                        "explicit cancellation raced with completion: {}",
                        bounded_text(&error.message, MAX_DIAGNOSTIC_BYTES)
                    );
                }
                invocation.await
            }
        }
    } else {
        invocation.await
    };
    let elapsed_time_micros = u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX);

    let runner_snapshot = runner.snapshot();
    let pool_after = pool.observations();
    let resources = backend.resource_snapshot();
    let log_sink = backend.log_sink();
    let logs = log_sink.snapshot_for(&config.activation_id);
    log_sink.clear();
    let retained_log_entries = log_sink.snapshot().len();
    let disposition = cell_disposition(&runner_snapshot);

    let (mut result, mut exit_code) = activation_result(
        config,
        topology,
        pool_before,
        pool_after,
        loaded.component_bytes,
        cache_after_prepare,
        runner_snapshot,
        resources,
        logs,
        retained_log_entries,
        disposition,
        outcome,
        elapsed_time_micros,
    );

    if let Err(error) = backend.release(prepared).await {
        apply_cleanup_failure(
            &mut result,
            cleanup_error("prepared-component release", error),
        );
        exit_code = EXIT_INTERNAL_SPIKE_FAILURE;
    }
    result.preparation.cache_after_release = cache_report(&backend.cache_snapshot());
    result.shutdown.prepared_cache_entries = backend.cache_snapshot().entries;
    recompute_shutdown(&mut result.shutdown);

    if !result.shutdown.clean_without_runtime() {
        let error = dirty_shutdown_error(&result.shutdown);
        apply_cleanup_failure(&mut result, error);
        exit_code = EXIT_INTERNAL_SPIKE_FAILURE;
    }

    ProcessReport { result, exit_code }
}

fn activation_result(
    config: &ValidatedConfig,
    mut topology: TopologyReport,
    pool_before: CellPoolSnapshot,
    pool_after: CellPoolSnapshot,
    component_bytes: u64,
    cache_after_prepare: PreparedCacheSnapshot,
    runner_snapshot: ActivationRunnerSnapshot,
    resources: RuntimeResourceSnapshot,
    logs: Vec<CapturedLog>,
    retained_log_entries: usize,
    disposition: String,
    outcome: ActivationOutcome,
    elapsed_time_micros: u64,
) -> (SpikeResult, u8) {
    topology.unchanged = topology.pool_capacity == pool_before.capacity
        && pool_before.capacity == pool_after.capacity
        && topology.listener_socket_count == 0;

    let (outcome_name, terminal_state, output, error, consumption, exit_code) =
        classify_activation_outcome(outcome);
    let shutdown = ShutdownReport {
        clean: false,
        runtime_stopped: false,
        active_leases: pool_after.active_leases,
        queued_waiters: pool_after.queue_depth,
        cancellation_registrations: runner_snapshot.active_cancellation_registrations,
        running_invocations: runner_snapshot.running_invocations,
        retained_log_entries,
        prepared_cache_entries: cache_after_prepare.entries,
        backend_resources: runtime_resource_report(&resources),
    };

    (
        SpikeResult {
            schema_version: RESULT_SCHEMA_VERSION,
            surface: SURFACE_NAME,
            production_ready: false,
            phase1_api_compatible: false,
            activation_id: config.activation_id.0.clone(),
            outcome: outcome_name,
            terminal_state,
            output,
            error,
            elapsed_time_micros,
            consumption,
            cell: CellReport {
                disposition,
                pool_before: Some(pool_report(&pool_before)),
                pool_after: Some(pool_report(&pool_after)),
            },
            logs: logs.into_iter().map(log_report).collect(),
            topology,
            preparation: PreparationReport {
                component_bytes,
                cache_after_prepare: cache_report(&cache_after_prepare),
                cache_after_release: CacheSnapshotReport::default(),
            },
            shutdown,
        },
        exit_code,
    )
}

fn classify_activation_outcome(
    outcome: ActivationOutcome,
) -> (
    String,
    Option<String>,
    Option<OutputReport>,
    Option<ErrorReport>,
    ConsumptionReport,
    u8,
) {
    match outcome {
        ActivationOutcome::Succeeded(success)
            if success.output_media_type == ECHO_DOMAIN_ERROR_MEDIA_TYPE =>
        {
            let domain_code = domain_error_code(&success.output);
            let output = output_report(success.output, success.output_media_type);
            (
                "domain_error".to_owned(),
                Some("completed".to_owned()),
                Some(output),
                Some(ErrorReport {
                    kind: "domain".to_owned(),
                    code: domain_code.clone(),
                    message: format!("guest returned declared echo domain error: {domain_code}"),
                    retryable: false,
                    details: Vec::new(),
                }),
                consumption_report(&success.consumption),
                EXIT_DOMAIN_ERROR,
            )
        }
        ActivationOutcome::Succeeded(success) => (
            "success".to_owned(),
            Some("completed".to_owned()),
            Some(output_report(success.output, success.output_media_type)),
            None,
            consumption_report(&success.consumption),
            EXIT_SUCCESS,
        ),
        ActivationOutcome::Failed {
            terminal_state,
            error,
            consumption,
        } => {
            let (outcome_name, exit_code) = match error.code {
                PlatformErrorCode::Cancelled => ("cancelled".to_owned(), EXIT_TIMEOUT_OR_CANCELLED),
                PlatformErrorCode::DeadlineExceeded => {
                    ("timeout".to_owned(), EXIT_TIMEOUT_OR_CANCELLED)
                }
                PlatformErrorCode::GuestTrap => ("trap".to_owned(), EXIT_GUEST_TRAP),
                PlatformErrorCode::ResourceExhausted => {
                    ("resource_exhausted".to_owned(), EXIT_GUEST_TRAP)
                }
                PlatformErrorCode::InvalidArgument
                | PlatformErrorCode::CorruptArtifact
                | PlatformErrorCode::IncompatibleContract => (
                    "invalid_component_or_configuration".to_owned(),
                    EXIT_INVALID_COMPONENT_OR_CONFIGURATION,
                ),
                _ => (
                    "internal_spike_failure".to_owned(),
                    EXIT_INTERNAL_SPIKE_FAILURE,
                ),
            };
            (
                outcome_name,
                Some(terminal_state_name(terminal_state).to_owned()),
                None,
                Some(platform_error_report(error)),
                consumption_report(&consumption),
                exit_code,
            )
        }
    }
}

fn preflight_failure(
    config: &ValidatedConfig,
    topology: TopologyReport,
    pool_before: CellPoolSnapshot,
    pool_after: CellPoolSnapshot,
    component_bytes: u64,
    error: PlatformError,
) -> ProcessReport {
    preflight_failure_with_preparation(
        config,
        topology,
        pool_before,
        pool_after,
        component_bytes,
        empty_cache_snapshot(config),
        empty_cache_snapshot(config),
        RuntimeResourceSnapshot::default(),
        error,
    )
}

fn preflight_failure_with_backend(
    config: &ValidatedConfig,
    topology: TopologyReport,
    pool_before: CellPoolSnapshot,
    pool_after: CellPoolSnapshot,
    component_bytes: u64,
    cache: PreparedCacheSnapshot,
    resources: RuntimeResourceSnapshot,
    error: PlatformError,
) -> ProcessReport {
    preflight_failure_with_preparation(
        config,
        topology,
        pool_before,
        pool_after,
        component_bytes,
        cache.clone(),
        cache,
        resources,
        error,
    )
}

fn preflight_failure_with_preparation(
    config: &ValidatedConfig,
    mut topology: TopologyReport,
    pool_before: CellPoolSnapshot,
    pool_after: CellPoolSnapshot,
    component_bytes: u64,
    cache_after_prepare: PreparedCacheSnapshot,
    cache_after_release: PreparedCacheSnapshot,
    resources: RuntimeResourceSnapshot,
    error: PlatformError,
) -> ProcessReport {
    eprintln!(
        "Phase 0 spike rejected input before leasing a cell: {}",
        bounded_text(&error.message, MAX_DIAGNOSTIC_BYTES)
    );
    topology.unchanged = topology.pool_capacity == pool_before.capacity
        && pool_before.capacity == pool_after.capacity
        && topology.listener_socket_count == 0;
    let internal = error.code == PlatformErrorCode::Internal;
    let mut shutdown = ShutdownReport {
        clean: false,
        runtime_stopped: false,
        active_leases: pool_after.active_leases,
        queued_waiters: pool_after.queue_depth,
        cancellation_registrations: 0,
        running_invocations: 0,
        retained_log_entries: 0,
        prepared_cache_entries: cache_after_release.entries,
        backend_resources: runtime_resource_report(&resources),
    };
    recompute_shutdown(&mut shutdown);

    ProcessReport {
        result: SpikeResult {
            schema_version: RESULT_SCHEMA_VERSION,
            surface: SURFACE_NAME,
            production_ready: false,
            phase1_api_compatible: false,
            activation_id: config.activation_id.0.clone(),
            outcome: if internal {
                "internal_spike_failure".to_owned()
            } else {
                "invalid_component_or_configuration".to_owned()
            },
            terminal_state: Some("rejected".to_owned()),
            output: None,
            error: Some(platform_error_report(error)),
            elapsed_time_micros: 0,
            consumption: ConsumptionReport::default(),
            cell: CellReport {
                disposition: "not_leased".to_owned(),
                pool_before: Some(pool_report(&pool_before)),
                pool_after: Some(pool_report(&pool_after)),
            },
            logs: Vec::new(),
            topology,
            preparation: PreparationReport {
                component_bytes,
                cache_after_prepare: cache_report(&cache_after_prepare),
                cache_after_release: cache_report(&cache_after_release),
            },
            shutdown,
        },
        exit_code: if internal {
            EXIT_INTERNAL_SPIKE_FAILURE
        } else {
            EXIT_INVALID_COMPONENT_OR_CONFIGURATION
        },
    }
}

fn invalid_uninitialized_report(activation_id: &str, message: String) -> ProcessReport {
    platform_uninitialized_report(
        activation_id,
        configuration_error(message, std::iter::empty::<(&str, String)>()),
        EXIT_INVALID_COMPONENT_OR_CONFIGURATION,
        "invalid_component_or_configuration",
    )
}

fn internal_uninitialized_report(activation_id: &str, message: String) -> ProcessReport {
    platform_uninitialized_report(
        activation_id,
        spike_error(
            PlatformErrorCode::Internal,
            message,
            "phase0-spike.internal-panic",
            std::iter::empty::<(&str, String)>(),
        ),
        EXIT_INTERNAL_SPIKE_FAILURE,
        "internal_spike_failure",
    )
}

fn platform_uninitialized_report(
    activation_id: &str,
    error: PlatformError,
    exit_code: u8,
    outcome: &str,
) -> ProcessReport {
    ProcessReport {
        result: SpikeResult {
            schema_version: RESULT_SCHEMA_VERSION,
            surface: SURFACE_NAME,
            production_ready: false,
            phase1_api_compatible: false,
            activation_id: activation_id.to_owned(),
            outcome: outcome.to_owned(),
            terminal_state: Some("rejected".to_owned()),
            output: None,
            error: Some(platform_error_report(error)),
            elapsed_time_micros: 0,
            consumption: ConsumptionReport::default(),
            cell: CellReport {
                disposition: "not_leased".to_owned(),
                pool_before: None,
                pool_after: None,
            },
            logs: Vec::new(),
            topology: TopologyReport {
                initialized: false,
                runtime_workers: 0,
                wasmtime_epoch_ticker_threads: 0,
                pool_capacity: 0,
                pool_queue_capacity: 0,
                listener_socket_count: 0,
                unchanged: true,
            },
            preparation: PreparationReport::default(),
            shutdown: ShutdownReport {
                clean: true,
                runtime_stopped: true,
                ..ShutdownReport::default()
            },
        },
        exit_code,
    }
}

fn emit_report(report: ProcessReport) -> ExitCode {
    let mut stdout = io::stdout().lock();
    if serde_json::to_writer(&mut stdout, &report.result).is_err()
        || stdout.write_all(b"\n").is_err()
        || stdout.flush().is_err()
    {
        eprintln!("failed to write the Phase 0 machine-readable result to stdout");
        return ExitCode::from(EXIT_INTERNAL_SPIKE_FAILURE);
    }
    ExitCode::from(report.exit_code)
}

#[derive(Debug)]
struct LoadedArtifact {
    artifact: CapsuleArtifact,
    component_bytes: u64,
}

fn load_artifact(config: &ValidatedConfig) -> Result<LoadedArtifact, PlatformError> {
    let manifest_path = if config.capsule.is_dir() {
        config.capsule.join("capsule.json")
    } else {
        config.capsule.clone()
    };
    if !manifest_path.is_file() {
        return Err(input_error(
            format!(
                "capsule manifest is not a readable file: {}",
                manifest_path.display()
            ),
            "phase0-spike.capsule-not-found",
            [("capsule", manifest_path.display().to_string())],
        ));
    }

    let manifest_bytes = fs::read(&manifest_path).map_err(|error| {
        input_error(
            format!("failed to read capsule manifest: {error}"),
            "phase0-spike.capsule-read-failed",
            [("capsule", manifest_path.display().to_string())],
        )
    })?;
    let document: CapsuleDocument = serde_json::from_slice(&manifest_bytes).map_err(|error| {
        input_error(
            format!("capsule manifest is not valid JSON for the spike: {error}"),
            "phase0-spike.capsule-decode-failed",
            [("capsule", manifest_path.display().to_string())],
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
                input_error(
                    "--component is required when the capsule lacks latent.dev/artifact",
                    "phase0-spike.component-path-missing",
                    [("capsule", manifest_path.display().to_string())],
                )
            })?,
    };
    if !component_path.is_file() {
        return Err(input_error(
            format!(
                "component is not a readable file: {}",
                component_path.display()
            ),
            "phase0-spike.component-not-found",
            [("component", component_path.display().to_string())],
        ));
    }

    let metadata = fs::metadata(&component_path).map_err(|error| {
        input_error(
            format!("failed to inspect component file: {error}"),
            "phase0-spike.component-inspection-failed",
            [("component", component_path.display().to_string())],
        )
    })?;
    let component_bytes = metadata.len();
    let maximum = u64::try_from(config.component_max_bytes).unwrap_or(u64::MAX);
    if component_bytes == 0 || component_bytes > maximum {
        return Err(input_error(
            "component size is zero or exceeds --component-max-bytes",
            "phase0-spike.component-size-rejected",
            [
                ("component_bytes", component_bytes.to_string()),
                ("component_max_bytes", maximum.to_string()),
            ],
        ));
    }
    let prepared_cache_maximum = u64::try_from(config.prepared_cache_bytes).unwrap_or(u64::MAX);
    if component_bytes > prepared_cache_maximum {
        return Err(configuration_error(
            "component cannot fit in the bounded prepared cache",
            [
                ("component_bytes", component_bytes.to_string()),
                ("prepared_cache_bytes", prepared_cache_maximum.to_string()),
            ],
        ));
    }

    let bytes = fs::read(&component_path).map_err(|error| {
        input_error(
            format!("failed to read component file: {error}"),
            "phase0-spike.component-read-failed",
            [("component", component_path.display().to_string())],
        )
    })?;
    let actual_digest = component_digest(&bytes);
    if manifest.component_digest.0 != actual_digest {
        return Err(input_error(
            "component digest does not match capsule metadata",
            "phase0-spike.component-digest-mismatch",
            [
                ("expected", manifest.component_digest.0.clone()),
                ("actual", actual_digest),
            ],
        ));
    }

    let size_bytes = u64::try_from(bytes.len()).map_err(|_| {
        input_error(
            "component size cannot be represented by the artifact descriptor",
            "phase0-spike.component-size-overflow",
            std::iter::empty::<(&str, String)>(),
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

    Ok(LoadedArtifact {
        artifact: CapsuleArtifact {
            descriptor,
            manifest,
            contracts: Vec::new(),
            component_bytes: bytes,
        },
        component_bytes: size_bytes,
    })
}

fn validate_requested_budget(
    config: &ValidatedConfig,
    manifest: &CapsuleManifest,
) -> Result<(), PlatformError> {
    let declared = &manifest.execution.resource_budget_ceiling;
    if declared.memory_bytes == 0 || declared.cpu_fuel == 0 {
        return Err(input_error(
            "capsule declares a zero memory or fuel ceiling",
            "phase0-spike.invalid-capsule-budget",
            [
                ("declared_memory_bytes", declared.memory_bytes.to_string()),
                ("declared_cpu_fuel", declared.cpu_fuel.to_string()),
            ],
        ));
    }
    if config.memory_bytes > declared.memory_bytes || config.fuel > declared.cpu_fuel {
        return Err(configuration_error(
            "requested invocation budget exceeds the capsule-declared ceiling",
            [
                ("requested_memory_bytes", config.memory_bytes.to_string()),
                ("declared_memory_bytes", declared.memory_bytes.to_string()),
                ("requested_cpu_fuel", config.fuel.to_string()),
                ("declared_cpu_fuel", declared.cpu_fuel.to_string()),
            ],
        ));
    }
    Ok(())
}

fn activation_envelope(
    config: &ValidatedConfig,
    manifest: &CapsuleManifest,
    deadline: u64,
) -> ActivationEnvelope {
    let tenant = manifest
        .metadata
        .tenant
        .clone()
        .unwrap_or_else(|| TenantId("phase0-spike".to_owned()));
    let mut budget = manifest.execution.resource_budget_ceiling.clone();
    budget.cpu_fuel = config.fuel;
    budget.memory_bytes = config.memory_bytes;
    budget.wall_deadline_unix_millis = Some(deadline);

    ActivationEnvelope {
        activation_id: config.activation_id.clone(),
        parent_activation_id: None,
        root_activation_id: config.activation_id.clone(),
        principal: InvocationPrincipal {
            subject: "phase0-spike-user".to_owned(),
            kind: PrincipalKind::User,
            tenant: Some(tenant.clone()),
            service: None,
            claims: Metadata::from([
                ("role".to_owned(), "phase0-spike".to_owned()),
                ("surface".to_owned(), SURFACE_NAME.to_owned()),
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
        deadline_unix_millis: Some(deadline),
        priority: 0,
        trace: TraceContext {
            trace_id: TraceId(SPIKE_TRACE_ID.to_owned()),
            span_id: SpanId(SPIKE_SPAN_ID.to_owned()),
            trace_flags: 1,
            baggage: Metadata::from([("surface".to_owned(), "phase0-spike".to_owned())]),
        },
        idempotency_key: None,
        retry_attempt: 0,
        budget,
        metadata: Metadata::from([
            ("mode".to_owned(), "invoke-once".to_owned()),
            ("production-ready".to_owned(), "false".to_owned()),
        ]),
        input: config.input.as_bytes().to_vec(),
        input_media_type: ECHO_SUCCESS_MEDIA_TYPE.to_owned(),
    }
}

fn bound_imports() -> Vec<BoundImport> {
    vec![
        BoundImport {
            capability: CapabilityId("context".to_owned()),
            contract: CONTEXT_IMPORT.to_owned(),
            opaque_handle: "phase0-spike-activation-context".to_owned(),
        },
        BoundImport {
            capability: CapabilityId("log".to_owned()),
            contract: LOG_IMPORT.to_owned(),
            opaque_handle: "phase0-spike-bounded-log".to_owned(),
        },
    ]
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
            return Err(input_error(
                "capsule document kind must be Capsule",
                "phase0-spike.unexpected-document-kind",
                [("kind", self.kind)],
            ));
        }
        if self.metadata.name.trim().is_empty()
            || self.component.digest.trim().is_empty()
            || self.component.version.trim().is_empty()
            || self.component.world.trim().is_empty()
        {
            return Err(input_error(
                "capsule identity and component fields must be non-empty",
                "phase0-spike.empty-capsule-field",
                std::iter::empty::<(&str, String)>(),
            ));
        }

        let backend = match self.execution.backend.as_str() {
            "wasm-component" => ExecutionBackendKind::WasmComponent,
            value => {
                return Err(input_error(
                    "the Phase 0 spike supports only the wasm-component backend",
                    "phase0-spike.unsupported-backend",
                    [("backend", value.to_owned())],
                ));
            }
        };
        let threading = match self.execution.threading.as_str() {
            "single-threaded" => ThreadingModel::SingleThreaded,
            "reentrant" => ThreadingModel::Reentrant,
            "cooperative" => ThreadingModel::Cooperative,
            value => {
                return Err(input_error(
                    "capsule declares an unknown threading model",
                    "phase0-spike.unknown-threading-model",
                    [("threading", value.to_owned())],
                ));
            }
        };
        let state_model = match self.execution.state_model.as_str() {
            "stateless" => StateModel::Stateless,
            "transactional-keyed" => StateModel::TransactionalKeyed,
            "entity" => StateModel::Entity,
            "durable-workflow" => StateModel::DurableWorkflow,
            value => {
                return Err(input_error(
                    "capsule declares an unknown state model",
                    "phase0-spike.unknown-state-model",
                    [("state_model", value.to_owned())],
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

fn platform_error_report(error: PlatformError) -> ErrorReport {
    ErrorReport {
        kind: "platform".to_owned(),
        code: platform_error_code_name(error.code).to_owned(),
        message: error.message,
        retryable: error.retryable,
        details: error
            .details
            .into_iter()
            .map(|detail| ErrorDetailReport {
                kind: detail.kind,
                fields: detail.fields,
            })
            .collect(),
    }
}

fn output_report(output: Vec<u8>, media_type: String) -> OutputReport {
    let bytes = output.len();
    OutputReport {
        media_type,
        utf8: String::from_utf8_lossy(&output).into_owned(),
        bytes,
    }
}

fn domain_error_code(output: &[u8]) -> String {
    serde_json::from_slice::<Value>(output)
        .ok()
        .and_then(|document| {
            document
                .get("error")
                .and_then(Value::as_str)
                .map(str::to_owned)
        })
        .unwrap_or_else(|| "declared-domain-error".to_owned())
}

fn consumption_report(consumption: &BudgetConsumption) -> ConsumptionReport {
    ConsumptionReport {
        cpu_fuel: consumption.cpu_fuel,
        peak_memory_bytes: consumption.peak_memory_bytes,
        wall_time_micros: consumption.wall_time_micros,
        child_calls: consumption.child_calls,
        outbound_requests: consumption.outbound_requests,
        state_read_bytes: consumption.state_read_bytes,
        state_write_bytes: consumption.state_write_bytes,
        blob_read_bytes: consumption.blob_read_bytes,
        blob_write_bytes: consumption.blob_write_bytes,
        log_bytes: consumption.log_bytes,
        effect_count: consumption.effect_count,
    }
}

fn pool_report(snapshot: &CellPoolSnapshot) -> PoolSnapshotReport {
    PoolSnapshotReport {
        class: cell_class_name(snapshot.class).to_owned(),
        capacity: snapshot.capacity,
        available: snapshot.available,
        queue_depth: snapshot.queue_depth,
        active_leases: snapshot.active_leases,
        quarantined: snapshot.quarantined,
    }
}

fn cache_report(snapshot: &PreparedCacheSnapshot) -> CacheSnapshotReport {
    CacheSnapshotReport {
        entries: snapshot.entries,
        source_bytes: snapshot.source_bytes,
        maximum_entries: snapshot.maximum_entries,
        maximum_source_bytes: snapshot.maximum_source_bytes,
    }
}

fn runtime_resource_report(snapshot: &RuntimeResourceSnapshot) -> RuntimeResourceReport {
    RuntimeResourceReport {
        active_invocations: snapshot.active_invocations,
        live_stores: snapshot.live_stores,
        live_host_states: snapshot.live_host_states,
        live_component_instances: snapshot.live_component_instances,
        live_temporary_buffers: snapshot.live_temporary_buffers,
        live_cancellation_probes: snapshot.live_cancellation_probes,
        stores_created: snapshot.stores_created,
    }
}

fn log_report(log: CapturedLog) -> LogReport {
    LogReport {
        activation_id: log.activation_id.0,
        level: log.level,
        message: log.message,
        fields: log.fields,
    }
}

fn cell_disposition(snapshot: &ActivationRunnerSnapshot) -> String {
    if snapshot.quarantined_cells > 0 {
        "quarantined".to_owned()
    } else if snapshot.released_cells > 0 {
        "released".to_owned()
    } else {
        "not_dispositioned".to_owned()
    }
}

impl ShutdownReport {
    fn clean_without_runtime(&self) -> bool {
        self.active_leases == 0
            && self.queued_waiters == 0
            && self.cancellation_registrations == 0
            && self.running_invocations == 0
            && self.retained_log_entries == 0
            && self.prepared_cache_entries == 0
            && self.backend_resources.active_invocations == 0
            && self.backend_resources.live_stores == 0
            && self.backend_resources.live_host_states == 0
            && self.backend_resources.live_component_instances == 0
            && self.backend_resources.live_temporary_buffers == 0
            && self.backend_resources.live_cancellation_probes == 0
    }
}

fn recompute_shutdown(shutdown: &mut ShutdownReport) {
    shutdown.clean = shutdown.runtime_stopped && shutdown.clean_without_runtime();
}

fn apply_cleanup_failure(result: &mut SpikeResult, error: PlatformError) {
    result.outcome = "internal_spike_failure".to_owned();
    result.terminal_state = Some("platform_failed".to_owned());
    result.output = None;
    result.error = Some(platform_error_report(error));
}

fn dirty_shutdown_error(shutdown: &ShutdownReport) -> PlatformError {
    spike_error(
        PlatformErrorCode::Internal,
        "Phase 0 spike shutdown left activation-owned or bounded state live",
        "phase0-spike.dirty-shutdown",
        [
            ("active_leases", shutdown.active_leases.to_string()),
            ("queued_waiters", shutdown.queued_waiters.to_string()),
            (
                "cancellation_registrations",
                shutdown.cancellation_registrations.to_string(),
            ),
            (
                "running_invocations",
                shutdown.running_invocations.to_string(),
            ),
            (
                "retained_log_entries",
                shutdown.retained_log_entries.to_string(),
            ),
            (
                "prepared_cache_entries",
                shutdown.prepared_cache_entries.to_string(),
            ),
        ],
    )
}

fn cleanup_error(operation: &str, cause: PlatformError) -> PlatformError {
    spike_error(
        PlatformErrorCode::Internal,
        format!("{operation} failed during Phase 0 spike shutdown"),
        "phase0-spike.cleanup-failed",
        [
            ("operation", operation.to_owned()),
            (
                "cause_code",
                platform_error_code_name(cause.code).to_owned(),
            ),
            ("cause_message", cause.message),
        ],
    )
}

fn empty_cache_snapshot(config: &ValidatedConfig) -> PreparedCacheSnapshot {
    PreparedCacheSnapshot {
        entries: 0,
        source_bytes: 0,
        maximum_entries: config.prepared_cache_entries,
        maximum_source_bytes: config.prepared_cache_bytes,
    }
}

fn configuration_error<I, K>(message: impl Into<String>, fields: I) -> PlatformError
where
    I: IntoIterator<Item = (K, String)>,
    K: Into<String>,
{
    spike_error(
        PlatformErrorCode::InvalidArgument,
        message,
        "phase0-spike.invalid-configuration",
        fields,
    )
}

fn input_error<I, K>(
    message: impl Into<String>,
    kind: impl Into<String>,
    fields: I,
) -> PlatformError
where
    I: IntoIterator<Item = (K, String)>,
    K: Into<String>,
{
    spike_error(PlatformErrorCode::CorruptArtifact, message, kind, fields)
}

fn spike_error<I, K>(
    code: PlatformErrorCode,
    message: impl Into<String>,
    kind: impl Into<String>,
    fields: I,
) -> PlatformError
where
    I: IntoIterator<Item = (K, String)>,
    K: Into<String>,
{
    let fields = fields
        .into_iter()
        .map(|(name, value)| (bounded_text(&name.into(), 64), bounded_text(&value, 256)))
        .collect();
    PlatformError {
        code,
        message: bounded_text(&message.into(), MAX_DIAGNOSTIC_BYTES),
        retryable: false,
        details: vec![ErrorDetail {
            kind: bounded_text(&kind.into(), 128),
            fields,
        }],
    }
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

fn now_unix_millis() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| u64::try_from(duration.as_millis()).unwrap_or(u64::MAX))
        .unwrap_or(0)
}

fn platform_error_code_name(code: PlatformErrorCode) -> &'static str {
    match code {
        PlatformErrorCode::Unavailable => "unavailable",
        PlatformErrorCode::DeadlineExceeded => "deadline_exceeded",
        PlatformErrorCode::Cancelled => "cancelled",
        PlatformErrorCode::ResourceExhausted => "resource_exhausted",
        PlatformErrorCode::PermissionDenied => "permission_denied",
        PlatformErrorCode::Unauthenticated => "unauthenticated",
        PlatformErrorCode::InvalidArgument => "invalid_argument",
        PlatformErrorCode::NotFound => "not_found",
        PlatformErrorCode::AlreadyExists => "already_exists",
        PlatformErrorCode::IncompatibleContract => "incompatible_contract",
        PlatformErrorCode::StateConflict => "state_conflict",
        PlatformErrorCode::DependencyFailed => "dependency_failed",
        PlatformErrorCode::GuestTrap => "guest_trap",
        PlatformErrorCode::CorruptArtifact => "corrupt_artifact",
        PlatformErrorCode::RouteUnavailable => "route_unavailable",
        PlatformErrorCode::AdmissionRejected => "admission_rejected",
        PlatformErrorCode::Internal => "internal",
        _ => "unknown",
    }
}

fn terminal_state_name(state: ActivationTerminalState) -> &'static str {
    match state {
        ActivationTerminalState::Completed => "completed",
        ActivationTerminalState::Rejected => "rejected",
        ActivationTerminalState::Cancelled => "cancelled",
        ActivationTerminalState::DeadlineExceeded => "deadline_exceeded",
        ActivationTerminalState::ResourceExhausted => "resource_exhausted",
        ActivationTerminalState::GuestTrap => "guest_trap",
        ActivationTerminalState::StateConflict => "state_conflict",
        ActivationTerminalState::DependencyFailed => "dependency_failed",
        ActivationTerminalState::PlatformFailed => "platform_failed",
        _ => "unknown",
    }
}

fn cell_class_name(class: CellClass) -> &'static str {
    match class {
        CellClass::Tiny => "tiny",
        CellClass::Small => "small",
        CellClass::Standard => "standard",
        CellClass::Large => "large",
        CellClass::ExtraLarge => "extra_large",
    }
}

fn bounded_text(value: &str, maximum_bytes: usize) -> String {
    if value.len() <= maximum_bytes {
        return value.to_owned();
    }
    let end = value
        .char_indices()
        .map(|(index, _)| index)
        .take_while(|index| *index <= maximum_bytes)
        .last()
        .unwrap_or(0);
    value[..end].to_owned()
}

fn panic_message(payload: &Box<dyn std::any::Any + Send>) -> String {
    if let Some(message) = payload.downcast_ref::<&str>() {
        bounded_text(message, MAX_DIAGNOSTIC_BYTES)
    } else if let Some(message) = payload.downcast_ref::<String>() {
        bounded_text(message, MAX_DIAGNOSTIC_BYTES)
    } else {
        "non-string panic payload".to_owned()
    }
}
