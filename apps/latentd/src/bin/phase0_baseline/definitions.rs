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

    /// Concurrent activation-throughput batches; profile default when omitted.
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
                BenchmarkMode::Smoke => (3, 1, 2, 16),
                BenchmarkMode::Full => (30, 8, 20, 1_000),
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
        {
            return Err(BenchError::new(
                "all capacities, counts, budgets, and interruption delays must be non-zero",
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

#[derive(Debug, Clone, Serialize)]
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
    pool_after: PoolSnapshotReport,
    runner_after: RunnerSnapshotReport,
    prepared_cache_after: CacheSnapshotReport,
    backend_resources_after: RuntimeResourceReport,
    retained_log_entries_after_clear: usize,
    process_after: ProcessSnapshot,
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
    final_state: PoolSnapshotReport,
}

#[derive(Debug, Clone, Serialize)]
struct ActivationThroughputReport {
    activations: u64,
    elapsed_micros: u64,
    activations_per_second: f64,
    batch_micros: Distribution,
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

#[derive(Debug, Clone, Serialize)]
struct TimingReport {
    process_entry_to_runtime_ready_micros: u64,
    capsule_validation_and_load_micros: u64,
    wasmtime_engine_construction_micros: u64,
    component_preparation_micros: u64,
    process_entry_to_first_invocation_ready_micros: u64,
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
    timings: TimingReport,
    pool_probe: PoolProbeReport,
    activation_throughput: ActivationThroughputReport,
    activation_samples: Vec<ActivationSample>,
    process_snapshots: Vec<ProcessSnapshot>,
    checks: Vec<Check>,
    limitations: Vec<String>,
    conclusions: Vec<String>,
}

#[derive(Debug)]
struct LoadedArtifact {
    artifact: CapsuleArtifact,
    component_path: PathBuf,
    component_bytes: u64,
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
    validation_micros: u64,
    engine_micros: u64,
    preparation_micros: u64,
    first_invocation_ready_micros: u64,
    pool_probe: PoolProbeReport,
    activation_throughput: ActivationThroughputReport,
    activation_samples: Vec<ActivationSample>,
    process_snapshots: Vec<ProcessSnapshot>,
    checks: Vec<Check>,
    distributions: BTreeMap<String, Distribution>,
}

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

fn run(cli: Cli, process_entry: Instant) -> Result<bool, BenchError> {
    let config = EffectiveConfig::from_cli(&cli)?;
    let initial_snapshot = observe_process("process_entry", process_entry);

    let runtime = Builder::new_multi_thread()
        .worker_threads(config.runtime_workers)
        .thread_name("phase0-baseline-worker")
        .enable_time()
        .build()
        .map_err(|error| BenchError::new(format!("failed to build Tokio runtime: {error}")))?;
    let pool = Arc::new(
        FixedCellPool::new(FixedCellPoolConfig::new(
            NodeId(NODE_ID.to_owned()),
            CellClass::Standard,
            config.pool_capacity,
            config.pool_queue_capacity,
        ))
        .map_err(platform_error)?,
    );
    runtime.block_on(async {
        let mut readiness_tasks = Vec::new();
        for _ in 0..config.runtime_workers {
            readiness_tasks.push(tokio::spawn(async { tokio::task::yield_now().await }));
        }
        for task in readiness_tasks {
            let _ = task.await;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    });
    let runtime_ready_micros = elapsed_micros(process_entry);
    let runtime_ready_snapshot = observe_process("runtime_and_pool_ready", process_entry);

    let mut result = runtime.block_on(run_async(
        &cli,
        &config,
        Arc::clone(&pool),
        process_entry,
    ))?;
    result.process_snapshots.insert(0, runtime_ready_snapshot);
    result.process_snapshots.insert(0, initial_snapshot.clone());

    drop(pool);
    drop(runtime);
    std::thread::sleep(Duration::from_millis(25));
    let final_snapshot = observe_process("runtime_stopped", process_entry);
    let final_thread_pass = match (initial_snapshot.thread_count, final_snapshot.thread_count) {
        (Some(initial), Some(final_count)) => final_count <= initial.saturating_add(1),
        _ => false,
    };
    result.checks.push(Check {
        name: "runtime_shutdown_returns_thread_count_to_process_baseline".to_owned(),
        passed: final_thread_pass,
        expected: format!("at most {} threads", initial_snapshot.thread_count.unwrap_or(0) + 1),
        observed: final_snapshot
            .thread_count
            .map_or_else(|| "unsupported".to_owned(), |value| value.to_string()),
    });
    result.process_snapshots.push(final_snapshot);

    let environment = environment_report();
    let all_passed = result.checks.iter().all(|check| check.passed);
    let status = if all_passed { "pass" } else { "fail" }.to_owned();
    let limitations = vec![
        "Measurements are observations from one finite local process and are not production SLOs, capacity guarantees, or competitive claims.".to_owned(),
        "Wall-clock distributions include host scheduling noise; compare like-for-like hardware, kernel, toolchain, target, profile, and runtime configuration.".to_owned(),
        "RSS allocators and Wasmtime may retain bounded arenas after first use; the invariant checks bounded range and monotonic growth after warm-up rather than requiring byte-for-byte return.".to_owned(),
        "Linux /proc supplies RSS, virtual memory, thread, descriptor, and socket probes. Other operating systems are reported unsupported and fail the strict checked-in smoke baseline.".to_owned(),
        "Component preparation is measured in-process after capsule validation and before the first activation; process-loader time before Rust main is not observable here.".to_owned(),
    ];
    let conclusions = if all_passed {
        vec![
            "All configured fixed-capacity and bounded-growth invariants passed for this sample window.".to_owned(),
            "Trap, timeout, cancellation, domain error, and memory-pressure samples did not prevent the immediately following echo from succeeding.".to_owned(),
            "The prepared cache remained bounded while active and returned to zero after explicit release.".to_owned(),
        ]
    } else {
        vec![
            "At least one configured invariant failed; inspect the raw checks and samples before using this run as a comparison baseline.".to_owned(),
        ]
    };

    let document = BaselineDocument {
        schema_version: SCHEMA_VERSION,
        generated_at_unix_millis: now_unix_millis(),
        status,
        observational_only: true,
        production_ready: false,
        phase1_api_compatible: false,
        environment,
        artifact: result.artifact,
        config: config.clone(),
        timings: TimingReport {
            process_entry_to_runtime_ready_micros: runtime_ready_micros,
            capsule_validation_and_load_micros: result.validation_micros,
            wasmtime_engine_construction_micros: result.engine_micros,
            component_preparation_micros: result.preparation_micros,
            process_entry_to_first_invocation_ready_micros: result.first_invocation_ready_micros,
            distributions: result.distributions,
        },
        pool_probe: result.pool_probe,
        activation_throughput: result.activation_throughput,
        activation_samples: result.activation_samples,
        process_snapshots: result.process_snapshots,
        checks: result.checks,
        limitations,
        conclusions,
    };

    write_outputs(&cli.output_json, &cli.output_report, &document)?;
    println!(
        "{}",
        serde_json::to_string(&json!({
            "schema_version": SCHEMA_VERSION,
            "status": document.status,
            "raw_results": cli.output_json,
            "report": cli.output_report,
        }))?
    );
    Ok(all_passed)
}
