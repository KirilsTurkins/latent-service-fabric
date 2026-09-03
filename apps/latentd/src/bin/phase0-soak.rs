//! Native-Linux Phase 0 long-running resource-plateau probe.
//!
//! The probe deliberately uses the same public-within-package composition as
//! `latentd phase0-spike` and `phase0-baseline`.  It keeps a bounded raw
//! sample at every completed batch rather than retaining an object per
//! activation, so a 100,000-activation process remains inspectable.

#![forbid(unsafe_code)]
#![allow(
    clippy::cast_possible_truncation,
    clippy::cast_precision_loss,
    clippy::cast_sign_loss,
    clippy::format_collect,
    clippy::large_futures,
    clippy::map_unwrap_or,
    clippy::needless_pass_by_value,
    clippy::similar_names,
    clippy::struct_excessive_bools,
    clippy::too_many_arguments,
    clippy::too_many_lines,
    clippy::type_complexity
)]

use std::collections::{BTreeMap, BTreeSet};
use std::error::Error;
use std::fmt;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use clap::Parser;
use latent_activation::{ActivationManager, ActivationOutcome};
use latent_core::{
    ActivationId, BoxFuture, NodeId, PlatformError, PlatformErrorCode, ResourceBudget, TenantId,
};
use latent_executor::ExecutionBackend;
use latent_manifest::CapsuleManifest;
use latent_node::Phase0ActivationRunner;
use latent_scheduler::{CellClass, CellLease, CellPool, CellPoolSnapshot, FixedCellPool};
use latent_wasmtime::{
    Phase0InstanceAllocator, Phase0WasmtimeBackend, PreparedCacheSnapshot, RuntimeResourceSnapshot,
};
use latentd::phase0_composition::{
    self, Phase0InvocationConfig, Phase0PreparationConfig, Phase0RuntimeConfig,
    Phase0RuntimeWorkerMonitor,
};
use serde::Serialize;
use sha2::{Digest, Sha256};
use tokio::sync::Barrier;

const SCHEMA_VERSION: &str = "latent.phase0.resource-soak.run.v1";
const SURFACE: &str = "latentd.phase0-soak";
const NODE_ID: &str = "phase0-soak-node-0";
const TRACE_ID: &str = "phase0-soak-trace-00000001";
const SPAN_ID: &str = "phase0-soak-span-01";
const WASMTIME_WORKSPACE_PIN: &str = "47.0.3";
const COMPONENT_MAXIMUM_BYTES: usize = 64 * 1024 * 1024;
const PREPARED_CACHE_MAXIMUM_ENTRIES: usize = 1;
const PREPARED_CACHE_MAXIMUM_BYTES: usize = 64 * 1024 * 1024;
const LOG_MAXIMUM_ENTRIES: usize = 64;
const LOG_MAXIMUM_BYTES: usize = 64 * 1024;
const DEFAULT_FUEL: u64 = 1_000_000_000_000;
const DEFAULT_MEMORY_BYTES: u64 = 16 * 1024 * 1024;
const DEFAULT_MEMORY_PRESSURE_BYTES: u64 = 4 * 1024 * 1024;
const DEFAULT_TIMEOUT_MILLIS: u64 = 25;
const DEFAULT_CANCELLATION_MILLIS: u64 = 5;
const MINIMUM_WARMUP_ACTIVATIONS: u64 = 1_000;
const MINIMUM_MEASURED_ACTIVATIONS: u64 = 100_000;
const FINAL_PREPARED_CACHE_ENABLED: bool = true;
const FINAL_WASMTIME_COPY_ON_WRITE_IMAGES: bool = true;
const FIXTURE_TRAP: &str = "__latent_test_trap";
const FIXTURE_INFINITE: &str = "__latent_test_infinite";
const FIXTURE_MEMORY: &str = "__latent_test_memory";
const FIXTURE_DELAYED_ECHO_PREFIX: &str = "__latent_test_delayed_echo:";

#[derive(Debug, Parser)]
#[command(
    name = "phase0-soak",
    version,
    about = "Record a native-Linux Phase 0 fresh-store resource-plateau probe"
)]
struct Cli {
    /// Staged containment capsule directory or capsule.json path.
    #[arg(long, value_name = "PATH")]
    capsule: PathBuf,

    /// Machine-readable raw soak result destination. The path must be new.
    #[arg(long, value_name = "PATH")]
    output_json: PathBuf,

    /// One-based independent process number, retained in the raw record.
    #[arg(long)]
    run_index: u32,

    /// Reachable commit that identifies the source being measured.
    #[arg(long)]
    source_commit: String,

    /// Git tree for the reachable source commit.
    #[arg(long)]
    source_tree: String,

    /// Durable origin branch or tag that contained the published source commit.
    #[arg(long)]
    published_source_ref: String,

    /// Head of the durable origin branch or tag resolved before collection.
    #[arg(long)]
    published_source_ref_head: String,

    /// Local commit from which this process was executed.
    #[arg(long)]
    execution_commit: String,

    /// Local Git tree from which this process was executed.
    #[arg(long)]
    execution_tree: String,

    /// The source commit explicitly selected as the final post-issue-40 configuration.
    /// A normal soak refuses to make a passing record unless this equals --source-commit.
    #[arg(long)]
    final_configuration_commit: Option<String>,

    /// Permit a deliberately undersized local smoke probe. Its result has status
    /// `test_only` and is rejected by the native-Linux aggregate command.
    #[arg(long)]
    test_mode: bool,

    /// Fresh-store warm-up activations, excluded from all growth analysis.
    #[arg(long, default_value_t = MINIMUM_WARMUP_ACTIVATIONS)]
    warmup_activations: u64,

    /// Normal measured activations, excluding additional saturation activations.
    #[arg(long, default_value_t = MINIMUM_MEASURED_ACTIVATIONS)]
    measured_activations: u64,

    /// Sequential activations per resource checkpoint batch.
    #[arg(long, default_value_t = 100)]
    batch_size: u32,

    /// Run both real saturation modes after this many measured batches.
    #[arg(long, default_value_t = 10)]
    saturation_every_batches: u32,

    /// Fixed generic execution-cell capacity.
    #[arg(long, default_value_t = 2)]
    pool_capacity: u32,

    /// Bounded FIFO waiter capacity.
    #[arg(long, default_value_t = 4)]
    pool_queue_capacity: u32,

    /// Immutable Tokio worker count.
    #[arg(long, default_value_t = 2)]
    runtime_workers: usize,

    /// Per-activation Wasmtime fuel grant.
    #[arg(long, default_value_t = DEFAULT_FUEL)]
    fuel: u64,

    /// Normal activation linear-memory grant.
    #[arg(long, default_value_t = DEFAULT_MEMORY_BYTES)]
    memory_bytes: u64,

    /// Memory-pressure activation grant.
    #[arg(long, default_value_t = DEFAULT_MEMORY_PRESSURE_BYTES)]
    memory_pressure_bytes: u64,

    /// Infinite-guest deadline used for interruption observations.
    #[arg(long, default_value_t = DEFAULT_TIMEOUT_MILLIS)]
    timeout_ms: u64,

    /// Explicit cancellation delay.
    #[arg(long, default_value_t = DEFAULT_CANCELLATION_MILLIS)]
    cancel_after_ms: u64,
}

#[derive(Debug, Clone, Serialize)]
struct EffectiveConfig {
    warmup_activations: u64,
    measured_activations: u64,
    batch_size: u32,
    saturation_every_batches: u32,
    pool_capacity: u32,
    pool_queue_capacity: u32,
    runtime_workers: usize,
    fuel: u64,
    memory_bytes: u64,
    memory_pressure_bytes: u64,
    timeout_ms: u64,
    cancel_after_ms: u64,
    component_maximum_bytes: usize,
    prepared_cache_maximum_entries: usize,
    prepared_cache_maximum_bytes: usize,
    invocation_log_maximum_entries: usize,
    invocation_log_maximum_bytes: usize,
    retained_log_maximum_entries: usize,
    retained_log_maximum_bytes: usize,
    prepared_cache_enabled: bool,
    wasmtime_instance_allocator: String,
    wasmtime_copy_on_write_images: bool,
    test_mode: bool,
}

impl EffectiveConfig {
    fn from_cli(cli: &Cli) -> Result<Self, SoakError> {
        let config = Self {
            warmup_activations: cli.warmup_activations,
            measured_activations: cli.measured_activations,
            batch_size: cli.batch_size,
            saturation_every_batches: cli.saturation_every_batches,
            pool_capacity: cli.pool_capacity,
            pool_queue_capacity: cli.pool_queue_capacity,
            runtime_workers: cli.runtime_workers,
            fuel: cli.fuel,
            memory_bytes: cli.memory_bytes,
            memory_pressure_bytes: cli.memory_pressure_bytes,
            timeout_ms: cli.timeout_ms,
            cancel_after_ms: cli.cancel_after_ms,
            component_maximum_bytes: COMPONENT_MAXIMUM_BYTES,
            prepared_cache_maximum_entries: PREPARED_CACHE_MAXIMUM_ENTRIES,
            prepared_cache_maximum_bytes: PREPARED_CACHE_MAXIMUM_BYTES,
            invocation_log_maximum_entries: LOG_MAXIMUM_ENTRIES,
            invocation_log_maximum_bytes: LOG_MAXIMUM_BYTES,
            retained_log_maximum_entries: LOG_MAXIMUM_ENTRIES,
            retained_log_maximum_bytes: LOG_MAXIMUM_BYTES,
            prepared_cache_enabled: FINAL_PREPARED_CACHE_ENABLED,
            wasmtime_instance_allocator: Phase0InstanceAllocator::OnDemand.name().to_owned(),
            wasmtime_copy_on_write_images: FINAL_WASMTIME_COPY_ON_WRITE_IMAGES,
            test_mode: cli.test_mode,
        };
        if cli.run_index == 0
            || config.batch_size < 11
            || config.pool_capacity == 0
            || config.pool_queue_capacity == 0
            || config.runtime_workers == 0
            || config.fuel == 0
            || config.memory_bytes == 0
            || config.memory_pressure_bytes == 0
            || config.timeout_ms == 0
            || config.cancel_after_ms == 0
            || config.saturation_every_batches == 0
        {
            return Err(SoakError::new(
                "run index, capacities, batches, budgets, and interruption delays must be non-zero; a batch must hold at least the mixed failure/recovery sequence",
            ));
        }
        let batch_size = u64::from(config.batch_size);
        if config.warmup_activations == 0
            || config.measured_activations == 0
            || !config.warmup_activations.is_multiple_of(batch_size)
            || !config.measured_activations.is_multiple_of(batch_size)
        {
            return Err(SoakError::new(
                "warm-up and measured activation counts must be non-zero multiples of --batch-size",
            ));
        }
        if !config.test_mode
            && (config.warmup_activations < MINIMUM_WARMUP_ACTIVATIONS
                || config.measured_activations < MINIMUM_MEASURED_ACTIVATIONS
                || config.saturation_every_batches > 10)
        {
            return Err(SoakError::new(
                "a native-Linux soak requires at least 1,000 warm-up activations, 100,000 measured activations, and both saturation modes at least every ten measured batches; use --test-mode only for an explicitly non-aggregateable local smoke probe",
            ));
        }
        if !valid_git_object_id(&cli.source_commit)
            || !valid_git_object_id(&cli.source_tree)
            || !valid_git_object_id(&cli.published_source_ref_head)
            || !valid_git_object_id(&cli.execution_commit)
            || !valid_git_object_id(&cli.execution_tree)
        {
            return Err(SoakError::new(
                "source, durable-ref head, and execution commit/tree identifiers must be 40-character lowercase Git object IDs",
            ));
        }
        if !valid_published_source_ref(&cli.published_source_ref) {
            return Err(SoakError::new(
                "published source ref must be a non-empty refs/heads/* or refs/tags/* name",
            ));
        }
        if cli.execution_commit != cli.source_commit {
            return Err(SoakError::new(
                "execution commit does not match the declared published source commit",
            ));
        }
        if cli.execution_tree != cli.source_tree {
            return Err(SoakError::new(
                "execution tree does not match the declared published source tree",
            ));
        }
        if !config.test_mode
            && cli.final_configuration_commit.as_deref() != Some(cli.source_commit.as_str())
        {
            return Err(SoakError::new(
                "a passing soak requires --final-configuration-commit equal to --source-commit after issue #40 has selected the final Phase 0 configuration",
            ));
        }
        Ok(config)
    }
}

#[derive(Debug)]
struct SoakError(String);

impl SoakError {
    fn new(message: impl Into<String>) -> Self {
        Self(message.into())
    }
}

impl fmt::Display for SoakError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl Error for SoakError {}

impl From<std::io::Error> for SoakError {
    fn from(error: std::io::Error) -> Self {
        Self(error.to_string())
    }
}

impl From<serde_json::Error> for SoakError {
    fn from(error: serde_json::Error) -> Self {
        Self(error.to_string())
    }
}

#[derive(Debug, Clone, Serialize)]
struct SourceIdentity {
    published_commit: String,
    published_tree: String,
    published_source_ref: String,
    published_source_ref_head: String,
    published_commit_reachable_from_ref: bool,
    execution_commit: String,
    execution_tree: String,
    execution_commit_matches_published: bool,
    tree_identity_verified: bool,
    final_configuration_commit: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
struct EnvironmentReport {
    operating_system: String,
    architecture: String,
    kernel: String,
    cpu_model: String,
    logical_cpu_count: usize,
    total_memory_bytes: Option<u64>,
    rustc: String,
    cargo: String,
    rust_target: String,
    build_profile: String,
    wasmtime_version: String,
    allocator_statistics: AllocatorStatistics,
    native_linux_validation: NativeLinuxValidation,
}

#[derive(Debug, Clone, Serialize)]
struct AllocatorStatistics {
    available: bool,
    method: String,
    reason: String,
}

#[derive(Debug, Clone, Serialize)]
struct NativeLinuxValidation {
    operating_system: String,
    wsl_detected: bool,
    container_kind: String,
    virtualization_kind: String,
    proc_probe_available: bool,
}

#[derive(Debug, Clone, Serialize)]
struct ArtifactReport {
    collector: latentd::phase0_collector::NativeCollectorIdentity,
    capsule_path: String,
    capsule_digest: String,
    capsule_bytes: u64,
    component_path: String,
    component_digest: String,
    component_bytes: u64,
}

#[derive(Debug, Clone, Serialize)]
struct ProcessSnapshot {
    offset_micros: u64,
    process_count: u32,
    child_process_count: u32,
    thread_count: u64,
    file_descriptor_count: u64,
    open_socket_count: u64,
    listening_socket_count: u64,
    rss_bytes: u64,
    virtual_memory_bytes: u64,
    pss_bytes: Option<u64>,
    private_bytes: Option<u64>,
    probe_notes: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
struct PoolReport {
    capacity: u32,
    available: u32,
    queue_depth: u32,
    active_leases: u32,
    quarantined: u32,
}

#[derive(Debug, Clone, Serialize)]
struct RunnerReport {
    active_cancellation_registrations: u64,
    running_invocations: u64,
    total_invocations: u64,
    released_cells: u64,
    quarantined_cells: u64,
    disposition_failures: u64,
}

#[derive(Debug, Clone, Serialize)]
struct BackendResourceReport {
    active_invocations: u64,
    live_stores: u64,
    live_host_states: u64,
    live_component_instances: u64,
    live_temporary_buffers: u64,
    live_cancellation_probes: u64,
    stores_created: u64,
}

#[derive(Debug, Clone, Serialize)]
struct CacheReport {
    entries: usize,
    source_bytes: usize,
    maximum_entries: usize,
    maximum_source_bytes: usize,
}

#[derive(Debug, Clone, Serialize)]
struct TimingStoreReport {
    entries: usize,
    maximum_entries: usize,
}

#[derive(Debug, Clone, Serialize)]
struct ResourceSample {
    phase: String,
    batch_kind: String,
    batch_index: u64,
    normal_measured_activations_completed: u64,
    total_activation_count: u64,
    process: ProcessSnapshot,
    pool: PoolReport,
    runner: RunnerReport,
    backend_resources: BackendResourceReport,
    prepared_cache: CacheReport,
    backend_timing_store: TimingStoreReport,
    retained_log_entries_after_clear: usize,
    observed_runtime_workers: usize,
    invariant_passed: bool,
}

#[derive(Debug, Clone, Serialize)]
struct Check {
    name: String,
    passed: bool,
    expected: String,
    observed: String,
}

#[derive(Debug, Clone, Default, Serialize)]
struct WorkloadCounters {
    warmup_activations: u64,
    normal_measured_activations: u64,
    saturation_activations: u64,
    batch_invariants_checked: u64,
    scenario_counts: BTreeMap<String, u64>,
    saturation_batch_counts: BTreeMap<String, u64>,
}

#[derive(Debug, Clone, Serialize)]
struct SaturationObservation {
    mode: String,
    activations: u32,
    maximum_observed_active_leases: u32,
    maximum_observed_queue_depth: u32,
}

#[derive(Debug, Clone, Serialize)]
struct ShutdownObservation {
    process: ProcessSnapshot,
    observed_runtime_workers: usize,
}

#[derive(Debug, Serialize)]
struct SoakDocument {
    schema_version: &'static str,
    status: String,
    test_only: bool,
    profile: &'static str,
    generated_at_unix_millis: u64,
    run_index: u32,
    command: Vec<String>,
    source_identity: SourceIdentity,
    environment: EnvironmentReport,
    artifact: ArtifactReport,
    config: EffectiveConfig,
    process_before_runtime: ProcessSnapshot,
    process_after_warmup: ProcessSnapshot,
    workload: WorkloadCounters,
    resource_samples: Vec<ResourceSample>,
    saturation_observations: Vec<SaturationObservation>,
    post_release: ResourceSample,
    post_shutdown: ShutdownObservation,
    checks: Vec<Check>,
    limitations: Vec<String>,
}

#[derive(Clone, Debug)]
struct SaturationGate {
    closed: tokio::sync::watch::Sender<bool>,
}

impl SaturationGate {
    fn new() -> Self {
        let (closed, _receiver) = tokio::sync::watch::channel(false);
        Self { closed }
    }

    fn close(&self) {
        self.closed.send_replace(true);
    }

    fn open(&self) {
        self.closed.send_replace(false);
    }

    async fn wait_until_open(&self) {
        let mut state = self.closed.subscribe();
        while *state.borrow_and_update() {
            if state.changed().await.is_err() {
                return;
            }
        }
    }
}

#[derive(Clone)]
struct GatedCellPool {
    inner: Arc<FixedCellPool>,
    gate: SaturationGate,
}

impl GatedCellPool {
    fn new(inner: Arc<FixedCellPool>, gate: SaturationGate) -> Self {
        Self { inner, gate }
    }
}

impl CellPool for GatedCellPool {
    fn acquire<'a>(
        &'a self,
        activation_id: &'a ActivationId,
        tenant: &'a TenantId,
        class: CellClass,
        budget: &'a ResourceBudget,
    ) -> BoxFuture<'a, Result<CellLease, PlatformError>> {
        let activation_id = activation_id.clone();
        let tenant = tenant.clone();
        let budget = budget.clone();
        let inner = Arc::clone(&self.inner);
        let gate = self.gate.clone();
        Box::pin(async move {
            let lease = inner
                .acquire(&activation_id, &tenant, class, &budget)
                .await?;
            gate.wait_until_open().await;
            Ok(lease)
        })
    }

    fn release(&self, lease: CellLease) -> BoxFuture<'_, Result<(), PlatformError>> {
        self.inner.release(lease)
    }

    fn capacity(&self, class: CellClass) -> u32 {
        self.inner.capacity(class)
    }

    fn available(&self, class: CellClass) -> u32 {
        self.inner.available(class)
    }

    fn cancel_waiting<'a>(
        &'a self,
        activation_id: &'a ActivationId,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        self.inner.cancel_waiting(activation_id)
    }

    fn quarantine(
        &self,
        lease: CellLease,
        reason: String,
    ) -> BoxFuture<'_, Result<(), PlatformError>> {
        self.inner.quarantine(lease, reason)
    }

    fn observations(&self, class: CellClass) -> CellPoolSnapshot {
        CellPool::observations(self.inner.as_ref(), class)
    }
}

#[derive(Clone, Copy)]
enum ExpectedOutcome {
    Success,
    DomainError,
    Trap,
    Timeout,
    Cancelled,
    ResourceExhausted,
}

struct InvocationSpec<'a> {
    scenario: &'a str,
    input: String,
    expected: ExpectedOutcome,
    memory_bytes: u64,
    timeout_ms: u64,
    cancel_after_ms: Option<u64>,
}

#[derive(Clone)]
struct TopologyReference {
    processes: u32,
    children: u32,
    threads: u64,
    open_sockets: u64,
    listeners: u64,
}

enum CacheExpectation {
    Prepared { entries: usize, source_bytes: usize },
    Released,
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    match run(cli) {
        Ok(true) => ExitCode::SUCCESS,
        Ok(false) => ExitCode::from(1),
        Err(error) => {
            eprintln!("Phase 0 resource soak failed: {error}");
            ExitCode::from(2)
        }
    }
}

fn run(cli: Cli) -> Result<bool, SoakError> {
    let config = EffectiveConfig::from_cli(&cli)?;
    if cli.output_json.exists() {
        return Err(SoakError::new(format!(
            "soak output must be a new path and will not overwrite evidence: {}",
            cli.output_json.display()
        )));
    }
    let native_linux_validation = validate_native_linux()?;
    let process_entry = Instant::now();
    let process_before_runtime = observe_process(process_entry)?;

    let composition = phase0_composition::construct_runtime_composition(&Phase0RuntimeConfig {
        node_id: NodeId(NODE_ID.to_owned()),
        pool_capacity: config.pool_capacity,
        pool_queue_capacity: config.pool_queue_capacity,
        runtime_workers: config.runtime_workers,
    })
    .map_err(platform_error)?;
    let latentd::phase0_composition::Phase0RuntimeComposition {
        runtime,
        pool,
        workers,
    } = composition;
    runtime
        .block_on(phase0_composition::wait_for_runtime_workers(
            &workers,
            config.runtime_workers,
        ))
        .map_err(platform_error)?;

    let mut document = runtime.block_on(run_async(
        &cli,
        &config,
        Arc::clone(&pool),
        workers.clone(),
        process_entry,
        native_linux_validation,
        process_before_runtime.clone(),
    ))?;

    drop(pool);
    drop(runtime);
    std::thread::sleep(Duration::from_millis(25));
    let shutdown_process = observe_process(process_entry)?;
    let post_release_file_descriptors = document.post_release.process.file_descriptor_count;
    let shutdown_pass = workers.active_workers() == 0
        && shutdown_process.process_count == process_before_runtime.process_count
        && shutdown_process.child_process_count == process_before_runtime.child_process_count
        && shutdown_process.file_descriptor_count <= process_before_runtime.file_descriptor_count
        && shutdown_process.file_descriptor_count <= post_release_file_descriptors
        && shutdown_process.open_socket_count == process_before_runtime.open_socket_count
        && shutdown_process.listening_socket_count == process_before_runtime.listening_socket_count
        && shutdown_process.thread_count <= process_before_runtime.thread_count.saturating_add(1);
    document.post_shutdown = ShutdownObservation {
        process: shutdown_process.clone(),
        observed_runtime_workers: workers.active_workers(),
    };
    document.checks.push(Check {
        name: "runtime_shutdown_returns_to_process_baseline".to_owned(),
        passed: shutdown_pass,
        expected: "no runtime workers, original process/socket topology, no post-release file-descriptor increase, and no more than one residual OS thread".to_owned(),
        observed: format!(
            "workers={}, processes={}, children={}, threads={}, file_descriptors={}, post_release_file_descriptors={}, sockets={}, listeners={}",
            workers.active_workers(),
            shutdown_process.process_count,
            shutdown_process.child_process_count,
            shutdown_process.thread_count,
            shutdown_process.file_descriptor_count,
            post_release_file_descriptors,
            shutdown_process.open_socket_count,
            shutdown_process.listening_socket_count
        ),
    });
    let all_passed = document.checks.iter().all(|check| check.passed);
    document.status = if config.test_mode {
        "test_only".to_owned()
    } else if all_passed {
        "pass".to_owned()
    } else {
        "fail".to_owned()
    };
    write_document(&cli.output_json, &document)?;
    println!(
        "{}",
        serde_json::json!({
            "schema_version": SCHEMA_VERSION,
            "status": document.status,
            "raw_result": cli.output_json,
        })
    );
    Ok(all_passed && !config.test_mode)
}

async fn run_async(
    cli: &Cli,
    config: &EffectiveConfig,
    pool: Arc<FixedCellPool>,
    workers: Phase0RuntimeWorkerMonitor,
    process_entry: Instant,
    native_linux_validation: NativeLinuxValidation,
    process_before_runtime: ProcessSnapshot,
) -> Result<SoakDocument, SoakError> {
    let collector = latentd::phase0_collector::native_collector_identity("phase0-soak")
        .map_err(SoakError::new)?;
    let (capsule_path, capsule_digest, capsule_bytes) = capsule_identity(&cli.capsule)?;
    let prepared_backend = phase0_composition::prepare_phase0_backend(&Phase0PreparationConfig {
        capsule: cli.capsule.clone(),
        component: None,
        component_maximum_bytes: config.component_maximum_bytes,
        prepared_cache_maximum_entries: config.prepared_cache_maximum_entries,
        prepared_cache_maximum_bytes: config.prepared_cache_maximum_bytes,
        // The soak measures the final ordinary Phase 0 configuration selected
        // after issue #40, never an allocator, COW, or cache experiment.
        prepared_cache_enabled: config.prepared_cache_enabled,
        invocation_log_maximum_entries: config.invocation_log_maximum_entries,
        invocation_log_maximum_bytes: config.invocation_log_maximum_bytes,
        retained_log_maximum_entries: config.retained_log_maximum_entries,
        retained_log_maximum_bytes: config.retained_log_maximum_bytes,
        requested_memory_bytes: config.memory_bytes.max(config.memory_pressure_bytes),
        requested_fuel: config.fuel,
        wasmtime_instance_allocator: Phase0InstanceAllocator::OnDemand,
        wasmtime_copy_on_write_images: config.wasmtime_copy_on_write_images,
        wasmtime_pooling_maximum_instances: config.pool_capacity,
    })
    .await
    .map_err(platform_error)?;
    let latentd::phase0_composition::Phase0PreparedBackend {
        loaded,
        backend,
        prepared,
        cache_after_prepare,
        ..
    } = prepared_backend;
    let gate = SaturationGate::new();
    let pool_for_runner: Arc<dyn CellPool> =
        Arc::new(GatedCellPool::new(Arc::clone(&pool), gate.clone()));
    let backend_for_runner: Arc<dyn ExecutionBackend> = backend.clone();
    let runner = phase0_composition::create_phase0_activation_runner(
        pool_for_runner,
        backend_for_runner,
        prepared.clone(),
    )
    .map_err(platform_error)?;

    let topology_reference = topology_reference(&observe_process(process_entry)?);
    let mut workload = WorkloadCounters::default();
    let mut samples = Vec::new();
    let mut saturation_observations = Vec::new();
    let mut batch_index = 0_u64;
    let after_prepare = resource_sample(
        "after_prepare",
        "after_prepare",
        batch_index,
        &workload,
        &pool,
        &runner,
        &backend,
        &workers,
        &topology_reference,
        CacheExpectation::Prepared {
            entries: cache_after_prepare.entries,
            source_bytes: cache_after_prepare.source_bytes,
        },
        config,
        process_entry,
    )?;
    samples.push(after_prepare);

    let warmup_batches = config.warmup_activations / u64::from(config.batch_size);
    for batch in 1..=warmup_batches {
        run_warmup_batch(
            config,
            &loaded.artifact.manifest,
            &runner,
            &backend,
            &mut workload,
            batch,
        )
        .await?;
        batch_index = batch_index.saturating_add(1);
        workload.batch_invariants_checked = workload.batch_invariants_checked.saturating_add(1);
        samples.push(resource_sample(
            "warmup",
            "warmup_success",
            batch_index,
            &workload,
            &pool,
            &runner,
            &backend,
            &workers,
            &topology_reference,
            CacheExpectation::Prepared {
                entries: cache_after_prepare.entries,
                source_bytes: cache_after_prepare.source_bytes,
            },
            config,
            process_entry,
        )?);
    }

    // The first steady descriptor baseline is meaningful only after the
    // excluded warm-up has exercised the prepared component and runtime.  It
    // is retained separately from the earlier preparation checkpoint so the
    // measured window cannot hide a descriptor introduced after preparation.
    let process_after_warmup = observe_process(process_entry)?;

    let measured_batches = config.measured_activations / u64::from(config.batch_size);
    for batch in 1..=measured_batches {
        run_mixed_measured_batch(
            config,
            &loaded.artifact.manifest,
            &runner,
            &backend,
            &mut workload,
            batch,
        )
        .await?;
        batch_index = batch_index.saturating_add(1);
        workload.batch_invariants_checked = workload.batch_invariants_checked.saturating_add(1);
        samples.push(resource_sample(
            "measured",
            "mixed_success_failure_recovery",
            batch_index,
            &workload,
            &pool,
            &runner,
            &backend,
            &workers,
            &topology_reference,
            CacheExpectation::Prepared {
                entries: cache_after_prepare.entries,
                source_bytes: cache_after_prepare.source_bytes,
            },
            config,
            process_entry,
        )?);

        if batch % u64::from(config.saturation_every_batches) == 0 {
            for mode in [SaturationMode::AtCapacity, SaturationMode::BoundedQueue] {
                let observation = run_saturation_batch(
                    config,
                    &loaded.artifact.manifest,
                    &pool,
                    &runner,
                    &backend,
                    &gate,
                    &mut workload,
                    batch,
                    mode,
                )
                .await?;
                let batch_kind = observation.mode.clone();
                saturation_observations.push(observation);
                batch_index = batch_index.saturating_add(1);
                workload.batch_invariants_checked =
                    workload.batch_invariants_checked.saturating_add(1);
                samples.push(resource_sample(
                    "measured",
                    &batch_kind,
                    batch_index,
                    &workload,
                    &pool,
                    &runner,
                    &backend,
                    &workers,
                    &topology_reference,
                    CacheExpectation::Prepared {
                        entries: cache_after_prepare.entries,
                        source_bytes: cache_after_prepare.source_bytes,
                    },
                    config,
                    process_entry,
                )?);
            }
        }
    }

    let scenario_pass = required_scenarios_present(&workload.scenario_counts);
    let at_capacity_pass = saturation_observations
        .iter()
        .filter(|observation| observation.mode == "at_capacity")
        .all(|observation| {
            observation.maximum_observed_active_leases == config.pool_capacity
                && observation.maximum_observed_queue_depth == 0
        })
        && workload
            .saturation_batch_counts
            .get("at_capacity")
            .copied()
            .unwrap_or(0)
            > 0;
    let bounded_queue_pass = saturation_observations
        .iter()
        .filter(|observation| observation.mode == "bounded_queue_saturation")
        .all(|observation| {
            observation.maximum_observed_active_leases == config.pool_capacity
                && observation.maximum_observed_queue_depth == config.pool_queue_capacity
        })
        && workload
            .saturation_batch_counts
            .get("bounded_queue_saturation")
            .copied()
            .unwrap_or(0)
            > 0;

    backend.release(prepared).await.map_err(platform_error)?;
    backend.log_sink().clear();
    let post_release = resource_sample(
        "post_release",
        "prepared_component_released",
        batch_index.saturating_add(1),
        &workload,
        &pool,
        &runner,
        &backend,
        &workers,
        &topology_reference,
        CacheExpectation::Released,
        config,
        process_entry,
    )?;

    let all_batch_samples_pass = samples.iter().all(|sample| sample.invariant_passed);
    let environment = environment_report(native_linux_validation);
    let source_identity = SourceIdentity {
        published_commit: cli.source_commit.clone(),
        published_tree: cli.source_tree.clone(),
        published_source_ref: cli.published_source_ref.clone(),
        published_source_ref_head: cli.published_source_ref_head.clone(),
        published_commit_reachable_from_ref: true,
        execution_commit: cli.execution_commit.clone(),
        execution_tree: cli.execution_tree.clone(),
        execution_commit_matches_published: cli.execution_commit == cli.source_commit,
        tree_identity_verified: cli.execution_tree == cli.source_tree,
        final_configuration_commit: cli.final_configuration_commit.clone(),
    };
    let checks = vec![
        Check {
            name: "native_linux_process_resource_probes_are_available".to_owned(),
            passed: true,
            expected: "native Linux without WSL/container execution and required /proc probes".to_owned(),
            observed: "validated before runtime construction".to_owned(),
        },
        Check {
            name: "prepared_cache_is_fixed_and_bounded".to_owned(),
            passed: cache_after_prepare.entries == 1
                && cache_after_prepare.source_bytes <= cache_after_prepare.maximum_source_bytes
                && cache_after_prepare.entries <= cache_after_prepare.maximum_entries,
            expected: "one prepared entry within configured entry and byte limits".to_owned(),
            observed: format!(
                "entries={}, source_bytes={}, maximum_entries={}, maximum_source_bytes={}",
                cache_after_prepare.entries,
                cache_after_prepare.source_bytes,
                cache_after_prepare.maximum_entries,
                cache_after_prepare.maximum_source_bytes
            ),
        },
        Check {
            name: "every_completed_batch_returns_logical_resources_to_zero".to_owned(),
            passed: all_batch_samples_pass,
            expected: "every warm-up, measured, and saturation batch returns pool, runner, backend, logs, and timing-store occupancy to its bounded baseline".to_owned(),
            observed: format!("{} completed batch checkpoints", workload.batch_invariants_checked),
        },
        Check {
            name: "fresh_store_outcomes_and_cause_specific_recovery_pass".to_owned(),
            passed: scenario_pass,
            expected: "success, domain error, trap, timeout, cancellation, memory pressure, and each immediately following cause-specific recovery all succeed as specified".to_owned(),
            observed: scenario_summary(&workload.scenario_counts),
        },
        Check {
            name: "real_at_capacity_batches_reach_exact_pool_capacity".to_owned(),
            passed: at_capacity_pass,
            expected: format!("active leases={} and queue depth=0", config.pool_capacity),
            observed: saturation_summary(&saturation_observations, "at_capacity"),
        },
        Check {
            name: "real_bounded_queue_batches_reach_exact_pool_and_queue_capacity".to_owned(),
            passed: bounded_queue_pass,
            expected: format!(
                "active leases={} and queue depth={}",
                config.pool_capacity, config.pool_queue_capacity
            ),
            observed: saturation_summary(&saturation_observations, "bounded_queue_saturation"),
        },
        Check {
            name: "post_release_returns_all_logical_resources_to_zero".to_owned(),
            passed: post_release.invariant_passed,
            expected: "prepared cache, runner state, backend live resources, logs, timing records, and pool activity are zero after explicit release".to_owned(),
            observed: format!(
                "cache_entries={}, active_leases={}, live_stores={}, timing_entries={}",
                post_release.prepared_cache.entries,
                post_release.pool.active_leases,
                post_release.backend_resources.live_stores,
                post_release.backend_timing_store.entries
            ),
        },
    ];
    Ok(SoakDocument {
        schema_version: SCHEMA_VERSION,
        status: "pending".to_owned(),
        test_only: config.test_mode,
        profile: "native_linux_resource_soak",
        generated_at_unix_millis: now_unix_millis(),
        run_index: cli.run_index,
        command: std::env::args().collect(),
        source_identity,
        environment,
        artifact: ArtifactReport {
            collector,
            capsule_path,
            capsule_digest,
            capsule_bytes,
            component_path: loaded.component_path.display().to_string(),
            component_digest: loaded.artifact.manifest.component_digest.0,
            component_bytes: loaded.component_bytes,
        },
        config: config.clone(),
        process_before_runtime,
        process_after_warmup,
        workload,
        resource_samples: samples,
        saturation_observations,
        post_release,
        post_shutdown: ShutdownObservation {
            process: observe_process(process_entry)?,
            observed_runtime_workers: workers.active_workers(),
        },
        checks,
        limitations: vec![
            "The raw samples are bounded batch checkpoints. Every individual activation drains its diagnostic timing entry and every completed batch is asserted before its checkpoint is written.".to_owned(),
            "PSS and private mappings are read from /proc/self/smaps_rollup when exposed by this Linux host. Allocator-internal statistics are intentionally marked unavailable because this safe Rust probe does not call allocator-specific unsafe APIs.".to_owned(),
            "This is observational Phase 0 evidence, not a production SLO, capacity guarantee, or cross-machine performance claim.".to_owned(),
        ],
    })
}

async fn run_warmup_batch(
    config: &EffectiveConfig,
    manifest: &CapsuleManifest,
    runner: &Arc<Phase0ActivationRunner>,
    backend: &Arc<Phase0WasmtimeBackend>,
    workload: &mut WorkloadCounters,
    batch: u64,
) -> Result<(), SoakError> {
    for slot in 0..config.batch_size {
        let scenario = "warmup_success";
        let input = format!("phase0 soak warmup {batch:08}-{slot:04}");
        invoke_and_verify(
            config,
            manifest,
            runner,
            backend,
            workload,
            InvocationSpec {
                scenario,
                input,
                expected: ExpectedOutcome::Success,
                memory_bytes: config.memory_bytes,
                timeout_ms: 1_000,
                cancel_after_ms: None,
            },
            true,
        )
        .await?;
    }
    Ok(())
}

async fn run_mixed_measured_batch(
    config: &EffectiveConfig,
    manifest: &CapsuleManifest,
    runner: &Arc<Phase0ActivationRunner>,
    backend: &Arc<Phase0WasmtimeBackend>,
    workload: &mut WorkloadCounters,
    batch: u64,
) -> Result<(), SoakError> {
    let prefix = [
        InvocationSpec {
            scenario: "success",
            input: format!("phase0 soak success {batch:08}"),
            expected: ExpectedOutcome::Success,
            memory_bytes: config.memory_bytes,
            timeout_ms: 1_000,
            cancel_after_ms: None,
        },
        InvocationSpec {
            scenario: "domain_error",
            input: String::new(),
            expected: ExpectedOutcome::DomainError,
            memory_bytes: config.memory_bytes,
            timeout_ms: 1_000,
            cancel_after_ms: None,
        },
        InvocationSpec {
            scenario: "recovery_after_domain_error",
            input: format!("healthy after domain error {batch:08}"),
            expected: ExpectedOutcome::Success,
            memory_bytes: config.memory_bytes,
            timeout_ms: 1_000,
            cancel_after_ms: None,
        },
        InvocationSpec {
            scenario: "trap",
            input: FIXTURE_TRAP.to_owned(),
            expected: ExpectedOutcome::Trap,
            memory_bytes: config.memory_bytes,
            timeout_ms: 1_000,
            cancel_after_ms: None,
        },
        InvocationSpec {
            scenario: "recovery_after_trap",
            input: format!("healthy after trap {batch:08}"),
            expected: ExpectedOutcome::Success,
            memory_bytes: config.memory_bytes,
            timeout_ms: 1_000,
            cancel_after_ms: None,
        },
        InvocationSpec {
            scenario: "timeout",
            input: FIXTURE_INFINITE.to_owned(),
            expected: ExpectedOutcome::Timeout,
            memory_bytes: config.memory_bytes,
            timeout_ms: config.timeout_ms,
            cancel_after_ms: None,
        },
        InvocationSpec {
            scenario: "recovery_after_timeout",
            input: format!("healthy after timeout {batch:08}"),
            expected: ExpectedOutcome::Success,
            memory_bytes: config.memory_bytes,
            timeout_ms: 1_000,
            cancel_after_ms: None,
        },
        InvocationSpec {
            scenario: "cancellation",
            input: FIXTURE_INFINITE.to_owned(),
            expected: ExpectedOutcome::Cancelled,
            memory_bytes: config.memory_bytes,
            timeout_ms: 1_000,
            cancel_after_ms: Some(config.cancel_after_ms),
        },
        InvocationSpec {
            scenario: "recovery_after_cancellation",
            input: format!("healthy after cancellation {batch:08}"),
            expected: ExpectedOutcome::Success,
            memory_bytes: config.memory_bytes,
            timeout_ms: 1_000,
            cancel_after_ms: None,
        },
        InvocationSpec {
            scenario: "memory_pressure",
            input: FIXTURE_MEMORY.to_owned(),
            expected: ExpectedOutcome::ResourceExhausted,
            memory_bytes: config.memory_pressure_bytes,
            timeout_ms: 2_000,
            cancel_after_ms: None,
        },
        InvocationSpec {
            scenario: "recovery_after_memory_pressure",
            input: format!("healthy after memory pressure {batch:08}"),
            expected: ExpectedOutcome::Success,
            memory_bytes: config.memory_bytes,
            timeout_ms: 1_000,
            cancel_after_ms: None,
        },
    ];
    for spec in prefix {
        invoke_and_verify(config, manifest, runner, backend, workload, spec, false).await?;
    }
    for slot in 11..config.batch_size {
        invoke_and_verify(
            config,
            manifest,
            runner,
            backend,
            workload,
            InvocationSpec {
                scenario: "success",
                input: format!("phase0 soak retained success {batch:08}-{slot:04}"),
                expected: ExpectedOutcome::Success,
                memory_bytes: config.memory_bytes,
                timeout_ms: 1_000,
                cancel_after_ms: None,
            },
            false,
        )
        .await?;
    }
    Ok(())
}

#[derive(Clone, Copy)]
enum SaturationMode {
    AtCapacity,
    BoundedQueue,
}

impl SaturationMode {
    const fn name(self) -> &'static str {
        match self {
            Self::AtCapacity => "at_capacity",
            Self::BoundedQueue => "bounded_queue_saturation",
        }
    }

    fn activation_count(self, config: &EffectiveConfig) -> Result<u32, SoakError> {
        match self {
            Self::AtCapacity => Ok(config.pool_capacity),
            Self::BoundedQueue => config
                .pool_capacity
                .checked_add(config.pool_queue_capacity)
                .ok_or_else(|| SoakError::new("saturated activation count overflow")),
        }
    }

    const fn expected_queue_depth(self, config: &EffectiveConfig) -> u32 {
        match self {
            Self::AtCapacity => 0,
            Self::BoundedQueue => config.pool_queue_capacity,
        }
    }
}

#[allow(clippy::too_many_arguments)]
async fn run_saturation_batch(
    config: &EffectiveConfig,
    manifest: &CapsuleManifest,
    pool: &Arc<FixedCellPool>,
    runner: &Arc<Phase0ActivationRunner>,
    backend: &Arc<Phase0WasmtimeBackend>,
    gate: &SaturationGate,
    workload: &mut WorkloadCounters,
    batch: u64,
    mode: SaturationMode,
) -> Result<SaturationObservation, SoakError> {
    let activation_count = mode.activation_count(config)?;
    let expected_queue_depth = mode.expected_queue_depth(config);
    let stores_before = backend.stores_created();
    gate.close();
    let participant_count = usize::try_from(activation_count)
        .map_err(|_| SoakError::new("saturation participant count does not fit usize"))?;
    let barrier = Arc::new(Barrier::new(participant_count.saturating_add(1)));

    let mut handles = Vec::new();
    for slot in 0..activation_count {
        let activation_id = ActivationId(format!(
            "soak-saturation-{}-{batch:08}-{slot:04}",
            mode.name()
        ));
        let expected_output = format!("soak-{}-{batch}-{slot}", mode.name());
        let input = format!("{FIXTURE_DELAYED_ECHO_PREFIX}{expected_output}");
        let envelope = phase0_composition::phase0_activation_envelope(
            manifest,
            &Phase0InvocationConfig {
                activation_id: activation_id.clone(),
                input: &input,
                memory_bytes: config.memory_bytes,
                fuel: config.fuel,
                deadline_unix_millis: now_unix_millis().saturating_add(10_000),
                surface: SURFACE,
                mode: "phase0-soak",
                principal_subject: "phase0-soak-user",
                default_tenant: "phase0-soak",
                trace_id: TRACE_ID,
                span_id: SPAN_ID,
            },
        );
        let worker_runner = Arc::clone(runner);
        let worker_barrier = Arc::clone(&barrier);
        handles.push(tokio::spawn(async move {
            worker_barrier.wait().await;
            let outcome = worker_runner.invoke(envelope).await;
            Ok::<_, SoakError>((activation_id, expected_output, outcome))
        }));
    }
    barrier.wait().await;
    let saturation_result =
        wait_for_saturation(pool, mode, config.pool_capacity, expected_queue_depth).await;
    // This is the authoritative observation: it is read while the real leases
    // are still held behind the gate, immediately after the exact-state proof.
    // A background maximum monitor can miss a short saturated interval if it
    // first receives CPU after the gate opens.
    let coordinated_snapshot = pool.observations();
    // Always release actual granted leases before joining, even after an
    // observation failure, so an invalid run cannot strand a worker.
    gate.open();
    let mut completed = Vec::new();
    for handle in handles {
        completed.push(
            handle
                .await
                .map_err(|error| SoakError::new(format!("saturation task failed: {error}")))??,
        );
    }
    saturation_result?;
    let stores_after = backend.stores_created();
    if stores_after != stores_before.saturating_add(u64::from(activation_count)) {
        return Err(SoakError::new(format!(
            "{} saturation did not use one fresh store per activation: before={}, after={}, activations={}",
            mode.name(), stores_before, stores_after, activation_count
        )));
    }
    for (activation_id, expected_output, outcome) in completed {
        let timing = backend.take_invocation_timing(&activation_id);
        if timing.is_none() {
            return Err(SoakError::new(format!(
                "{} saturation activation has no backend timing record: {}",
                mode.name(),
                activation_id.0
            )));
        }
        if !successful_output(&outcome, &expected_output) {
            return Err(SoakError::new(format!(
                "{} saturation activation returned an unexpected outcome",
                mode.name()
            )));
        }
    }
    backend.log_sink().clear();
    workload.saturation_activations = workload
        .saturation_activations
        .saturating_add(u64::from(activation_count));
    let success_count = workload
        .scenario_counts
        .entry("success".to_owned())
        .or_default();
    *success_count = success_count.saturating_add(u64::from(activation_count));
    let saturation_count = workload
        .saturation_batch_counts
        .entry(mode.name().to_owned())
        .or_default();
    *saturation_count = saturation_count.saturating_add(1);
    Ok(SaturationObservation {
        mode: mode.name().to_owned(),
        activations: activation_count,
        maximum_observed_active_leases: coordinated_snapshot.active_leases,
        maximum_observed_queue_depth: coordinated_snapshot.queue_depth,
    })
}

async fn wait_for_saturation(
    pool: &FixedCellPool,
    mode: SaturationMode,
    expected_active: u32,
    expected_queue: u32,
) -> Result<(), SoakError> {
    let deadline = tokio::time::Instant::now() + Duration::from_secs(2);
    loop {
        let snapshot = pool.observations();
        if snapshot.active_leases == expected_active && snapshot.queue_depth == expected_queue {
            return Ok(());
        }
        if tokio::time::Instant::now() >= deadline {
            return Err(SoakError::new(format!(
                "real {} activation batch did not reach its required pool state: active={} expected={}, queue={} expected={}",
                mode.name(), snapshot.active_leases, expected_active, snapshot.queue_depth, expected_queue
            )));
        }
        tokio::task::yield_now().await;
    }
}

#[allow(clippy::too_many_arguments)]
async fn invoke_and_verify(
    config: &EffectiveConfig,
    manifest: &CapsuleManifest,
    runner: &Arc<Phase0ActivationRunner>,
    backend: &Arc<Phase0WasmtimeBackend>,
    workload: &mut WorkloadCounters,
    spec: InvocationSpec<'_>,
    warmup: bool,
) -> Result<(), SoakError> {
    let total_before = workload
        .warmup_activations
        .saturating_add(workload.normal_measured_activations)
        .saturating_add(workload.saturation_activations);
    let activation_id = ActivationId(format!(
        "soak-{}-{total_before:08}",
        spec.scenario.replace('_', "-")
    ));
    let envelope = phase0_composition::phase0_activation_envelope(
        manifest,
        &Phase0InvocationConfig {
            activation_id: activation_id.clone(),
            input: &spec.input,
            memory_bytes: spec.memory_bytes,
            fuel: config.fuel,
            deadline_unix_millis: now_unix_millis().saturating_add(spec.timeout_ms),
            surface: SURFACE,
            mode: "phase0-soak",
            principal_subject: "phase0-soak-user",
            default_tenant: "phase0-soak",
            trace_id: TRACE_ID,
            span_id: SPAN_ID,
        },
    );
    let stores_before = backend.stores_created();
    let invocation = runner.invoke(envelope);
    tokio::pin!(invocation);
    let outcome = if let Some(cancel_after_ms) = spec.cancel_after_ms {
        tokio::select! {
            biased;
            outcome = &mut invocation => outcome,
            () = tokio::time::sleep(Duration::from_millis(cancel_after_ms)) => {
                let _ = runner.cancel(&activation_id, "phase0 soak explicit cancellation").await;
                invocation.await
            }
        }
    } else {
        invocation.await
    };
    let stores_after = backend.stores_created();
    if stores_after != stores_before.saturating_add(1) {
        return Err(SoakError::new(format!(
            "{} did not construct exactly one fresh Wasmtime store: before={}, after={}",
            spec.scenario, stores_before, stores_after
        )));
    }
    if backend.take_invocation_timing(&activation_id).is_none() {
        return Err(SoakError::new(format!(
            "{} did not produce a bounded backend timing record",
            spec.scenario
        )));
    }
    backend.log_sink().clear();
    if !outcome_matches(spec.expected, &spec.input, &outcome) {
        return Err(SoakError::new(format!(
            "{} returned an unexpected terminal outcome",
            spec.scenario
        )));
    }
    if warmup {
        workload.warmup_activations = workload.warmup_activations.saturating_add(1);
    } else {
        workload.normal_measured_activations =
            workload.normal_measured_activations.saturating_add(1);
    }
    let scenario_count = workload
        .scenario_counts
        .entry(spec.scenario.to_owned())
        .or_default();
    *scenario_count = scenario_count.saturating_add(1);
    Ok(())
}

fn outcome_matches(expected: ExpectedOutcome, input: &str, outcome: &ActivationOutcome) -> bool {
    match (expected, outcome) {
        (ExpectedOutcome::Success, ActivationOutcome::Succeeded(success)) => {
            String::from_utf8_lossy(&success.output) == input
        }
        (ExpectedOutcome::DomainError, ActivationOutcome::DeclaredError { error, .. }) => {
            error.code == "empty-message"
        }
        (ExpectedOutcome::Trap, ActivationOutcome::Failed { error, .. }) => {
            error.code == PlatformErrorCode::GuestTrap
        }
        (ExpectedOutcome::Timeout, ActivationOutcome::Failed { error, .. }) => {
            error.code == PlatformErrorCode::DeadlineExceeded
        }
        (ExpectedOutcome::Cancelled, ActivationOutcome::Failed { error, .. }) => {
            error.code == PlatformErrorCode::Cancelled
        }
        (ExpectedOutcome::ResourceExhausted, ActivationOutcome::Failed { error, .. }) => {
            error.code == PlatformErrorCode::ResourceExhausted
        }
        _ => false,
    }
}

fn successful_output(outcome: &ActivationOutcome, expected: &str) -> bool {
    matches!(outcome, ActivationOutcome::Succeeded(success) if String::from_utf8_lossy(&success.output) == expected)
}

#[allow(clippy::too_many_arguments)]
fn resource_sample(
    phase: &str,
    batch_kind: &str,
    batch_index: u64,
    workload: &WorkloadCounters,
    pool: &Arc<FixedCellPool>,
    runner: &Arc<Phase0ActivationRunner>,
    backend: &Arc<Phase0WasmtimeBackend>,
    workers: &Phase0RuntimeWorkerMonitor,
    topology: &TopologyReference,
    cache_expectation: CacheExpectation,
    config: &EffectiveConfig,
    process_entry: Instant,
) -> Result<ResourceSample, SoakError> {
    let process = observe_process(process_entry)?;
    let pool_report = pool_report(&pool.observations());
    let runner_report = runner_report(&runner.snapshot());
    let backend_report = backend_resource_report(&backend.resource_snapshot());
    let cache_report = cache_report(&backend.cache_snapshot());
    let timing_snapshot = backend.invocation_timing_snapshot();
    let timing_report = TimingStoreReport {
        entries: timing_snapshot.entries,
        maximum_entries: timing_snapshot.maximum_entries,
    };
    let retained_log_entries_after_clear = backend.log_sink().snapshot().len();
    let observed_runtime_workers = workers.active_workers();
    let cache_clean = match cache_expectation {
        CacheExpectation::Prepared {
            entries,
            source_bytes,
        } => {
            cache_report.entries == entries
                && cache_report.source_bytes == source_bytes
                && cache_report.entries <= cache_report.maximum_entries
                && cache_report.source_bytes <= cache_report.maximum_source_bytes
        }
        CacheExpectation::Released => cache_report.entries == 0 && cache_report.source_bytes == 0,
    };
    let invariant_passed = process.process_count == topology.processes
        && process.child_process_count == topology.children
        && process.thread_count == topology.threads
        && process.open_socket_count == topology.open_sockets
        && process.listening_socket_count == topology.listeners
        && observed_runtime_workers == config.runtime_workers
        && pool_is_clean(&pool_report, config.pool_capacity)
        && runner_is_clean(&runner_report)
        && backend_resources_are_clean(&backend_report)
        && cache_clean
        && timing_report.entries == 0
        && retained_log_entries_after_clear == 0;
    if !invariant_passed {
        return Err(SoakError::new(format!(
            "logical resource or topology invariant failed after {phase}/{batch_kind} batch {batch_index}: processes={}, children={}, threads={}, sockets={}, listeners={}, workers={}, pool={:?}, runner={:?}, backend={:?}, cache={:?}, timings={}, logs={}",
            process.process_count,
            process.child_process_count,
            process.thread_count,
            process.open_socket_count,
            process.listening_socket_count,
            observed_runtime_workers,
            pool_report,
            runner_report,
            backend_report,
            cache_report,
            timing_report.entries,
            retained_log_entries_after_clear,
        )));
    }
    Ok(ResourceSample {
        phase: phase.to_owned(),
        batch_kind: batch_kind.to_owned(),
        batch_index,
        normal_measured_activations_completed: workload.normal_measured_activations,
        total_activation_count: workload
            .warmup_activations
            .saturating_add(workload.normal_measured_activations)
            .saturating_add(workload.saturation_activations),
        process,
        pool: pool_report,
        runner: runner_report,
        backend_resources: backend_report,
        prepared_cache: cache_report,
        backend_timing_store: timing_report,
        retained_log_entries_after_clear,
        observed_runtime_workers,
        invariant_passed,
    })
}

fn topology_reference(process: &ProcessSnapshot) -> TopologyReference {
    TopologyReference {
        processes: process.process_count,
        children: process.child_process_count,
        threads: process.thread_count,
        open_sockets: process.open_socket_count,
        listeners: process.listening_socket_count,
    }
}

fn pool_report(snapshot: &CellPoolSnapshot) -> PoolReport {
    PoolReport {
        capacity: snapshot.capacity,
        available: snapshot.available,
        queue_depth: snapshot.queue_depth,
        active_leases: snapshot.active_leases,
        quarantined: snapshot.quarantined,
    }
}

fn runner_report(snapshot: &latent_node::ActivationRunnerSnapshot) -> RunnerReport {
    RunnerReport {
        active_cancellation_registrations: snapshot.active_cancellation_registrations,
        running_invocations: snapshot.running_invocations,
        total_invocations: snapshot.total_invocations,
        released_cells: snapshot.released_cells,
        quarantined_cells: snapshot.quarantined_cells,
        disposition_failures: snapshot.disposition_failures,
    }
}

fn backend_resource_report(snapshot: &RuntimeResourceSnapshot) -> BackendResourceReport {
    BackendResourceReport {
        active_invocations: snapshot.active_invocations,
        live_stores: snapshot.live_stores,
        live_host_states: snapshot.live_host_states,
        live_component_instances: snapshot.live_component_instances,
        live_temporary_buffers: snapshot.live_temporary_buffers,
        live_cancellation_probes: snapshot.live_cancellation_probes,
        stores_created: snapshot.stores_created,
    }
}

fn cache_report(snapshot: &PreparedCacheSnapshot) -> CacheReport {
    CacheReport {
        entries: snapshot.entries,
        source_bytes: snapshot.source_bytes,
        maximum_entries: snapshot.maximum_entries,
        maximum_source_bytes: snapshot.maximum_source_bytes,
    }
}

fn pool_is_clean(snapshot: &PoolReport, capacity: u32) -> bool {
    snapshot.capacity == capacity
        && snapshot.available == capacity
        && snapshot.queue_depth == 0
        && snapshot.active_leases == 0
        && snapshot.quarantined == 0
}

fn runner_is_clean(snapshot: &RunnerReport) -> bool {
    snapshot.active_cancellation_registrations == 0
        && snapshot.running_invocations == 0
        && snapshot.quarantined_cells == 0
        && snapshot.disposition_failures == 0
}

fn backend_resources_are_clean(snapshot: &BackendResourceReport) -> bool {
    snapshot.active_invocations == 0
        && snapshot.live_stores == 0
        && snapshot.live_host_states == 0
        && snapshot.live_component_instances == 0
        && snapshot.live_temporary_buffers == 0
        && snapshot.live_cancellation_probes == 0
}

fn required_scenarios_present(counts: &BTreeMap<String, u64>) -> bool {
    [
        "success",
        "domain_error",
        "trap",
        "timeout",
        "cancellation",
        "memory_pressure",
        "recovery_after_domain_error",
        "recovery_after_trap",
        "recovery_after_timeout",
        "recovery_after_cancellation",
        "recovery_after_memory_pressure",
    ]
    .iter()
    .all(|name| counts.get(*name).copied().unwrap_or(0) > 0)
}

fn scenario_summary(counts: &BTreeMap<String, u64>) -> String {
    counts
        .iter()
        .map(|(name, count)| format!("{name}={count}"))
        .collect::<Vec<_>>()
        .join(", ")
}

fn saturation_summary(observations: &[SaturationObservation], mode: &str) -> String {
    let matching = observations
        .iter()
        .filter(|observation| observation.mode == mode)
        .collect::<Vec<_>>();
    let active = matching
        .iter()
        .map(|observation| observation.maximum_observed_active_leases)
        .min()
        .zip(
            matching
                .iter()
                .map(|observation| observation.maximum_observed_active_leases)
                .max(),
        );
    let queue = matching
        .iter()
        .map(|observation| observation.maximum_observed_queue_depth)
        .min()
        .zip(
            matching
                .iter()
                .map(|observation| observation.maximum_observed_queue_depth)
                .max(),
        );
    format!(
        "batches={}, active_range={:?}, queue_range={:?}",
        matching.len(),
        active,
        queue
    )
}

fn validate_native_linux() -> Result<NativeLinuxValidation, SoakError> {
    if std::env::consts::OS != "linux" {
        return Err(SoakError::new(
            "Phase 0 resource soak requires a native Linux host or VM",
        ));
    }
    let kernel_text = ["/proc/sys/kernel/osrelease", "/proc/version"]
        .iter()
        .filter_map(|path| fs::read_to_string(path).ok())
        .collect::<Vec<_>>()
        .join("\n")
        .to_lowercase();
    let wsl_detected = kernel_text.contains("microsoft") || kernel_text.contains("wsl");
    if wsl_detected {
        return Err(SoakError::new(
            "WSL cannot provide native-Linux Phase 0 resource-soak evidence",
        ));
    }
    let container = Command::new("systemd-detect-virt")
        .arg("--container")
        .output()
        .map_err(|error| {
            SoakError::new(format!(
                "native-Linux container probe systemd-detect-virt is unavailable: {error}"
            ))
        })?;
    let container_kind = String::from_utf8_lossy(&container.stdout).trim().to_owned();
    if container_kind != "none" {
        return Err(SoakError::new(format!(
            "native-Linux container probe did not establish a bare host or VM (status {}, value {:?})",
            container.status, container_kind
        )));
    }
    let virtualization = Command::new("systemd-detect-virt")
        .output()
        .map_err(|error| {
            SoakError::new(format!(
                "native-Linux virtualization probe systemd-detect-virt is unavailable: {error}"
            ))
        })?;
    let virtualization_kind = String::from_utf8_lossy(&virtualization.stdout)
        .trim()
        .to_owned();
    if virtualization_kind.is_empty() {
        return Err(SoakError::new(
            "native-Linux virtualization probe returned no identifiable host or VM kind",
        ));
    }
    let proc_probe_available = Path::new("/proc/self/status").is_file()
        && Path::new("/proc/self/fd").is_dir()
        && Path::new("/proc/self/task").is_dir()
        && Path::new("/proc/net/tcp").is_file()
        && Path::new("/proc/net/tcp6").is_file();
    if !proc_probe_available {
        return Err(SoakError::new(
            "required native-Linux /proc resource probes are unavailable",
        ));
    }
    Ok(NativeLinuxValidation {
        operating_system: "linux".to_owned(),
        wsl_detected,
        container_kind,
        virtualization_kind,
        proc_probe_available,
    })
}

fn observe_process(process_entry: Instant) -> Result<ProcessSnapshot, SoakError> {
    let status = fs::read_to_string("/proc/self/status").map_err(|error| {
        SoakError::new(format!("cannot read required /proc/self/status: {error}"))
    })?;
    let thread_count = parse_status_value(&status, "Threads:", 1)
        .ok_or_else(|| SoakError::new("/proc/self/status lacks Threads"))?;
    let rss_bytes = parse_status_value(&status, "VmRSS:", 1_024)
        .ok_or_else(|| SoakError::new("/proc/self/status lacks VmRSS"))?;
    let virtual_memory_bytes = parse_status_value(&status, "VmSize:", 1_024)
        .ok_or_else(|| SoakError::new("/proc/self/status lacks VmSize"))?;
    let mut socket_inodes = BTreeSet::new();
    let descriptors = fs::read_dir("/proc/self/fd")
        .map_err(|error| SoakError::new(format!("cannot read required /proc/self/fd: {error}")))?;
    let mut file_descriptor_count = 0_u64;
    for descriptor in descriptors {
        let descriptor = descriptor.map_err(|error| {
            SoakError::new(format!(
                "cannot enumerate /proc/self/fd descriptor: {error}"
            ))
        })?;
        file_descriptor_count = file_descriptor_count.saturating_add(1);
        if let Ok(target) = fs::read_link(descriptor.path()) {
            let target = target.to_string_lossy();
            if let Some(inode) = target
                .strip_prefix("socket:[")
                .and_then(|value| value.strip_suffix(']'))
            {
                socket_inodes.insert(inode.to_owned());
            }
        }
    }
    let child_path = format!("/proc/self/task/{}/children", std::process::id());
    let children = fs::read_to_string(&child_path)
        .map_err(|error| SoakError::new(format!("cannot read required {child_path}: {error}")))?;
    let child_process_count = u32::try_from(children.split_whitespace().count())
        .map_err(|_| SoakError::new("child process count does not fit u32"))?;
    let mut notes = vec![
        "listening_socket_count covers process-owned TCP/TCP6 LISTEN inodes; open_socket_count covers every process-owned socket descriptor".to_owned(),
    ];
    let (pss_bytes, private_bytes) = smaps_rollup(&mut notes);
    Ok(ProcessSnapshot {
        offset_micros: elapsed_micros(process_entry),
        process_count: 1_u32.saturating_add(child_process_count),
        child_process_count,
        thread_count,
        file_descriptor_count,
        open_socket_count: u64::try_from(socket_inodes.len()).unwrap_or(u64::MAX),
        listening_socket_count: count_listening_sockets(&socket_inodes)?,
        rss_bytes,
        virtual_memory_bytes,
        pss_bytes,
        private_bytes,
        probe_notes: notes,
    })
}

fn parse_status_value(status: &str, prefix: &str, multiplier: u64) -> Option<u64> {
    status.lines().find_map(|line| {
        let value = line.strip_prefix(prefix)?.split_whitespace().next()?;
        value
            .parse::<u64>()
            .ok()
            .map(|parsed| parsed.saturating_mul(multiplier))
    })
}

fn smaps_rollup(notes: &mut Vec<String>) -> (Option<u64>, Option<u64>) {
    let contents = match fs::read_to_string("/proc/self/smaps_rollup") {
        Ok(contents) => contents,
        Err(error) => {
            notes.push(format!("PSS/private probe unavailable: {error}"));
            return (None, None);
        }
    };
    let pss = parse_kib_field(&contents, "Pss:");
    let private_clean = parse_kib_field(&contents, "Private_Clean:").unwrap_or(0);
    let private_dirty = parse_kib_field(&contents, "Private_Dirty:").unwrap_or(0);
    let private_hugetlb = parse_kib_field(&contents, "Private_Hugetlb:").unwrap_or(0);
    if pss.is_none() {
        notes.push("PSS/private probe lacks Pss in /proc/self/smaps_rollup".to_owned());
    }
    (
        pss,
        Some(
            private_clean
                .saturating_add(private_dirty)
                .saturating_add(private_hugetlb),
        ),
    )
}

fn parse_kib_field(contents: &str, prefix: &str) -> Option<u64> {
    contents.lines().find_map(|line| {
        let value = line.strip_prefix(prefix)?.split_whitespace().next()?;
        value
            .parse::<u64>()
            .ok()
            .map(|kilobytes| kilobytes.saturating_mul(1_024))
    })
}

fn count_listening_sockets(socket_inodes: &BTreeSet<String>) -> Result<u64, SoakError> {
    let mut listening = BTreeSet::new();
    for path in ["/proc/net/tcp", "/proc/net/tcp6"] {
        let table = fs::read_to_string(path).map_err(|error| {
            SoakError::new(format!(
                "cannot read required listening-socket probe {path}: {error}"
            ))
        })?;
        for line in table.lines().skip(1) {
            let fields = line.split_whitespace().collect::<Vec<_>>();
            if fields.len() > 9 && fields[3] == "0A" && socket_inodes.contains(fields[9]) {
                listening.insert(fields[9].to_owned());
            }
        }
    }
    u64::try_from(listening.len())
        .map_err(|_| SoakError::new("listening socket count does not fit u64"))
}

fn environment_report(native_linux_validation: NativeLinuxValidation) -> EnvironmentReport {
    let rustc = command_output("rustc", &["-Vv"]);
    let rust_target = rustc
        .lines()
        .find_map(|line| line.strip_prefix("host: ").map(str::to_owned))
        .unwrap_or_else(|| "unknown".to_owned());
    EnvironmentReport {
        operating_system: std::env::consts::OS.to_owned(),
        architecture: std::env::consts::ARCH.to_owned(),
        kernel: command_output("uname", &["-srvmo"]),
        cpu_model: cpu_model(),
        logical_cpu_count: std::thread::available_parallelism().map_or(1, usize::from),
        total_memory_bytes: total_memory_bytes(),
        rustc,
        cargo: command_output("cargo", &["-V"]),
        rust_target,
        build_profile: if cfg!(debug_assertions) {
            "debug".to_owned()
        } else {
            "release".to_owned()
        },
        wasmtime_version: format!("{WASMTIME_WORKSPACE_PIN} (workspace pin)"),
        allocator_statistics: AllocatorStatistics {
            available: false,
            method: "not_collected".to_owned(),
            reason: "allocator-internal statistics are optional and no allocator-specific safe probe is configured".to_owned(),
        },
        native_linux_validation,
    }
}

fn command_output(program: &str, arguments: &[&str]) -> String {
    match Command::new(program).args(arguments).output() {
        Ok(output) if output.status.success() => {
            String::from_utf8_lossy(&output.stdout).trim().to_owned()
        }
        Ok(output) => format!("unavailable (exit {})", output.status),
        Err(error) => format!("unavailable ({error})"),
    }
}

fn cpu_model() -> String {
    fs::read_to_string("/proc/cpuinfo")
        .ok()
        .and_then(|contents| {
            contents.lines().find_map(|line| {
                line.strip_prefix("model name\t: ")
                    .or_else(|| line.strip_prefix("Hardware\t: "))
                    .map(str::to_owned)
            })
        })
        .unwrap_or_else(|| "unknown".to_owned())
}

fn total_memory_bytes() -> Option<u64> {
    fs::read_to_string("/proc/meminfo")
        .ok()
        .and_then(|contents| {
            contents.lines().find_map(|line| {
                let value = line.strip_prefix("MemTotal:")?.split_whitespace().next()?;
                value
                    .parse::<u64>()
                    .ok()
                    .map(|kilobytes| kilobytes.saturating_mul(1_024))
            })
        })
}

fn platform_error(error: PlatformError) -> SoakError {
    SoakError::new(format!(
        "{}: {}",
        platform_error_code_name(error.code),
        error.message
    ))
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

fn elapsed_micros(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX)
}

fn now_unix_millis() -> u64 {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis(),
    )
    .unwrap_or(u64::MAX)
}

fn valid_git_object_id(value: &str) -> bool {
    value.len() == 40
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn valid_published_source_ref(value: &str) -> bool {
    let prefix = if value.starts_with("refs/heads/") {
        "refs/heads/"
    } else if value.starts_with("refs/tags/") {
        "refs/tags/"
    } else {
        return false;
    };
    value.len() > prefix.len() && !value.chars().any(char::is_whitespace)
}

fn capsule_identity(capsule: &Path) -> Result<(String, String, u64), SoakError> {
    let manifest_path = if capsule.is_dir() {
        capsule.join("capsule.json")
    } else {
        capsule.to_path_buf()
    };
    let bytes = fs::read(&manifest_path).map_err(|error| {
        SoakError::new(format!(
            "failed to read capsule manifest for fixture identity ({}): {error}",
            manifest_path.display()
        ))
    })?;
    let byte_count = u64::try_from(bytes.len())
        .map_err(|_| SoakError::new("capsule manifest is too large to record"))?;
    if byte_count == 0 {
        return Err(SoakError::new(
            "capsule manifest is empty and cannot identify the measured fixture",
        ));
    }
    let digest = Sha256::digest(&bytes);
    Ok((
        manifest_path.display().to_string(),
        format!("sha256:{digest:x}"),
        byte_count,
    ))
}

fn write_document(path: &Path, document: &SoakDocument) -> Result<(), SoakError> {
    if let Some(parent) = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        fs::create_dir_all(parent)?;
    }
    let mut bytes = serde_json::to_vec_pretty(document)?;
    bytes.push(b'\n');
    fs::write(path, bytes)?;
    Ok(())
}
