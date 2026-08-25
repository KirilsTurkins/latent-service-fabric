fn pool_snapshot(snapshot: &CellPoolSnapshot) -> PoolSnapshotReport {
    PoolSnapshotReport {
        capacity: snapshot.capacity,
        available: snapshot.available,
        queue_depth: snapshot.queue_depth,
        active_leases: snapshot.active_leases,
        quarantined: snapshot.quarantined,
    }
}

fn runner_snapshot(snapshot: &ActivationRunnerSnapshot) -> RunnerSnapshotReport {
    RunnerSnapshotReport {
        active_cancellation_registrations: snapshot.active_cancellation_registrations,
        running_invocations: snapshot.running_invocations,
        total_invocations: snapshot.total_invocations,
        released_cells: snapshot.released_cells,
        quarantined_cells: snapshot.quarantined_cells,
        disposition_failures: snapshot.disposition_failures,
    }
}

fn cache_snapshot(snapshot: &PreparedCacheSnapshot) -> CacheSnapshotReport {
    CacheSnapshotReport {
        entries: snapshot.entries,
        source_bytes: snapshot.source_bytes,
        maximum_entries: snapshot.maximum_entries,
        maximum_source_bytes: snapshot.maximum_source_bytes,
    }
}

fn runtime_resources(snapshot: &RuntimeResourceSnapshot) -> RuntimeResourceReport {
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

fn pool_is_clean(snapshot: &PoolSnapshotReport, expected_capacity: u32) -> bool {
    snapshot.capacity == expected_capacity
        && snapshot.available == expected_capacity
        && snapshot.queue_depth == 0
        && snapshot.active_leases == 0
        && snapshot.quarantined == 0
}

fn resources_are_reclaimed(resources: &RuntimeResourceReport) -> bool {
    resources.active_invocations == 0
        && resources.live_stores == 0
        && resources.live_host_states == 0
        && resources.live_component_instances == 0
        && resources.live_temporary_buffers == 0
        && resources.live_cancellation_probes == 0
}

fn expected_outcome_for_scenario(scenario: &str) -> Option<&'static str> {
    match scenario {
        "cold_echo" | "warm_echo" | "sequence_echo" | "recovery_echo" | "throughput_echo" => {
            Some("success")
        }
        "domain_error" => Some("domain_error"),
        "trap" => Some("trap"),
        "timeout" => Some("timeout"),
        "cancellation" => Some("cancelled"),
        "memory_pressure" => Some("resource_exhausted"),
        _ => None,
    }
}

fn failure_recovery_is_healthy(samples: &[ActivationSample]) -> bool {
    let failure_scenarios = [
        "domain_error",
        "trap",
        "timeout",
        "cancellation",
        "memory_pressure",
    ];
    for (index, sample) in samples.iter().enumerate() {
        if failure_scenarios.contains(&sample.scenario.as_str()) {
            let Some(next) = samples.get(index.saturating_add(1)) else {
                return false;
            };
            if next.scenario != "recovery_echo"
                || next.outcome.name != "success"
                || !next.contract_result_valid
            {
                return false;
            }
        }
    }
    true
}

fn outcome_summary(samples: &[ActivationSample]) -> String {
    let mut counts = BTreeMap::<String, usize>::new();
    for sample in samples {
        *counts.entry(sample.outcome.name.clone()).or_default() += 1;
    }
    counts
        .into_iter()
        .map(|(name, count)| format!("{name}={count}"))
        .collect::<Vec<_>>()
        .join(", ")
}

fn scenario_values<F>(samples: &[ActivationSample], scenario: &str, value: F) -> Vec<u64>
where
    F: Fn(&ActivationSample) -> u64,
{
    samples
        .iter()
        .filter(|sample| sample.scenario == scenario)
        .map(value)
        .collect()
}

fn insert_scenario_distribution(
    distributions: &mut BTreeMap<String, Distribution>,
    samples: &[ActivationSample],
    scenario: &str,
) {
    let values = scenario_values(samples, scenario, |sample| sample.elapsed_micros);
    if let Some(distribution) = distribution(&values) {
        distributions.insert(format!("{scenario}_elapsed_micros"), distribution);
    }
}

fn distribution(values: &[u64]) -> Option<Distribution> {
    if values.is_empty() {
        return None;
    }
    let mut sorted = values.to_vec();
    sorted.sort_unstable();
    let sum = sorted
        .iter()
        .fold(0_u128, |accumulator, value| accumulator + u128::from(*value));
    Some(Distribution {
        samples: sorted.len(),
        minimum: sorted[0],
        p50: percentile(&sorted, 50),
        p95: percentile(&sorted, 95),
        p99: percentile(&sorted, 99),
        maximum: *sorted.last().unwrap_or(&sorted[0]),
        mean: sum as f64 / sorted.len() as f64,
    })
}

fn percentile(sorted: &[u64], percentage: usize) -> u64 {
    let rank = percentage
        .saturating_mul(sorted.len())
        .saturating_add(99)
        / 100;
    sorted[rank.saturating_sub(1).min(sorted.len().saturating_sub(1))]
}

fn rate_per_second(operations: u64, elapsed_micros: u64) -> f64 {
    if elapsed_micros == 0 {
        return 0.0;
    }
    operations as f64 * 1_000_000.0 / elapsed_micros as f64
}

struct GrowthAnalysis {
    passed: bool,
    description: String,
}

fn bounded_growth(values: &[u64], allowance: u64) -> GrowthAnalysis {
    if values.is_empty() {
        return GrowthAnalysis {
            passed: false,
            description: "probe unsupported or no samples".to_owned(),
        };
    }
    let minimum = values.iter().copied().min().unwrap_or(0);
    let maximum = values.iter().copied().max().unwrap_or(0);
    let range = maximum.saturating_sub(minimum);
    let first = values[0];
    let last = *values.last().unwrap_or(&first);
    let net_growth = last.saturating_sub(first);
    let monotonic = values.windows(2).all(|pair| pair[1] >= pair[0]);
    GrowthAnalysis {
        passed: range <= allowance && net_growth <= allowance,
        description: format!(
            "samples={}, min={minimum}, max={maximum}, range={range}, first={first}, last={last}, net_growth={net_growth}, monotonic_non_decreasing={monotonic}, allowance={allowance}",
            values.len()
        ),
    }
}

fn topology_range(snapshots: &[ProcessSnapshot]) -> String {
    fn range(values: impl Iterator<Item = u64>) -> String {
        let values = values.collect::<Vec<_>>();
        match (
            values.iter().copied().min(),
            values.iter().copied().max(),
        ) {
            (Some(minimum), Some(maximum)) => format!("{minimum}..{maximum}"),
            _ => "unsupported".to_owned(),
        }
    }
    format!(
        "processes={}, threads={}, open_sockets={}, listeners={}",
        range(snapshots.iter().map(|snapshot| u64::from(snapshot.process_count))),
        range(snapshots.iter().filter_map(|snapshot| snapshot.thread_count)),
        range(
            snapshots
                .iter()
                .filter_map(|snapshot| snapshot.open_socket_count)
        ),
        range(
            snapshots
                .iter()
                .filter_map(|snapshot| snapshot.listening_socket_count)
        )
    )
}

fn elapsed_micros(started: Instant) -> u64 {
    duration_micros(started.elapsed())
}

fn duration_micros(duration: Duration) -> u64 {
    u64::try_from(duration.as_micros()).unwrap_or(u64::MAX)
}

fn now_unix_millis() -> u64 {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    u64::try_from(millis).unwrap_or(u64::MAX)
}

fn platform_error(error: PlatformError) -> BenchError {
    BenchError::new(format!(
        "{}: {}",
        platform_error_code_name(error.code),
        error.message
    ))
}

#[cfg(target_os = "linux")]
fn observe_process(label: &str, process_entry: Instant) -> ProcessSnapshot {
    let mut notes = vec![
        "listening_socket_count covers process-owned TCP/TCP6 LISTEN inodes; open_socket_count covers every process-owned socket descriptor".to_owned(),
    ];
    let status = fs::read_to_string("/proc/self/status");
    let (thread_count, rss_bytes, virtual_memory_bytes) = match status {
        Ok(status) => (
            parse_status_value(&status, "Threads:", 1),
            parse_status_value(&status, "VmRSS:", 1_024),
            parse_status_value(&status, "VmSize:", 1_024),
        ),
        Err(error) => {
            notes.push(format!("failed to read /proc/self/status: {error}"));
            (None, None, None)
        }
    };

    let mut file_descriptor_count = None;
    let mut socket_inodes = BTreeSet::new();
    match fs::read_dir("/proc/self/fd") {
        Ok(descriptors) => {
            let mut count = 0_u64;
            for descriptor in descriptors.flatten() {
                count = count.saturating_add(1);
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
            file_descriptor_count = Some(count);
        }
        Err(error) => notes.push(format!("failed to read /proc/self/fd: {error}")),
    }
    let open_socket_count = u64::try_from(socket_inodes.len()).ok();
    let listening_socket_count = Some(count_listening_sockets(&socket_inodes, &mut notes));

    let child_process_count = read_child_process_count(&mut notes);
    let process_count = child_process_count
        .and_then(|count| u32::try_from(count).ok())
        .map_or(1, |children| 1_u32.saturating_add(children));
    let probe_supported = thread_count.is_some()
        && rss_bytes.is_some()
        && virtual_memory_bytes.is_some()
        && file_descriptor_count.is_some()
        && open_socket_count.is_some()
        && child_process_count.is_some();

    ProcessSnapshot {
        label: label.to_owned(),
        offset_micros: elapsed_micros(process_entry),
        probe_supported,
        process_count,
        child_process_count,
        thread_count,
        file_descriptor_count,
        open_socket_count,
        listening_socket_count,
        rss_bytes,
        virtual_memory_bytes,
        notes,
    }
}

#[cfg(target_os = "linux")]
fn parse_status_value(status: &str, prefix: &str, multiplier: u64) -> Option<u64> {
    status.lines().find_map(|line| {
        let value = line.strip_prefix(prefix)?.split_whitespace().next()?;
        value
            .parse::<u64>()
            .ok()
            .map(|parsed| parsed.saturating_mul(multiplier))
    })
}

#[cfg(target_os = "linux")]
fn read_child_process_count(notes: &mut Vec<String>) -> Option<u32> {
    let children_path = format!("/proc/self/task/{}/children", std::process::id());
    match fs::read_to_string(children_path) {
        Ok(children) => u32::try_from(children.split_whitespace().count()).ok(),
        Err(error) => {
            notes.push(format!("failed to read process children: {error}"));
            None
        }
    }
}

#[cfg(target_os = "linux")]
fn count_listening_sockets(
    process_socket_inodes: &BTreeSet<String>,
    notes: &mut Vec<String>,
) -> u64 {
    let mut listening = BTreeSet::new();
    for path in ["/proc/net/tcp", "/proc/net/tcp6"] {
        match fs::read_to_string(path) {
            Ok(table) => {
                for line in table.lines().skip(1) {
                    let fields = line.split_whitespace().collect::<Vec<_>>();
                    if fields.len() > 9
                        && fields[3] == "0A"
                        && process_socket_inodes.contains(fields[9])
                    {
                        listening.insert(fields[9].to_owned());
                    }
                }
            }
            Err(error) => notes.push(format!("failed to read {path}: {error}")),
        }
    }
    u64::try_from(listening.len()).unwrap_or(u64::MAX)
}

#[cfg(not(target_os = "linux"))]
fn observe_process(label: &str, process_entry: Instant) -> ProcessSnapshot {
    ProcessSnapshot {
        label: label.to_owned(),
        offset_micros: elapsed_micros(process_entry),
        probe_supported: false,
        process_count: 1,
        child_process_count: None,
        thread_count: None,
        file_descriptor_count: None,
        open_socket_count: None,
        listening_socket_count: None,
        rss_bytes: None,
        virtual_memory_bytes: None,
        notes: vec![
            "strict process resource probes are implemented for Linux /proc only".to_owned(),
        ],
    }
}

fn environment_report() -> EnvironmentReport {
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
        repository_commit: std::env::var("GITHUB_SHA")
            .ok()
            .filter(|value| !value.trim().is_empty())
            .unwrap_or_else(|| command_output("git", &["rev-parse", "HEAD"])),
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

#[cfg(target_os = "linux")]
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

#[cfg(not(target_os = "linux"))]
fn cpu_model() -> String {
    "unknown".to_owned()
}

#[cfg(target_os = "linux")]
fn total_memory_bytes() -> Option<u64> {
    let contents = fs::read_to_string("/proc/meminfo").ok()?;
    parse_status_value(&contents, "MemTotal:", 1_024)
}

#[cfg(not(target_os = "linux"))]
fn total_memory_bytes() -> Option<u64> {
    None
}
