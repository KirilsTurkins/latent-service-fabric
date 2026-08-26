#[derive(Debug, Clone, Copy, ValueEnum, Serialize)]
#[serde(rename_all = "snake_case")]
enum BenchmarkMode {
    Smoke,
    Full,
}

#[derive(Debug, Parser)]
#[command(
    name = "phase0-baseline",
    version,
    about = "Record observational Phase 0 activation and resource baselines"
)]
struct Cli {
    /// Staged containment capsule directory or capsule.json path.
    #[arg(long, value_name = "PATH")]
    capsule: PathBuf,

    /// Measurements collected by repeatedly launching the real issue-23 executable path.
    #[arg(long, value_name = "PATH")]
    executable_harness_probe: PathBuf,

    /// Parent-process wall-clock timestamp captured immediately before process launch.
    #[arg(long)]
    parent_launch_unix_micros: u64,

    /// Machine-readable raw result destination.
    #[arg(long, value_name = "PATH")]
    output_json: PathBuf,

    /// Concise Markdown baseline report destination.
    #[arg(long, value_name = "PATH")]
    output_report: PathBuf,

    /// Deterministic smoke profile or heavier local profile.
    #[arg(long, value_enum, default_value_t = BenchmarkMode::Full)]
    mode: BenchmarkMode,

    /// Fixed generic execution-cell capacity.
    #[arg(long, default_value_t = 2)]
    pool_capacity: u32,

    /// Bounded FIFO waiter capacity.
    #[arg(long, default_value_t = 4)]
    pool_queue_capacity: u32,

    /// Immutable Tokio worker count.
    #[arg(long, default_value_t = 2)]
    runtime_workers: usize,

    /// Warm echo sample count; profile default when omitted.
    #[arg(long)]
    warm_samples: Option<u32>,

    /// Mixed success/failure sequence repetitions; profile default when omitted.
    #[arg(long)]
    sequence_repetitions: Option<u32>,

    /// Concurrent activation-throughput batches per mode; profile default when omitted.
    #[arg(long)]
    throughput_batches: Option<u32>,

    /// Acquire/release iterations per fixed-pool worker; profile default when omitted.
    #[arg(long)]
    pool_iterations: Option<u32>,

    /// Per-activation Wasmtime fuel grant.
    #[arg(long, default_value_t = DEFAULT_FUEL)]
    fuel: u64,

    /// Normal activation linear-memory grant.
    #[arg(long, default_value_t = DEFAULT_MEMORY_BYTES)]
    memory_bytes: u64,

    /// Memory-pressure activation grant.
    #[arg(long, default_value_t = DEFAULT_MEMORY_PRESSURE_BYTES)]
    memory_pressure_bytes: u64,

    /// Infinite-guest timeout used for interruption and overshoot measurement.
    #[arg(long, default_value_t = DEFAULT_TIMEOUT_MILLIS)]
    timeout_ms: u64,

    /// Explicit cancellation delay.
    #[arg(long, default_value_t = DEFAULT_CANCELLATION_MILLIS)]
    cancel_after_ms: u64,

    /// Maximum accepted timeout/cancellation overshoot.
    #[arg(long, default_value_t = DEFAULT_MAXIMUM_TIMEOUT_OVERSHOOT_MILLIS)]
    maximum_overshoot_ms: u64,

    /// Allowed steady-state RSS range before fixed-capacity growth fails.
    #[arg(long, default_value_t = DEFAULT_RSS_GROWTH_ALLOWANCE_BYTES)]
    rss_growth_allowance_bytes: u64,

    /// Allowed steady-state file-descriptor range.
    #[arg(long, default_value_t = DEFAULT_FD_GROWTH_ALLOWANCE)]
    fd_growth_allowance: u64,
}

#[derive(Debug, Clone, Serialize)]
struct EffectiveConfig {
    mode: BenchmarkMode,
    pool_capacity: u32,
    pool_queue_capacity: u32,
    runtime_workers: usize,
    warm_samples: u32,
    sequence_repetitions: u32,
    throughput_batches: u32,
    pool_iterations: u32,
    fuel: u64,
    memory_bytes: u64,
    memory_pressure_bytes: u64,
    timeout_ms: u64,
    cancel_after_ms: u64,
    maximum_overshoot_ms: u64,
    rss_growth_allowance_bytes: u64,
    fd_growth_allowance: u64,
}

impl EffectiveConfig {
    fn from_cli(cli: &Cli) -> Result<Self, BenchError> {
        let (warm_samples, sequence_repetitions, throughput_batches, pool_iterations) =
            match cli.mode {
                BenchmarkMode::Smoke => (5, 2, 2, 32),
                BenchmarkMode::Full => (40, 10, 24, 2_000),
            };
        let config = Self {
            mode: cli.mode,
            pool_capacity: cli.pool_capacity,
            pool_queue_capacity: cli.pool_queue_capacity,
            runtime_workers: cli.runtime_workers,
            warm_samples: cli.warm_samples.unwrap_or(warm_samples),
            sequence_repetitions: cli
                .sequence_repetitions
                .unwrap_or(sequence_repetitions),
            throughput_batches: cli.throughput_batches.unwrap_or(throughput_batches),
            pool_iterations: cli.pool_iterations.unwrap_or(pool_iterations),
            fuel: cli.fuel,
            memory_bytes: cli.memory_bytes,
            memory_pressure_bytes: cli.memory_pressure_bytes,
            timeout_ms: cli.timeout_ms,
            cancel_after_ms: cli.cancel_after_ms,
            maximum_overshoot_ms: cli.maximum_overshoot_ms,
            rss_growth_allowance_bytes: cli.rss_growth_allowance_bytes,
            fd_growth_allowance: cli.fd_growth_allowance,
        };
        if config.pool_capacity == 0
            || config.pool_queue_capacity == 0
            || config.runtime_workers == 0
            || config.warm_samples == 0
            || config.sequence_repetitions == 0
            || config.throughput_batches == 0
            || config.pool_iterations == 0
            || config.fuel == 0
            || config.memory_bytes == 0
            || config.memory_pressure_bytes == 0
            || config.timeout_ms == 0
            || config.cancel_after_ms == 0
            || cli.parent_launch_unix_micros == 0
        {
            return Err(BenchError::new(
                "all capacities, counts, budgets, interruption delays, and launch timestamps must be non-zero",
            ));
        }
        Ok(config)
    }
}

#[derive(Debug)]
struct BenchError(String);

impl BenchError {
    fn new(message: impl Into<String>) -> Self {
        Self(message.into())
    }
}

impl fmt::Display for BenchError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl Error for BenchError {}

impl From<std::io::Error> for BenchError {
    fn from(error: std::io::Error) -> Self {
        Self(error.to_string())
    }
}

impl From<serde_json::Error> for BenchError {
    fn from(error: serde_json::Error) -> Self {
        Self(error.to_string())
    }
}

#[derive(Debug, Clone, Serialize)]
struct Distribution {
    samples: usize,
    minimum: u64,
    p50: u64,
    p95: u64,
    p99: u64,
    maximum: u64,
    mean: f64,
}

#[derive(Debug, Clone, Serialize)]
struct ProcessSnapshot {
    label: String,
    offset_micros: u64,
    probe_supported: bool,
    process_count: u32,
    child_process_count: Option<u32>,
    thread_count: Option<u64>,
    file_descriptor_count: Option<u64>,
    open_socket_count: Option<u64>,
    listening_socket_count: Option<u64>,
    rss_bytes: Option<u64>,
    virtual_memory_bytes: Option<u64>,
    notes: Vec<String>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct PoolSnapshotReport {
    capacity: u32,
    available: u32,
    queue_depth: u32,
    active_leases: u32,
    quarantined: u32,
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

#[derive(Debug, Clone, Serialize)]
struct CacheSnapshotReport {
    entries: usize,
    source_bytes: usize,
    maximum_entries: usize,
    maximum_source_bytes: usize,
}

#[derive(Debug, Clone, Serialize)]
struct RuntimeResourceReport {
    active_invocations: u64,
    live_stores: u64,
    live_host_states: u64,
    live_component_instances: u64,
    live_temporary_buffers: u64,
    live_cancellation_probes: u64,
    stores_created: u64,
}

#[derive(Debug, Clone, Serialize)]
struct ConsumptionReport {
    cpu_fuel: u64,
    peak_memory_bytes: u64,
    wall_time_micros: u64,
    log_bytes: u64,
}

#[derive(Debug, Clone, Serialize)]
struct OutcomeReport {
    name: String,
    error_code: Option<String>,
    output_utf8: Option<String>,
    consumption: ConsumptionReport,
}

#[derive(Debug, Clone, Default, Serialize)]
struct ActivationPhaseTimingReport {
    acquisition_queued: bool,
    acquire_or_queue_wait_micros: u64,
    /// Wasmtime's existing consumption observation, retained for continuity.
    contained_execution_micros: u64,
    /// Explicit backend boundaries recorded inside `Phase0WasmtimeBackend`.
    backend_setup_micros: u64,
    guest_call_micros: u64,
    host_call_micros: u64,
    host_call_count: u64,
    component_post_return_micros: u64,
    activation_resource_reclamation_micros: u64,
    outcome_classification_micros: u64,
    reusable_proof_micros: u64,
    backend_total_micros: u64,
    /// Legacy residual interval. It contains setup and host work and is not an
    /// authoritative cleanup measurement.
    backend_resource_cleanup_micros: u64,
    cell_disposition_micros: u64,
    /// Authoritative cleanup interval from the host-visible guest-call/
    /// canonical-post-return completion boundary through reusable-proof return
    /// and cell disposition.
    post_invocation_cleanup_micros: u64,
    total_invocation_micros: u64,
}

#[derive(Debug, Clone, Serialize)]
struct ActivationSample {
    scenario: String,
    iteration: u32,
    activation_id: String,
    elapsed_micros: u64,
    timeout_or_cancel_overshoot_micros: Option<u64>,
    expected_outcome: String,
    contract_result_valid: bool,
    outcome: OutcomeReport,
    phase_timings: ActivationPhaseTimingReport,
    pool_after: PoolSnapshotReport,
    runner_after: RunnerSnapshotReport,
    prepared_cache_after: CacheSnapshotReport,
    backend_resources_after: RuntimeResourceReport,
    retained_log_entries_after_clear: usize,
    observed_runtime_workers_after: usize,
    process_after: ProcessSnapshot,
}

#[derive(Debug, Clone, Serialize)]
struct TopologySnapshot {
    label: String,
    observed_runtime_workers: usize,
    process: ProcessSnapshot,
    pool: PoolSnapshotReport,
}

#[derive(Debug, Clone, Serialize)]
struct Check {
    name: String,
    passed: bool,
    expected: String,
    observed: String,
}

#[derive(Debug, Clone, Serialize)]
struct PoolProbeReport {
    acquire_micros: Distribution,
    release_micros: Distribution,
    queued_wait_micros: Distribution,
    overflow_rejected: bool,
    overflow_error_code: Option<String>,
    throughput_operations: u64,
    throughput_elapsed_micros: u64,
    throughput_operations_per_second: f64,
    maximum_observed_active_leases: u32,
    maximum_observed_queue_depth: u32,
    final_state: PoolSnapshotReport,
}

#[derive(Debug, Clone, Serialize)]
struct ThroughputModeReport {
    mode: String,
    activations: u64,
    elapsed_micros: u64,
    activations_per_second: f64,
    batch_micros: Distribution,
    activation_latency_micros: Distribution,
    acquire_wait_micros: Distribution,
    queued_acquire_wait_micros: Option<Distribution>,
    maximum_observed_active_leases: u32,
    maximum_observed_queue_depth: u32,
}

#[derive(Debug, Clone, Serialize)]
struct ActivationThroughputReport {
    at_capacity: ThroughputModeReport,
    bounded_queue_saturation: ThroughputModeReport,
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
    repository_commit: String,
}

#[derive(Debug, Clone, Serialize)]
struct ArtifactReport {
    capsule_path: String,
    component_path: String,
    component_digest: String,
    component_bytes: u64,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
struct ExecutableHarnessProbeSample {
    iteration: u32,
    launch_to_completion_micros: u64,
    activation_elapsed_micros: u64,
    runtime_workers: usize,
    pool_capacity: u32,
    listener_socket_count: u32,
    shutdown_clean: bool,
    topology_unchanged: bool,
    output_utf8: String,
    raw_result: Value,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
struct ExecutableHarnessFailureProbeSample {
    scenario: String,
    command: Vec<String>,
    expected_exit_code: i32,
    exit_code: i32,
    expected_outcome: String,
    raw_result: Value,
}

#[derive(Debug, Clone, Deserialize)]
struct ExecutableHarnessProbeDocument {
    schema_version: String,
    command: Vec<String>,
    samples: Vec<ExecutableHarnessProbeSample>,
    failure_recovery_samples: Vec<ExecutableHarnessFailureProbeSample>,
}

#[derive(Debug, Clone, Serialize)]
struct ExecutableHarnessProbeReport {
    schema_version: String,
    command: Vec<String>,
    samples: Vec<ExecutableHarnessProbeSample>,
    failure_recovery_samples: Vec<ExecutableHarnessFailureProbeSample>,
    process_launch_to_completion_micros: Distribution,
    cold_activation_micros: Distribution,
}

#[derive(Debug, Clone, Serialize)]
struct TimingReport {
    process_launch_to_runtime_ready_micros: u64,
    rust_entry_to_runtime_ready_micros: u64,
    capsule_validation_and_load_micros: u64,
    wasmtime_engine_construction_micros: u64,
    component_preparation_micros: u64,
    rust_entry_to_first_invocation_ready_micros: u64,
    prepared_component_release_micros: u64,
    distributions: BTreeMap<String, Distribution>,
}

#[derive(Debug, Serialize)]
struct BaselineDocument {
    schema_version: &'static str,
    generated_at_unix_millis: u64,
    status: String,
    observational_only: bool,
    production_ready: bool,
    phase1_api_compatible: bool,
    environment: EnvironmentReport,
    artifact: ArtifactReport,
    config: EffectiveConfig,
    executable_harness: ExecutableHarnessProbeReport,
    timings: TimingReport,
    pool_probe: PoolProbeReport,
    activation_throughput: ActivationThroughputReport,
    activation_samples: Vec<ActivationSample>,
    process_snapshots: Vec<ProcessSnapshot>,
    topology_snapshots: Vec<TopologySnapshot>,
    checks: Vec<Check>,
    limitations: Vec<String>,
    conclusions: Vec<String>,
}

#[derive(Debug, Clone, Copy)]
enum ExpectedOutcome {
    Success,
    DomainError,
    Trap,
    Timeout,
    Cancelled,
    ResourceExhausted,
}

impl ExpectedOutcome {
    fn name(self) -> &'static str {
        match self {
            Self::Success => "success",
            Self::DomainError => "domain_error",
            Self::Trap => "trap",
            Self::Timeout => "timeout",
            Self::Cancelled => "cancelled",
            Self::ResourceExhausted => "resource_exhausted",
        }
    }
}

struct InvocationRequest<'a> {
    scenario: &'a str,
    iteration: u32,
    input: &'a str,
    expected: ExpectedOutcome,
    memory_bytes: u64,
    fuel: u64,
    timeout_ms: u64,
    cancel_after_ms: Option<u64>,
}

struct AsyncRunResult {
    artifact: ArtifactReport,
    executable_harness: ExecutableHarnessProbeReport,
    validation_micros: u64,
    engine_micros: u64,
    preparation_micros: u64,
    first_invocation_ready_micros: u64,
    prepared_release_micros: u64,
    pool_probe: PoolProbeReport,
    activation_throughput: ActivationThroughputReport,
    activation_samples: Vec<ActivationSample>,
    process_snapshots: Vec<ProcessSnapshot>,
    topology_snapshots: Vec<TopologySnapshot>,
    checks: Vec<Check>,
    distributions: BTreeMap<String, Distribution>,
}

type RuntimeWorkerMonitor = Phase0RuntimeWorkerMonitor;

fn main() -> ExitCode {
    let process_entry = Instant::now();
    let cli = Cli::parse();
    match run(cli, process_entry) {
        Ok(true) => ExitCode::SUCCESS,
        Ok(false) => ExitCode::from(1),
        Err(error) => {
            eprintln!("Phase 0 baseline failed before producing a complete report: {error}");
            ExitCode::from(2)
        }
    }
}
