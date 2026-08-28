//! Explicit composition root for the non-production Phase 0 activation spike.
//!
//! `latentd phase0-spike invoke-once` is intentionally finite. Its
//! `verify-recovery` sibling retains the same composition for a controlled
//! trap followed by a successful echo. Both wire the fixed cell pool, Wasmtime
//! containment backend, activation runner, bounded preparation cache, bounded
//! logs, deadlines, and cancellation into one local executable path. They are
//! not Phase 1 management or invocation APIs.

#![forbid(unsafe_code)]

#[cfg(target_os = "linux")]
use std::fs;
use std::io::{self, Write as _};
use std::path::PathBuf;
use std::process::ExitCode;
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use clap::{error::ErrorKind, Args, Parser, Subcommand};
use latent_activation::{ActivationManager, ActivationOutcome};
use latent_core::{
    ActivationId, ActivationTerminalState, BudgetConsumption, CancelDisposition, ErrorDetail,
    Metadata, NodeId, PlatformError, PlatformErrorCode,
};
use latent_executor::{ExecutionBackend, PreparedComponent};
use latent_manifest::CapsuleManifest;
use latent_node::{ActivationRunnerSnapshot, Phase0ActivationRunner};
use latent_scheduler::{CellClass, CellPool, CellPoolSnapshot, FixedCellPool};
use latent_wasmtime::{
    CapturedLog, Phase0InstanceAllocator, Phase0WasmtimeBackend, PreparedCacheSnapshot,
    RuntimeResourceSnapshot,
};
use serde::Serialize;

use crate::phase0_composition::{
    self, Phase0InvocationConfig, Phase0LoadedArtifact, Phase0PreparationConfig,
    Phase0RuntimeConfig, Phase0RuntimeWorkerMonitor,
};

pub const EXIT_SUCCESS: u8 = 0;
pub const EXIT_DOMAIN_ERROR: u8 = 10;
pub const EXIT_TIMEOUT_OR_CANCELLED: u8 = 11;
pub const EXIT_GUEST_TRAP: u8 = 12;
pub const EXIT_INVALID_COMPONENT_OR_CONFIGURATION: u8 = 13;
pub const EXIT_INTERNAL_SPIKE_FAILURE: u8 = 14;

const RESULT_SCHEMA_VERSION: &str = "latent.phase0.spike.result.v1";
const INVOKE_ONCE_SURFACE_NAME: &str = "latentd.phase0-spike.invoke-once";
const VERIFY_RECOVERY_SURFACE_NAME: &str = "latentd.phase0-spike.verify-recovery";
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

    #[command(
        name = "verify-recovery",
        about = "Run a controlled trap and a successful echo through one retained Phase 0 composition"
    )]
    VerifyRecovery(VerifyRecoveryArgs),
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

#[derive(Debug, Args)]
struct VerifyRecoveryArgs {
    #[command(flatten)]
    invocation: InvokeOnceArgs,
}

#[derive(Debug, Clone)]
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
    surface: &'static str,
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
            surface: INVOKE_ONCE_SURFACE_NAME,
        })
    }
}

#[derive(Debug)]
struct ValidatedRecoveryConfig {
    invocation: ValidatedConfig,
    trap_activation_id: ActivationId,
    recovery_activation_id: ActivationId,
}

impl TryFrom<VerifyRecoveryArgs> for ValidatedRecoveryConfig {
    type Error = PlatformError;

    fn try_from(arguments: VerifyRecoveryArgs) -> Result<Self, Self::Error> {
        let mut invocation = ValidatedConfig::try_from(arguments.invocation)?;
        invocation.surface = VERIFY_RECOVERY_SURFACE_NAME;
        if invocation.pool_capacity != 1 {
            return Err(configuration_error(
                "verify-recovery requires --pool-capacity 1 to prove cell reuse",
                [("pool_capacity", invocation.pool_capacity.to_string())],
            ));
        }
        if invocation.cancel_after_ms.is_some() {
            return Err(configuration_error(
                "verify-recovery owns its controlled trap and does not accept --cancel-after-ms",
                std::iter::empty::<(&str, String)>(),
            ));
        }
        if invocation.input.is_empty() {
            return Err(configuration_error(
                "verify-recovery requires a non-empty successful echo input",
                std::iter::empty::<(&str, String)>(),
            ));
        }

        let trap_activation_id = recovery_activation_id(&invocation.activation_id, "trap")?;
        let recovery_activation_id = recovery_activation_id(&invocation.activation_id, "recovery")?;
        Ok(Self {
            invocation,
            trap_activation_id,
            recovery_activation_id,
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
    recovery: Option<RecoveryReport>,
    shutdown: ShutdownReport,
}

#[derive(Debug, Clone, Serialize)]
struct OutputReport {
    media_type: String,
    utf8: String,
    bytes: usize,
}

#[derive(Debug, Clone, Serialize)]
struct ErrorReport {
    kind: String,
    code: String,
    message: String,
    retryable: bool,
    details: Vec<ErrorDetailReport>,
}

#[derive(Debug, Clone, Serialize)]
struct ErrorDetailReport {
    kind: String,
    fields: Metadata,
}

#[derive(Debug, Clone, Default, Serialize)]
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

#[derive(Debug, Clone, Serialize)]
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

#[derive(Debug, Clone, Serialize)]
struct LogReport {
    activation_id: String,
    level: String,
    message: String,
    fields: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
struct TopologyFingerprintReport {
    /// Worker threads observed through Tokio's lifecycle hooks, not the CLI value.
    runtime_workers: usize,
    /// Fixed pool capacity observed from the concrete fixed pool.
    pool_capacity: u32,
    /// Process-owned socket descriptors observed by the platform topology probe.
    listener_socket_count: u32,
}

#[derive(Debug, Clone, Serialize)]
struct TopologyReport {
    initialized: bool,
    /// Kept for the v1 convenience view; its raw source is `before_component_load`.
    runtime_workers: usize,
    wasmtime_epoch_ticker_threads: u32,
    pool_capacity: u32,
    pool_queue_capacity: u32,
    listener_socket_count: u32,
    /// Raw process/runtime/pool observation captured before any capsule or component is loaded.
    before_component_load: Option<TopologyFingerprintReport>,
    /// Raw observations captured after each completed activation in this process.
    after_activations: Vec<TopologyFingerprintReport>,
    unchanged: bool,
}

#[derive(Debug, Clone, Serialize)]
struct ActivationReport {
    activation_id: String,
    outcome: String,
    terminal_state: Option<String>,
    output: Option<OutputReport>,
    error: Option<ErrorReport>,
    elapsed_time_micros: u64,
    consumption: ConsumptionReport,
    cell: CellReport,
    logs: Vec<LogReport>,
}

#[derive(Debug, Clone, Serialize)]
struct RunnerSnapshotReport {
    active_cancellation_registrations: u64,
    running_invocations: u64,
    total_invocations: u64,
    released_cells: u64,
    quarantined_cells: u64,
    disposition_failures: u64,
}

#[derive(Debug, Serialize)]
struct RecoveryActivationReport {
    phase: String,
    activation: ActivationReport,
    /// Cumulative runner counters demonstrate that one runner served both calls.
    runner: RunnerSnapshotReport,
    /// Cache observations demonstrate that the prepared component remains retained between calls.
    prepared_cache: CacheSnapshotReport,
    backend_resources: RuntimeResourceReport,
    retained_log_entries: usize,
}

#[derive(Debug, Serialize)]
struct RecoveryReport {
    expected_failure: String,
    activation_count: u32,
    activations: Vec<RecoveryActivationReport>,
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

type RuntimeTopologyMonitor = Phase0RuntimeWorkerMonitor;

struct CompletedInvocation {
    activation: ActivationReport,
    exit_code: u8,
    pool_after: CellPoolSnapshot,
    runner_snapshot: ActivationRunnerSnapshot,
    resources: RuntimeResourceSnapshot,
    retained_log_entries: usize,
    cache: PreparedCacheSnapshot,
}

struct PreparedComposition {
    loaded: Phase0LoadedArtifact,
    backend: Arc<Phase0WasmtimeBackend>,
    prepared: PreparedComponent,
    cache_after_prepare: PreparedCacheSnapshot,
    runner: Arc<Phase0ActivationRunner>,
}

struct PreparationFailure {
    component_bytes: u64,
    cache_after_prepare: PreparedCacheSnapshot,
    cache_after_release: PreparedCacheSnapshot,
    resources: RuntimeResourceSnapshot,
    error: PlatformError,
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
        Command::Phase0Spike(Phase0SpikeArgs {
            command: Phase0Command::VerifyRecovery(arguments),
        }) => match ValidatedRecoveryConfig::try_from(arguments) {
            Ok(config) => EntryOutcome::Report(run_recovery_validated(config)),
            Err(error) => {
                eprintln!(
                    "configuration rejected before runtime initialization: {}",
                    error.message
                );
                EntryOutcome::Report(platform_uninitialized_report_for_surface(
                    DEFAULT_ACTIVATION_ID,
                    error,
                    EXIT_INVALID_COMPONENT_OR_CONFIGURATION,
                    "invalid_component_or_configuration",
                    VERIFY_RECOVERY_SURFACE_NAME,
                ))
            }
        },
    }
}

fn run_validated(config: ValidatedConfig) -> ProcessReport {
    let composition = match construct_runtime_composition(&config) {
        Ok(composition) => composition,
        Err(report) => return *report,
    };
    let RuntimeComposition {
        runtime,
        pool,
        topology,
        monitor,
    } = composition;
    let mut report = runtime.block_on(execute_once(&config, pool, topology, monitor));
    drop(runtime);
    record_runtime_shutdown(&mut report);
    report
}

fn run_recovery_validated(config: ValidatedRecoveryConfig) -> ProcessReport {
    let composition = match construct_runtime_composition(&config.invocation) {
        Ok(composition) => composition,
        Err(report) => return *report,
    };
    let RuntimeComposition {
        runtime,
        pool,
        topology,
        monitor,
    } = composition;
    let mut report = runtime.block_on(execute_recovery(&config, pool, topology, monitor));
    drop(runtime);
    record_runtime_shutdown(&mut report);
    report
}

struct RuntimeComposition {
    runtime: tokio::runtime::Runtime,
    pool: Arc<FixedCellPool>,
    topology: TopologyReport,
    monitor: RuntimeTopologyMonitor,
}

fn construct_runtime_composition(
    config: &ValidatedConfig,
) -> Result<RuntimeComposition, Box<ProcessReport>> {
    let shared = match phase0_composition::construct_runtime_composition(&Phase0RuntimeConfig {
        node_id: NodeId(SPIKE_NODE_ID.to_owned()),
        pool_capacity: config.pool_capacity,
        pool_queue_capacity: config.pool_queue_capacity,
        runtime_workers: config.runtime_workers,
    }) {
        Ok(composition) => composition,
        Err(error) => {
            return Err(Box::new(platform_uninitialized_report(
                &config.activation_id.0,
                error,
                EXIT_INTERNAL_SPIKE_FAILURE,
                "internal_spike_failure",
            )));
        }
    };
    let crate::phase0_composition::Phase0RuntimeComposition {
        runtime,
        pool,
        workers: monitor,
    } = shared;

    let baseline = match runtime.block_on(wait_for_runtime_topology(
        &monitor,
        &pool,
        config.runtime_workers,
    )) {
        Ok(baseline) => baseline,
        Err(error) => {
            let pool_snapshot = pool.observations();
            let mut report = preflight_failure(
                config,
                configured_topology(config),
                pool_snapshot,
                pool_snapshot,
                0,
                error,
            );
            drop(runtime);
            record_runtime_shutdown(&mut report);
            return Err(Box::new(report));
        }
    };

    Ok(RuntimeComposition {
        runtime,
        pool,
        topology: topology_from_baseline(baseline, config.pool_queue_capacity),
        monitor,
    })
}

fn record_runtime_shutdown(report: &mut ProcessReport) {
    report.result.shutdown.runtime_stopped = true;
    recompute_shutdown(&mut report.result.shutdown);
}

async fn prepare_composition(
    config: &ValidatedConfig,
    pool: &Arc<FixedCellPool>,
) -> Result<PreparedComposition, PreparationFailure> {
    let prepared_backend =
        match phase0_composition::prepare_phase0_backend(&Phase0PreparationConfig {
            capsule: config.capsule.clone(),
            component: config.component.clone(),
            component_maximum_bytes: config.component_max_bytes,
            prepared_cache_maximum_entries: config.prepared_cache_entries,
            prepared_cache_maximum_bytes: config.prepared_cache_bytes,
            prepared_cache_enabled: true,
            invocation_log_maximum_entries: config.log_max_entries,
            invocation_log_maximum_bytes: config.log_max_bytes,
            retained_log_maximum_entries: config.log_max_entries,
            retained_log_maximum_bytes: config.log_max_bytes,
            requested_memory_bytes: config.memory_bytes,
            requested_fuel: config.fuel,
            wasmtime_instance_allocator: Phase0InstanceAllocator::OnDemand,
            wasmtime_copy_on_write_images: true,
            wasmtime_pooling_maximum_instances: config.pool_capacity,
        })
        .await
        {
            Ok(prepared) => prepared,
            Err(error) => return Err(empty_preparation_failure(config, 0, error)),
        };
    let crate::phase0_composition::Phase0PreparedBackend {
        loaded,
        backend,
        prepared,
        cache_after_prepare,
        ..
    } = prepared_backend;

    let backend_for_runner: Arc<dyn ExecutionBackend> = backend.clone();
    let pool_for_runner: Arc<dyn CellPool> = pool.clone();
    let runner = match phase0_composition::create_phase0_activation_runner(
        pool_for_runner,
        backend_for_runner,
        prepared.clone(),
    ) {
        Ok(runner) => runner,
        Err(error) => {
            let release_error = backend.release(prepared).await.err();
            let error = release_error.map_or(error, |release_error| {
                cleanup_error("prepared-component release", release_error)
            });
            return Err(PreparationFailure {
                component_bytes: loaded.component_bytes,
                cache_after_prepare,
                cache_after_release: backend.cache_snapshot(),
                resources: backend.resource_snapshot(),
                error,
            });
        }
    };

    Ok(PreparedComposition {
        loaded,
        backend,
        prepared,
        cache_after_prepare,
        runner,
    })
}

fn empty_preparation_failure(
    config: &ValidatedConfig,
    component_bytes: u64,
    error: PlatformError,
) -> PreparationFailure {
    PreparationFailure {
        component_bytes,
        cache_after_prepare: empty_cache_snapshot(config),
        cache_after_release: empty_cache_snapshot(config),
        resources: RuntimeResourceSnapshot::default(),
        error,
    }
}

fn preparation_failure_report(
    config: &ValidatedConfig,
    topology: TopologyReport,
    pool_before: CellPoolSnapshot,
    pool: &FixedCellPool,
    failure: PreparationFailure,
) -> ProcessReport {
    preflight_failure_with_preparation(
        config,
        topology,
        pool_before,
        pool.observations(),
        failure.component_bytes,
        failure.cache_after_prepare,
        failure.cache_after_release,
        failure.resources,
        failure.error,
    )
}

async fn execute_once(
    config: &ValidatedConfig,
    pool: Arc<FixedCellPool>,
    mut topology: TopologyReport,
    monitor: RuntimeTopologyMonitor,
) -> ProcessReport {
    let pool_before = pool.observations();
    let PreparedComposition {
        loaded,
        backend,
        prepared,
        cache_after_prepare,
        runner,
    } = match prepare_composition(config, &pool).await {
        Ok(composition) => composition,
        Err(failure) => {
            return preparation_failure_report(config, topology, pool_before, &pool, failure);
        }
    };

    let completed = match invoke_prepared(
        config,
        &loaded.artifact.manifest,
        &pool,
        &backend,
        &runner,
        &mut topology,
        &monitor,
    )
    .await
    {
        Ok(completed) => completed,
        Err(error) => {
            let release_error = backend.release(prepared).await.err();
            let error = release_error.map_or(error, |release_error| {
                cleanup_error("prepared-component release", release_error)
            });
            return preflight_failure_with_preparation(
                config,
                topology,
                pool_before,
                pool.observations(),
                loaded.component_bytes,
                cache_after_prepare,
                backend.cache_snapshot(),
                backend.resource_snapshot(),
                error,
            );
        }
    };
    let mut result = spike_result_from_activation(
        config.surface,
        &completed.activation,
        topology,
        PreparationReport {
            component_bytes: loaded.component_bytes,
            cache_after_prepare: cache_report(&cache_after_prepare),
            cache_after_release: CacheSnapshotReport::default(),
        },
        shutdown_from_completed(&completed),
        None,
    );
    let mut exit_code = completed.exit_code;

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
    if !result.topology.unchanged {
        let error = topology_changed_error(&result.topology);
        apply_cleanup_failure(&mut result, error);
        exit_code = EXIT_INTERNAL_SPIKE_FAILURE;
    }

    ProcessReport { result, exit_code }
}

async fn execute_recovery(
    recovery: &ValidatedRecoveryConfig,
    pool: Arc<FixedCellPool>,
    mut topology: TopologyReport,
    monitor: RuntimeTopologyMonitor,
) -> ProcessReport {
    let config = &recovery.invocation;
    let pool_before = pool.observations();
    let PreparedComposition {
        loaded,
        backend,
        prepared,
        cache_after_prepare,
        runner,
    } = match prepare_composition(config, &pool).await {
        Ok(composition) => composition,
        Err(failure) => {
            return preparation_failure_report(config, topology, pool_before, &pool, failure);
        }
    };

    let trap_config = recovery_invocation_config(
        config,
        recovery.trap_activation_id.clone(),
        "__latent_test_trap",
    );
    let trapped = match invoke_prepared(
        &trap_config,
        &loaded.artifact.manifest,
        &pool,
        &backend,
        &runner,
        &mut topology,
        &monitor,
    )
    .await
    {
        Ok(completed) => completed,
        Err(error) => {
            let release_error = backend.release(prepared).await.err();
            let error = release_error.map_or(error, |release_error| {
                cleanup_error("prepared-component release", release_error)
            });
            return preflight_failure_with_preparation(
                config,
                topology,
                pool_before,
                pool.observations(),
                loaded.component_bytes,
                cache_after_prepare,
                backend.cache_snapshot(),
                backend.resource_snapshot(),
                error,
            );
        }
    };
    // This check intentionally happens before the healthy call. With one cell,
    // it establishes that the trap released all activation-owned capacity and
    // resources before the retained runner is asked to recover.
    let trap_verification_error = verify_trap_recovery_step(&trapped, &topology);

    let healthy_config = recovery_invocation_config(
        config,
        recovery.recovery_activation_id.clone(),
        &config.input,
    );
    let healthy = match invoke_prepared(
        &healthy_config,
        &loaded.artifact.manifest,
        &pool,
        &backend,
        &runner,
        &mut topology,
        &monitor,
    )
    .await
    {
        Ok(completed) => completed,
        Err(error) => {
            let mut result = spike_result_from_activation(
                config.surface,
                &trapped.activation,
                topology,
                PreparationReport {
                    component_bytes: loaded.component_bytes,
                    cache_after_prepare: cache_report(&cache_after_prepare),
                    cache_after_release: CacheSnapshotReport::default(),
                },
                shutdown_from_completed(&trapped),
                Some(RecoveryReport {
                    expected_failure: "trap".to_owned(),
                    activation_count: 1,
                    activations: vec![recovery_activation_report("trap", &trapped)],
                }),
            );
            let exit_code = EXIT_INTERNAL_SPIKE_FAILURE;
            if let Err(release_error) = backend.release(prepared).await {
                apply_cleanup_failure(
                    &mut result,
                    cleanup_error("prepared-component release", release_error),
                );
            } else {
                apply_cleanup_failure(&mut result, error);
            }
            result.preparation.cache_after_release = cache_report(&backend.cache_snapshot());
            result.shutdown.prepared_cache_entries = backend.cache_snapshot().entries;
            recompute_shutdown(&mut result.shutdown);
            if !result.shutdown.clean_without_runtime() {
                let shutdown_error = dirty_shutdown_error(&result.shutdown);
                apply_cleanup_failure(&mut result, shutdown_error);
            }
            return ProcessReport { result, exit_code };
        }
    };

    let recovery_report = RecoveryReport {
        expected_failure: "trap".to_owned(),
        activation_count: 2,
        activations: vec![
            recovery_activation_report("trap", &trapped),
            recovery_activation_report("recovery", &healthy),
        ],
    };
    let verification_error = trap_verification_error
        .or_else(|| verify_recovery_completion(&healthy, &topology, &config.input));
    let mut result = spike_result_from_activation(
        config.surface,
        &healthy.activation,
        topology,
        PreparationReport {
            component_bytes: loaded.component_bytes,
            cache_after_prepare: cache_report(&cache_after_prepare),
            cache_after_release: CacheSnapshotReport::default(),
        },
        shutdown_from_completed(&healthy),
        Some(recovery_report),
    );
    let mut exit_code = EXIT_SUCCESS;

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
        let shutdown_error = dirty_shutdown_error(&result.shutdown);
        apply_cleanup_failure(&mut result, shutdown_error);
        exit_code = EXIT_INTERNAL_SPIKE_FAILURE;
    }
    if let Some(error) = verification_error {
        apply_cleanup_failure(&mut result, error);
        exit_code = EXIT_INTERNAL_SPIKE_FAILURE;
    }

    ProcessReport { result, exit_code }
}

async fn invoke_prepared(
    config: &ValidatedConfig,
    manifest: &CapsuleManifest,
    pool: &Arc<FixedCellPool>,
    backend: &Arc<Phase0WasmtimeBackend>,
    runner: &Arc<Phase0ActivationRunner>,
    topology: &mut TopologyReport,
    monitor: &RuntimeTopologyMonitor,
) -> Result<CompletedInvocation, PlatformError> {
    let pool_before = pool.observations();
    let deadline = now_unix_millis()
        .checked_add(config.timeout_ms)
        .ok_or_else(|| {
            configuration_error(
                "invocation timeout overflows the Unix millisecond deadline",
                [("timeout_ms", config.timeout_ms.to_string())],
            )
        })?;
    let envelope = phase0_composition::phase0_activation_envelope(
        manifest,
        &Phase0InvocationConfig {
            activation_id: config.activation_id.clone(),
            input: &config.input,
            memory_bytes: config.memory_bytes,
            fuel: config.fuel,
            deadline_unix_millis: deadline,
            surface: config.surface,
            mode: spike_mode_name(config.surface),
            principal_subject: "phase0-spike-user",
            default_tenant: "phase0-spike",
            trace_id: SPIKE_TRACE_ID,
            span_id: SPIKE_SPAN_ID,
        },
    );

    let started = Instant::now();
    let invocation = runner.invoke(envelope);
    tokio::pin!(invocation);
    let outcome = if let Some(cancel_after_ms) = config.cancel_after_ms {
        tokio::select! {
            biased;
            outcome = &mut invocation => outcome,
            () = tokio::time::sleep(Duration::from_millis(cancel_after_ms)) => {
                match runner
                    .cancel(&config.activation_id, "phase0-spike explicit cancellation")
                    .await
                {
                    Ok(CancelDisposition::Accepted) => {}
                    Ok(CancelDisposition::AlreadyTerminal(_)) | Ok(CancelDisposition::NotFound) => {
                        eprintln!("explicit cancellation raced with completion");
                    }
                    Err(error) => {
                        eprintln!(
                            "explicit cancellation could not be sent: {}",
                            bounded_text(&error.message, MAX_DIAGNOSTIC_BYTES)
                        );
                    }
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
    record_topology_after_activation(topology, monitor, pool)?;
    let (activation, exit_code) = activation_report(
        config,
        pool_before,
        pool_after,
        runner_snapshot,
        logs,
        outcome,
        elapsed_time_micros,
    );

    Ok(CompletedInvocation {
        activation,
        exit_code,
        pool_after,
        runner_snapshot,
        resources,
        retained_log_entries,
        cache: backend.cache_snapshot(),
    })
}

fn activation_report(
    config: &ValidatedConfig,
    pool_before: CellPoolSnapshot,
    pool_after: CellPoolSnapshot,
    runner_snapshot: ActivationRunnerSnapshot,
    logs: Vec<CapturedLog>,
    outcome: ActivationOutcome,
    elapsed_time_micros: u64,
) -> (ActivationReport, u8) {
    let (outcome_name, terminal_state, output, error, consumption, exit_code) =
        classify_activation_outcome(outcome);
    (
        ActivationReport {
            activation_id: config.activation_id.0.clone(),
            outcome: outcome_name,
            terminal_state,
            output,
            error,
            elapsed_time_micros,
            consumption,
            cell: CellReport {
                disposition: cell_disposition(&runner_snapshot),
                pool_before: Some(pool_report(&pool_before)),
                pool_after: Some(pool_report(&pool_after)),
            },
            logs: logs.into_iter().map(log_report).collect(),
        },
        exit_code,
    )
}

fn shutdown_from_completed(completed: &CompletedInvocation) -> ShutdownReport {
    ShutdownReport {
        clean: false,
        runtime_stopped: false,
        active_leases: completed.pool_after.active_leases,
        queued_waiters: completed.pool_after.queue_depth,
        cancellation_registrations: completed.runner_snapshot.active_cancellation_registrations,
        running_invocations: completed.runner_snapshot.running_invocations,
        retained_log_entries: completed.retained_log_entries,
        prepared_cache_entries: completed.cache.entries,
        backend_resources: runtime_resource_report(&completed.resources),
    }
}

fn spike_result_from_activation(
    surface: &'static str,
    activation: &ActivationReport,
    topology: TopologyReport,
    preparation: PreparationReport,
    shutdown: ShutdownReport,
    recovery: Option<RecoveryReport>,
) -> SpikeResult {
    SpikeResult {
        schema_version: RESULT_SCHEMA_VERSION,
        surface,
        production_ready: false,
        phase1_api_compatible: false,
        activation_id: activation.activation_id.clone(),
        outcome: activation.outcome.clone(),
        terminal_state: activation.terminal_state.clone(),
        output: activation.output.clone(),
        error: activation.error.clone(),
        elapsed_time_micros: activation.elapsed_time_micros,
        consumption: activation.consumption.clone(),
        cell: activation.cell.clone(),
        logs: activation.logs.clone(),
        topology,
        preparation,
        recovery,
        shutdown,
    }
}

fn recovery_activation_id(base: &ActivationId, phase: &str) -> Result<ActivationId, PlatformError> {
    let value = format!("{}-{phase}", base.0);
    if value.len() > MAX_ACTIVATION_ID_BYTES {
        return Err(configuration_error(
            "activation ID is too long for the verify-recovery phase suffix",
            [
                ("activation_id_bytes", base.0.len().to_string()),
                ("phase", phase.to_owned()),
            ],
        ));
    }
    Ok(ActivationId(value))
}

fn recovery_invocation_config(
    base: &ValidatedConfig,
    activation_id: ActivationId,
    input: &str,
) -> ValidatedConfig {
    let mut config = base.clone();
    config.activation_id = activation_id;
    config.input = input.to_owned();
    config.cancel_after_ms = None;
    config
}

fn recovery_activation_report(
    phase: &str,
    completed: &CompletedInvocation,
) -> RecoveryActivationReport {
    RecoveryActivationReport {
        phase: phase.to_owned(),
        activation: completed.activation.clone(),
        runner: runner_snapshot_report(&completed.runner_snapshot),
        prepared_cache: cache_report(&completed.cache),
        backend_resources: runtime_resource_report(&completed.resources),
        retained_log_entries: completed.retained_log_entries,
    }
}

fn runner_snapshot_report(snapshot: &ActivationRunnerSnapshot) -> RunnerSnapshotReport {
    RunnerSnapshotReport {
        active_cancellation_registrations: snapshot.active_cancellation_registrations,
        running_invocations: snapshot.running_invocations,
        total_invocations: snapshot.total_invocations,
        released_cells: snapshot.released_cells,
        quarantined_cells: snapshot.quarantined_cells,
        disposition_failures: snapshot.disposition_failures,
    }
}

fn verify_trap_recovery_step(
    trapped: &CompletedInvocation,
    topology: &TopologyReport,
) -> Option<PlatformError> {
    if trapped.activation.outcome != "trap"
        || trapped
            .activation
            .error
            .as_ref()
            .map(|error| error.code.as_str())
            != Some("guest_trap")
    {
        return Some(recovery_verification_error(
            "controlled recovery failure did not produce the expected guest trap",
            [
                ("actual_outcome", trapped.activation.outcome.clone()),
                (
                    "actual_error_code",
                    trapped
                        .activation
                        .error
                        .as_ref()
                        .map(|error| error.code.clone())
                        .unwrap_or_else(|| "none".to_owned()),
                ),
            ],
        ));
    }
    if let Some(error) = verify_recovery_step("trap", trapped) {
        return Some(error);
    }
    if trapped.runner_snapshot.total_invocations != 1 || trapped.cache.entries != 1 {
        return Some(recovery_verification_error(
            "controlled trap did not retain exactly one prepared runner composition",
            [
                (
                    "runner_total_invocations",
                    trapped.runner_snapshot.total_invocations.to_string(),
                ),
                ("prepared_cache_entries", trapped.cache.entries.to_string()),
            ],
        ));
    }
    let Some(before) = topology.before_component_load.as_ref() else {
        return Some(recovery_verification_error(
            "recovery composition has no pre-component topology observation",
            std::iter::empty::<(&str, String)>(),
        ));
    };
    if topology.after_activations.len() != 1 || topology.after_activations[0] != *before {
        return Some(recovery_verification_error(
            "runtime, pool, or socket topology changed after the controlled trap",
            [(
                "after_activation_count",
                topology.after_activations.len().to_string(),
            )],
        ));
    }
    None
}

fn verify_recovery_completion(
    healthy: &CompletedInvocation,
    topology: &TopologyReport,
    expected_output: &str,
) -> Option<PlatformError> {
    let recovered_output = healthy
        .activation
        .output
        .as_ref()
        .map(|output| output.utf8.as_str());
    if healthy.activation.outcome != "success" || recovered_output != Some(expected_output) {
        return Some(recovery_verification_error(
            "same-composition recovery invocation did not echo the requested input",
            [
                ("actual_outcome", healthy.activation.outcome.clone()),
                (
                    "actual_output",
                    recovered_output.unwrap_or("<no-output>").to_owned(),
                ),
            ],
        ));
    }
    if let Some(error) = verify_recovery_step("recovery", healthy) {
        return Some(error);
    }
    if healthy.runner_snapshot.total_invocations != 2 || healthy.cache.entries != 1 {
        return Some(recovery_verification_error(
            "recovery did not reuse the original runner and prepared component",
            [
                (
                    "runner_total_invocations",
                    healthy.runner_snapshot.total_invocations.to_string(),
                ),
                ("prepared_cache_entries", healthy.cache.entries.to_string()),
            ],
        ));
    }

    let Some(before) = topology.before_component_load.as_ref() else {
        return Some(recovery_verification_error(
            "recovery composition has no pre-component topology observation",
            std::iter::empty::<(&str, String)>(),
        ));
    };
    if topology.after_activations.len() != 2
        || topology
            .after_activations
            .iter()
            .any(|after| after != before)
    {
        return Some(recovery_verification_error(
            "runtime, pool, or socket topology changed during recovery verification",
            [(
                "after_activation_count",
                topology.after_activations.len().to_string(),
            )],
        ));
    }
    None
}

fn verify_recovery_step(phase: &str, completed: &CompletedInvocation) -> Option<PlatformError> {
    let pool = &completed.pool_after;
    let runner = completed.runner_snapshot;
    let resources = &completed.resources;
    let reusable_pool = pool.capacity == 1
        && pool.available == 1
        && pool.active_leases == 0
        && pool.queue_depth == 0
        && pool.quarantined == 0;
    let fully_reclaimed = runner.active_cancellation_registrations == 0
        && runner.running_invocations == 0
        && completed.retained_log_entries == 0
        && resources.active_invocations == 0
        && resources.live_stores == 0
        && resources.live_host_states == 0
        && resources.live_component_instances == 0
        && resources.live_temporary_buffers == 0
        && resources.live_cancellation_probes == 0;
    if completed.activation.cell.disposition != "released" || !reusable_pool || !fully_reclaimed {
        return Some(recovery_verification_error(
            "recovery phase did not release its capacity-one cell and contained resources",
            [
                ("phase", phase.to_owned()),
                (
                    "cell_disposition",
                    completed.activation.cell.disposition.clone(),
                ),
                ("pool_available", pool.available.to_string()),
                ("pool_active_leases", pool.active_leases.to_string()),
                ("pool_quarantined", pool.quarantined.to_string()),
                (
                    "cancellation_registrations",
                    runner.active_cancellation_registrations.to_string(),
                ),
                (
                    "running_invocations",
                    runner.running_invocations.to_string(),
                ),
                (
                    "retained_log_entries",
                    completed.retained_log_entries.to_string(),
                ),
            ],
        ));
    }
    None
}

fn recovery_verification_error<I, K>(message: impl Into<String>, fields: I) -> PlatformError
where
    I: IntoIterator<Item = (K, String)>,
    K: Into<String>,
{
    spike_error(
        PlatformErrorCode::Internal,
        message,
        "phase0-spike.recovery-verification-failed",
        fields,
    )
}

fn configured_topology(config: &ValidatedConfig) -> TopologyReport {
    TopologyReport {
        initialized: false,
        runtime_workers: config.runtime_workers,
        wasmtime_epoch_ticker_threads: 1,
        pool_capacity: config.pool_capacity,
        pool_queue_capacity: config.pool_queue_capacity,
        listener_socket_count: 0,
        before_component_load: None,
        after_activations: Vec::new(),
        unchanged: false,
    }
}

fn topology_from_baseline(
    baseline: TopologyFingerprintReport,
    pool_queue_capacity: u32,
) -> TopologyReport {
    TopologyReport {
        initialized: true,
        runtime_workers: baseline.runtime_workers,
        wasmtime_epoch_ticker_threads: 1,
        pool_capacity: baseline.pool_capacity,
        pool_queue_capacity,
        listener_socket_count: baseline.listener_socket_count,
        before_component_load: Some(baseline),
        after_activations: Vec::new(),
        unchanged: true,
    }
}

async fn wait_for_runtime_topology(
    monitor: &RuntimeTopologyMonitor,
    pool: &FixedCellPool,
    expected_workers: usize,
) -> Result<TopologyFingerprintReport, PlatformError> {
    phase0_composition::wait_for_runtime_workers(monitor, expected_workers).await?;
    observe_topology(monitor, pool)
}

fn record_topology_after_activation(
    topology: &mut TopologyReport,
    monitor: &RuntimeTopologyMonitor,
    pool: &FixedCellPool,
) -> Result<(), PlatformError> {
    let observation = observe_topology(monitor, pool)?;
    topology.after_activations.push(observation);
    recompute_topology_unchanged(topology);
    Ok(())
}

fn observe_topology(
    monitor: &RuntimeTopologyMonitor,
    pool: &FixedCellPool,
) -> Result<TopologyFingerprintReport, PlatformError> {
    let runtime_workers = monitor.active_workers();
    let pool_snapshot = pool.observations();
    Ok(TopologyFingerprintReport {
        runtime_workers,
        pool_capacity: pool_snapshot.capacity,
        listener_socket_count: observed_process_socket_count()?,
    })
}

fn recompute_topology_unchanged(topology: &mut TopologyReport) {
    let direct_view = TopologyFingerprintReport {
        runtime_workers: topology.runtime_workers,
        pool_capacity: topology.pool_capacity,
        listener_socket_count: topology.listener_socket_count,
    };
    topology.unchanged = match topology.before_component_load.as_ref() {
        Some(before) => {
            before == &direct_view
                && topology
                    .after_activations
                    .iter()
                    .all(|after| after == before)
        }
        None => false,
    };
}

#[cfg(target_os = "linux")]
fn observed_process_socket_count() -> Result<u32, PlatformError> {
    let descriptors = fs::read_dir("/proc/self/fd").map_err(|error| {
        spike_error(
            PlatformErrorCode::Internal,
            format!("failed to inspect /proc/self/fd for process socket topology: {error}"),
            "phase0-spike.socket-observation-failed",
            std::iter::empty::<(&str, String)>(),
        )
    })?;
    let mut socket_count = 0_usize;
    for descriptor in descriptors.flatten() {
        let Ok(target) = fs::read_link(descriptor.path()) else {
            continue;
        };
        if target.to_string_lossy().starts_with("socket:[") {
            socket_count = socket_count.saturating_add(1);
        }
    }
    u32::try_from(socket_count).map_err(|_| {
        spike_error(
            PlatformErrorCode::Internal,
            "process socket descriptor count cannot be represented",
            "phase0-spike.socket-observation-overflow",
            [("socket_count", socket_count.to_string())],
        )
    })
}

#[cfg(target_os = "windows")]
fn observed_process_socket_count() -> Result<u32, PlatformError> {
    let output = std::process::Command::new("netstat")
        .arg("-ano")
        .output()
        .map_err(|error| {
            spike_error(
                PlatformErrorCode::Internal,
                format!("failed to inspect Windows process socket topology: {error}"),
                "phase0-spike.socket-observation-failed",
                std::iter::empty::<(&str, String)>(),
            )
        })?;
    if !output.status.success() {
        return Err(spike_error(
            PlatformErrorCode::Internal,
            "Windows netstat did not complete while observing process socket topology",
            "phase0-spike.socket-observation-failed",
            [("status", output.status.to_string())],
        ));
    }
    let process_id = std::process::id().to_string();
    let socket_count = String::from_utf8_lossy(&output.stdout)
        .lines()
        .filter(|line| {
            let fields = line.split_whitespace().collect::<Vec<_>>();
            fields.len() >= 4 && fields.last() == Some(&process_id.as_str())
        })
        .count();
    u32::try_from(socket_count).map_err(|_| {
        spike_error(
            PlatformErrorCode::Internal,
            "process socket count cannot be represented",
            "phase0-spike.socket-observation-overflow",
            [("socket_count", socket_count.to_string())],
        )
    })
}

#[cfg(any(target_os = "macos", target_os = "freebsd"))]
fn observed_process_socket_count() -> Result<u32, PlatformError> {
    let process_id = std::process::id().to_string();
    let output = std::process::Command::new("lsof")
        .args(["-nP", "-a", "-p", process_id.as_str(), "-i"])
        .output()
        .map_err(|error| {
            spike_error(
                PlatformErrorCode::Internal,
                format!("failed to inspect process socket topology with lsof: {error}"),
                "phase0-spike.socket-observation-failed",
                std::iter::empty::<(&str, String)>(),
            )
        })?;
    if !output.status.success() {
        return Err(spike_error(
            PlatformErrorCode::Internal,
            "lsof did not complete while observing process socket topology",
            "phase0-spike.socket-observation-failed",
            [("status", output.status.to_string())],
        ));
    }
    let socket_count = String::from_utf8_lossy(&output.stdout)
        .lines()
        .skip(1)
        .filter(|line| !line.trim().is_empty())
        .count();
    u32::try_from(socket_count).map_err(|_| {
        spike_error(
            PlatformErrorCode::Internal,
            "process socket count cannot be represented",
            "phase0-spike.socket-observation-overflow",
            [("socket_count", socket_count.to_string())],
        )
    })
}

#[cfg(not(any(
    target_os = "linux",
    target_os = "windows",
    target_os = "macos",
    target_os = "freebsd"
)))]
fn observed_process_socket_count() -> Result<u32, PlatformError> {
    Err(spike_error(
        PlatformErrorCode::Internal,
        "this platform has no supported process socket topology probe",
        "phase0-spike.socket-observation-unsupported",
        std::iter::empty::<(&str, String)>(),
    ))
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
        ActivationOutcome::Succeeded(success) => (
            "success".to_owned(),
            Some("completed".to_owned()),
            Some(output_report(success.output, success.output_media_type)),
            None,
            consumption_report(&success.consumption),
            EXIT_SUCCESS,
        ),
        ActivationOutcome::DeclaredError { error, consumption } => (
            "domain_error".to_owned(),
            Some("completed".to_owned()),
            Some(output_report(error.payload, error.media_type)),
            Some(ErrorReport {
                kind: "domain".to_owned(),
                code: error.code,
                message: error.message,
                retryable: false,
                details: Vec::new(),
            }),
            consumption_report(&consumption),
            EXIT_DOMAIN_ERROR,
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
    recompute_topology_unchanged(&mut topology);
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
            surface: config.surface,
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
            recovery: None,
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
    platform_uninitialized_report_for_surface(
        activation_id,
        error,
        exit_code,
        outcome,
        INVOKE_ONCE_SURFACE_NAME,
    )
}

fn platform_uninitialized_report_for_surface(
    activation_id: &str,
    error: PlatformError,
    exit_code: u8,
    outcome: &str,
    surface: &'static str,
) -> ProcessReport {
    ProcessReport {
        result: SpikeResult {
            schema_version: RESULT_SCHEMA_VERSION,
            surface,
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
                before_component_load: None,
                after_activations: Vec::new(),
                unchanged: false,
            },
            preparation: PreparationReport::default(),
            recovery: None,
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

fn spike_mode_name(surface: &str) -> &'static str {
    match surface {
        VERIFY_RECOVERY_SURFACE_NAME => "verify-recovery",
        _ => "invoke-once",
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

fn topology_changed_error(topology: &TopologyReport) -> PlatformError {
    spike_error(
        PlatformErrorCode::Internal,
        "Phase 0 spike observed a runtime, pool, or socket topology change",
        "phase0-spike.topology-changed",
        [
            (
                "after_activation_count",
                topology.after_activations.len().to_string(),
            ),
            (
                "baseline_runtime_workers",
                topology
                    .before_component_load
                    .as_ref()
                    .map(|baseline| baseline.runtime_workers.to_string())
                    .unwrap_or_else(|| "unobserved".to_owned()),
            ),
            (
                "observed_runtime_workers",
                topology
                    .after_activations
                    .last()
                    .map(|observation| observation.runtime_workers.to_string())
                    .unwrap_or_else(|| "unobserved".to_owned()),
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
