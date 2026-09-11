mod call;
mod output;
mod plan;
mod record;
mod runner;
mod session;

use std::io::Read;
use std::path::{Path, PathBuf};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

type Result<T> = std::result::Result<T, &'static str>;

pub(super) fn run() -> Result<()> {
    if std::env::args_os().skip(1).any(|arg| arg == "--session") {
        return session::run();
    }
    let started = Instant::now();
    let started_unix = unix_millis()?;
    let (plan_path, output_path) = arguments()?;
    let bytes = read(&plan_path, 2 * 1024 * 1024)?;
    let plan: plan::Plan = serde_json::from_slice(&bytes).map_err(|_| "invalid-plan-json")?;
    let prepared = plan.prepare()?;
    let token = read(&plan.token_file, 4096)?;
    let token = std::str::from_utf8(&token).map_err(|_| "invalid-token")?;
    let token = token.trim_end_matches(['\r', '\n']);
    if token.is_empty() || !token.bytes().all(|byte| (33..=126).contains(&byte)) {
        return Err("invalid-token");
    }
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(plan.runtime_workers as usize)
        .max_blocking_threads(1)
        .enable_all()
        .build()
        .map_err(|_| "client-runtime-failed")?;
    runtime.block_on(runner::run(
        plan,
        prepared,
        token,
        output_path,
        record::digest(&bytes),
        started,
        started_unix,
    ))
}

fn arguments() -> Result<(PathBuf, PathBuf)> {
    let mut args = std::env::args_os().skip(1);
    let mut plan = None;
    let mut output = None;
    while let Some(flag) = args.next() {
        let value = args.next().ok_or("usage: --plan PATH --output DIRECTORY")?;
        let slot = if flag == "--plan" {
            &mut plan
        } else if flag == "--output" {
            &mut output
        } else {
            return Err("unknown-argument");
        };
        if slot.replace(PathBuf::from(value)).is_some() {
            return Err("duplicate-argument");
        }
    }
    Ok((plan.ok_or("missing-plan")?, output.ok_or("missing-output")?))
}

fn read(path: &Path, maximum: usize) -> Result<Vec<u8>> {
    if !std::fs::metadata(path)
        .map_err(|_| "input-stat-failed")?
        .is_file()
    {
        return Err("input-not-regular-file");
    }
    let file = std::fs::File::open(path).map_err(|_| "input-open-failed")?;
    if !file.metadata().map_err(|_| "input-stat-failed")?.is_file() {
        return Err("input-not-regular-file");
    }
    let mut bytes = Vec::new();
    file.take(maximum as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| "input-read-failed")?;
    if bytes.len() > maximum {
        return Err("input-byte-limit");
    }
    Ok(bytes)
}

fn unix_millis() -> Result<u64> {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| "wall-clock-unavailable")?
            .as_millis(),
    )
    .map_err(|_| "wall-clock-overflow")
}

fn nanos(duration: std::time::Duration) -> u64 {
    u64::try_from(duration.as_nanos()).unwrap_or(u64::MAX)
}
