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
    let _ = writeln!(
        report,
        "**Schema:** `{}`  ",
        document.schema_version
    );
    let _ = writeln!(
        report,
        "**Generated:** Unix epoch {} ms  ",
        document.generated_at_unix_millis
    );
    let _ = writeln!(
        report,
        "**Raw results:** `{}`\n",
        raw_path.display()
    );
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

    let _ = writeln!(report, "## Runtime and sample configuration\n");
    let _ = writeln!(report, "| Field | Value |");
    let _ = writeln!(report, "|---|---:|");
    report_row(&mut report, "Mode", &format!("{:?}", document.config.mode));
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
        "Activation throughput batches",
        &document.config.throughput_batches.to_string(),
    );
    report_row(
        &mut report,
        "Pool iterations per worker",
        &document.config.pool_iterations.to_string(),
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
    report.push('\n');

    let _ = writeln!(report, "## Artifact\n");
    let _ = writeln!(report, "| Field | Value |");
    let _ = writeln!(report, "|---|---|");
    report_row(&mut report, "Capsule", &document.artifact.capsule_path);
    report_row(&mut report, "Component", &document.artifact.component_path);
    report_row(&mut report, "Digest", &document.artifact.component_digest);
    report_row(
        &mut report,
        "Component bytes",
        &document.artifact.component_bytes.to_string(),
    );
    report.push('\n');

    let _ = writeln!(report, "## Startup and preparation\n");
    let _ = writeln!(report, "| Metric | Microseconds |");
    let _ = writeln!(report, "|---|---:|");
    report_row(
        &mut report,
        "Rust entry to fixed runtime/pool ready",
        &document
            .timings
            .process_entry_to_runtime_ready_micros
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
        "Rust entry to first invocation ready",
        &document
            .timings
            .process_entry_to_first_invocation_ready_micros
            .to_string(),
    );
    report.push('\n');

    let _ = writeln!(report, "## Activation distributions\n");
    let _ = writeln!(
        report,
        "Percentiles use nearest-rank ordering over raw wall-clock samples.\n"
    );
    let _ = writeln!(
        report,
        "| Metric | N | Min | P50 | P95 | P99 | Max | Mean |"
    );
    let _ = writeln!(report, "|---|---:|---:|---:|---:|---:|---:|---:|");
    for (name, distribution) in &document.timings.distributions {
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
    report.push('\n');

    let _ = writeln!(report, "## Fixed-pool and activation throughput\n");
    let _ = writeln!(report, "| Metric | Value |");
    let _ = writeln!(report, "|---|---:|");
    report_row(
        &mut report,
        "Immediate acquire P50",
        &format!("{} us", document.pool_probe.acquire_micros.p50),
    );
    report_row(
        &mut report,
        "Queued wait P95",
        &format!("{} us", document.pool_probe.queued_wait_micros.p95),
    );
    report_row(
        &mut report,
        "Release P50",
        &format!("{} us", document.pool_probe.release_micros.p50),
    );
    report_row(
        &mut report,
        "Bounded overflow rejected",
        &document.pool_probe.overflow_rejected.to_string(),
    );
    report_row(
        &mut report,
        "Pool acquire/release operations",
        &document.pool_probe.throughput_operations.to_string(),
    );
    report_row(
        &mut report,
        "Pool operations/second",
        &format!(
            "{:.1}",
            document.pool_probe.throughput_operations_per_second
        ),
    );
    report_row(
        &mut report,
        "Concurrent activations",
        &document.activation_throughput.activations.to_string(),
    );
    report_row(
        &mut report,
        "Activations/second at configured capacity",
        &format!(
            "{:.1}",
            document.activation_throughput.activations_per_second
        ),
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
