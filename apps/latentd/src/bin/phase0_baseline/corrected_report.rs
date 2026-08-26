fn write_outputs(
    json_path: &Path,
    report_path: &Path,
    document: &BaselineDocument,
) -> Result<(), BenchError> {
    ensure_parent(json_path)?;
    ensure_parent(report_path)?;
    let mut raw = serde_json::to_vec_pretty(document)?;
    raw.push(b'\n');
    fs::write(json_path, raw)?;
    fs::write(report_path, render_report(document, json_path))?;
    Ok(())
}

fn ensure_parent(path: &Path) -> Result<(), BenchError> {
    if let Some(parent) = path.parent().filter(|parent| !parent.as_os_str().is_empty()) {
        fs::create_dir_all(parent)?;
    }
    Ok(())
}

fn render_report(document: &BaselineDocument, raw_path: &Path) -> String {
    let mut report = String::new();
    let passed = document.status == "pass";
    let _ = writeln!(report, "# Phase 0 activation and resource baseline\n");
    let _ = writeln!(
        report,
        "**Status:** {}  ",
        if passed { "PASS" } else { "FAIL" }
    );
    let _ = writeln!(report, "**Schema:** `{}`  ", document.schema_version);
    let _ = writeln!(
        report,
        "**Generated:** Unix epoch {} ms  ",
        document.generated_at_unix_millis
    );
    let _ = writeln!(report, "**Raw results:** `{}`\n", raw_path.display());
    let _ = writeln!(
        report,
        "> Observational Phase 0 evidence only. These values are not production SLOs, scaling commitments, or competitive claims.\n"
    );

    let _ = writeln!(report, "## Environment\n");
    let _ = writeln!(report, "| Field | Value |");
    let _ = writeln!(report, "|---|---|");
    report_row(&mut report, "OS", &document.environment.operating_system);
    report_row(&mut report, "Architecture", &document.environment.architecture);
    report_row(&mut report, "Kernel", &document.environment.kernel);
    report_row(&mut report, "CPU", &document.environment.cpu_model);
    report_row(
        &mut report,
        "Logical CPUs",
        &document.environment.logical_cpu_count.to_string(),
    );
    report_row(
        &mut report,
        "Memory",
        &document
            .environment
            .total_memory_bytes
            .map_or_else(|| "unsupported".to_owned(), format_bytes),
    );
    report_row(&mut report, "Rust", &document.environment.rustc);
    report_row(&mut report, "Cargo", &document.environment.cargo);
    report_row(&mut report, "Target", &document.environment.rust_target);
    report_row(
        &mut report,
        "Build profile",
        &document.environment.build_profile,
    );
    report_row(
        &mut report,
        "Wasmtime",
        &document.environment.wasmtime_version,
    );
    report_row(
        &mut report,
        "Repository commit",
        &document.environment.repository_commit,
    );
    report.push('\n');

    let _ = writeln!(report, "## Runtime configuration and pass/fail thresholds\n");
    let _ = writeln!(report, "| Field | Value |");
    let _ = writeln!(report, "|---|---:|");
    report_row(&mut report, "Mode", &format!("{:?}", document.config.mode));
    report_row(
        &mut report,
        "Independent issue-23 cold samples",
        &document.executable_harness.samples.len().to_string(),
    );
    report_row(
        &mut report,
        "Warm echo samples",
        &document.config.warm_samples.to_string(),
    );
    report_row(
        &mut report,
        "Mixed-sequence repetitions",
        &document.config.sequence_repetitions.to_string(),
    );
    report_row(
        &mut report,
        "Throughput batches per mode",
        &document.config.throughput_batches.to_string(),
    );
    report_row(
        &mut report,
        "Pool iterations per worker",
        &document.config.pool_iterations.to_string(),
    );
    report_row(
        &mut report,
        "Runtime workers",
        &document.config.runtime_workers.to_string(),
    );
    report_row(
        &mut report,
        "Pool capacity",
        &document.config.pool_capacity.to_string(),
    );
    report_row(
        &mut report,
        "Pool queue capacity",
        &document.config.pool_queue_capacity.to_string(),
    );
    report_row(&mut report, "Fuel grant", &document.config.fuel.to_string());
    report_row(
        &mut report,
        "Memory grant",
        &format_bytes(document.config.memory_bytes),
    );
    report_row(
        &mut report,
        "Memory-pressure grant",
        &format_bytes(document.config.memory_pressure_bytes),
    );
    report_row(
        &mut report,
        "Timeout",
        &format!("{} ms", document.config.timeout_ms),
    );
    report_row(
        &mut report,
        "Cancellation delay",
        &format!("{} ms", document.config.cancel_after_ms),
    );
    report_row(
        &mut report,
        "Maximum interruption overshoot",
        &format!("{} ms", document.config.maximum_overshoot_ms),
    );
    report_row(
        &mut report,
        "RSS growth allowance",
        &format_bytes(document.config.rss_growth_allowance_bytes),
    );
    report_row(
        &mut report,
        "File-descriptor growth allowance",
        &document.config.fd_growth_allowance.to_string(),
    );
    report.push('\n');

    let _ = writeln!(report, "## Exact issue-23 executable probe\n");
    let _ = writeln!(
        report,
        "Cold samples come from fresh launches of the real `latentd phase0-spike invoke-once` command. The same checked executable probe also retains trap, timeout, and same-composition post-trap recovery documents; all use the shared Phase 0 composition API.\n"
    );
    report_distribution_row_header(&mut report);
    report_distribution_row(
        &mut report,
        "Process launch to completion",
        &document
            .executable_harness
            .process_launch_to_completion_micros,
    );
    report_distribution_row(
        &mut report,
        "Cold activation inside issue-23 harness",
        &document.executable_harness.cold_activation_micros,
    );
    let _ = writeln!(
        report,
        "Exact failure/recovery probes retained: {}.\n",
        document.executable_harness.failure_recovery_samples.len()
    );

    let _ = writeln!(report, "## Startup and preparation\n");
    let _ = writeln!(report, "| Metric | Microseconds |");
    let _ = writeln!(report, "|---|---:|");
    report_row(
        &mut report,
        "External process launch to runtime/pool ready",
        &document
            .timings
            .process_launch_to_runtime_ready_micros
            .to_string(),
    );
    report_row(
        &mut report,
        "Rust entry to observed worker/pool readiness",
        &document
            .timings
            .rust_entry_to_runtime_ready_micros
            .to_string(),
    );
    report_row(
        &mut report,
        "Capsule validation and component load",
        &document
            .timings
            .capsule_validation_and_load_micros
            .to_string(),
    );
    report_row(
        &mut report,
        "Wasmtime engine/backend construction",
        &document
            .timings
            .wasmtime_engine_construction_micros
            .to_string(),
    );
    report_row(
        &mut report,
        "Component preparation",
        &document.timings.component_preparation_micros.to_string(),
    );
    report_row(
        &mut report,
        "Rust entry to retained invocation readiness",
        &document
            .timings
            .rust_entry_to_first_invocation_ready_micros
            .to_string(),
    );
    report_row(
        &mut report,
        "Prepared-component release",
        &document
            .timings
            .prepared_component_release_micros
            .to_string(),
    );
    report.push('\n');

    let _ = writeln!(report, "## Activation and cleanup distributions\n");
    let _ = writeln!(
        report,
        "Percentiles use nearest-rank ordering over the raw samples. The typed guest-call interval includes Wasmtime's automatic canonical post-return; backend boundaries then separately record setup, in-guest host imports, host-visible post-call result accounting, activation-resource reclamation, outcome classification, reusable-proof return, and cell disposition. `post_invocation_cleanup_micros` is the authoritative sum after the host-visible guest-call completion boundary; `backend_resource_cleanup_micros` is retained only as a residual interval.\n"
    );
    report_distribution_row_header(&mut report);
    for (name, distribution) in &document.timings.distributions {
        report_distribution_row(&mut report, name, distribution);
    }
    report.push('\n');

    let _ = writeln!(report, "## Fixed-pool and activation throughput\n");
    let _ = writeln!(report, "| Metric | At capacity | Bounded queue saturation |");
    let _ = writeln!(report, "|---|---:|---:|");
    let capacity = &document.activation_throughput.at_capacity;
    let saturated = &document.activation_throughput.bounded_queue_saturation;
    let _ = writeln!(
        report,
        "| Activations | {} | {} |",
        capacity.activations, saturated.activations
    );
    let _ = writeln!(
        report,
        "| Activations/second | {:.1} | {:.1} |",
        capacity.activations_per_second, saturated.activations_per_second
    );
    let _ = writeln!(
        report,
        "| Maximum active leases | {} | {} |",
        capacity.maximum_observed_active_leases,
        saturated.maximum_observed_active_leases
    );
    let _ = writeln!(
        report,
        "| Maximum queue depth | {} | {} |",
        capacity.maximum_observed_queue_depth,
        saturated.maximum_observed_queue_depth
    );
    let _ = writeln!(
        report,
        "| Acquire-wait P95 (us) | {} | {} |",
        capacity.acquire_wait_micros.p95,
        saturated.acquire_wait_micros.p95
    );
    let _ = writeln!(
        report,
        "| Queued acquire-wait P95 (us) | n/a | {} |",
        saturated
            .queued_acquire_wait_micros
            .as_ref()
            .map_or(0, |distribution| distribution.p95)
    );
    report.push('\n');

    let _ = writeln!(report, "## Invariant checks\n");
    let _ = writeln!(report, "| Check | Result | Expected | Observed |");
    let _ = writeln!(report, "|---|---|---|---|");
    for check in &document.checks {
        let _ = writeln!(
            report,
            "| {} | {} | {} | {} |",
            markdown_cell(&check.name),
            if check.passed { "PASS" } else { "FAIL" },
            markdown_cell(&check.expected),
            markdown_cell(&check.observed)
        );
    }
    report.push('\n');

    let _ = writeln!(report, "## Conclusions\n");
    for conclusion in &document.conclusions {
        let _ = writeln!(report, "- {conclusion}");
    }
    report.push('\n');
    let _ = writeln!(report, "## Limitations and comparison rules\n");
    for limitation in &document.limitations {
        let _ = writeln!(report, "- {limitation}");
    }
    let _ = writeln!(
        report,
        "- Compare runs only when CPU, memory, OS/kernel, Rust, Wasmtime, target, build profile, pool topology, limits, fixture digest, and sample configuration are recorded and materially equivalent."
    );
    report
}

fn report_distribution_row_header(report: &mut String) {
    let _ = writeln!(
        report,
        "| Metric | N | Min | P50 | P95 | P99 | Max | Mean |"
    );
    let _ = writeln!(report, "|---|---:|---:|---:|---:|---:|---:|---:|");
}

fn report_distribution_row(report: &mut String, name: &str, distribution: &Distribution) {
    let _ = writeln!(
        report,
        "| {} | {} | {} | {} | {} | {} | {} | {:.1} |",
        markdown_cell(name),
        distribution.samples,
        distribution.minimum,
        distribution.p50,
        distribution.p95,
        distribution.p99,
        distribution.maximum,
        distribution.mean
    );
}

fn report_row(report: &mut String, name: &str, value: &str) {
    let _ = writeln!(
        report,
        "| {} | {} |",
        markdown_cell(name),
        markdown_cell(value)
    );
}

fn markdown_cell(value: &str) -> String {
    value
        .replace('|', "\\|")
        .replace(['\r', '\n'], "<br>")
        .trim()
        .to_owned()
}

fn format_bytes(bytes: u64) -> String {
    const MEBIBYTE: f64 = 1_048_576.0;
    format!("{bytes} bytes ({:.2} MiB)", bytes as f64 / MEBIBYTE)
}
