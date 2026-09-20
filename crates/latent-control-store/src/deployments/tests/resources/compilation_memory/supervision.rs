//! The physical fixture owns exactly one child at a time and no detached writers.

use std::io::{self, Read};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use super::super::ReapedChild;

const MAX_STREAM_BYTES: usize = 64 * 1024;

fn reader(
    source: impl Read + Send + 'static,
    overflow: Arc<AtomicBool>,
) -> JoinHandle<io::Result<Vec<u8>>> {
    std::thread::spawn(move || {
        let mut output = Vec::new();
        source
            .take((MAX_STREAM_BYTES + 1) as u64)
            .read_to_end(&mut output)?;
        if output.len() > MAX_STREAM_BYTES {
            overflow.store(true, Ordering::Release);
        }
        Ok(output)
    })
}

pub(super) fn run(command: &mut Command, timeout: Duration) -> Result<(String, f64), String> {
    let started = Instant::now();
    let mut child = ReapedChild(
        command
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|error| format!("child-spawn: {error}"))?,
    );
    let overflow = Arc::new(AtomicBool::new(false));
    let stdout = reader(child.0.stdout.take().unwrap(), Arc::clone(&overflow));
    let stderr = reader(child.0.stderr.take().unwrap(), Arc::clone(&overflow));
    let outcome = loop {
        if overflow.load(Ordering::Acquire) {
            break Err("child-output-limit".to_owned());
        }
        match child.0.try_wait() {
            Ok(Some(status)) => break Ok(status),
            Ok(None) => {}
            Err(error) => break Err(format!("child-wait: {error}")),
        }
        if started.elapsed() >= timeout {
            break Err("child-timeout".to_owned());
        }
        std::thread::sleep(Duration::from_millis(10));
    };
    if outcome.is_err() {
        let _ = child.0.kill();
        let _ = child.0.wait();
    }
    // The fixture child does not start descendants. Both bounded pipe readers
    // are joined after exit/kill, before the parent can remove its private root.
    let stdout = stdout.join().map_err(|_| "stdout-reader-panicked")?;
    let stderr = stderr.join().map_err(|_| "stderr-reader-panicked")?;
    let stdout = stdout.map_err(|error| format!("stdout-read: {error}"))?;
    let stderr = stderr.map_err(|error| format!("stderr-read: {error}"))?;
    if stdout.len() > MAX_STREAM_BYTES || stderr.len() > MAX_STREAM_BYTES {
        return Err("child-output-limit".to_owned());
    }
    let evidence = format!(
        "{}{}",
        String::from_utf8_lossy(&stdout),
        String::from_utf8_lossy(&stderr)
    );
    let status = outcome.map_err(|error| format!("{error}: {evidence}"))?;
    if !status.success() {
        return Err(format!("child-exit={status}: {evidence}"));
    }
    Ok((evidence, started.elapsed().as_secs_f64()))
}

#[test]
fn child_timeout_kills_and_reaps_the_owned_process() {
    let result = run(
        Command::new("sh").args(["-c", "exec sleep 60"]),
        Duration::from_millis(50),
    );
    assert!(result.unwrap_err().starts_with("child-timeout"));
}

#[test]
fn child_output_is_bounded_before_any_log_file_can_grow() {
    let result = run(
        Command::new("sh").args(["-c", "while :; do printf 'xxxxxxxxxxxxxxxx'; done"]),
        Duration::from_secs(5),
    );
    assert_eq!(result.unwrap_err(), "child-output-limit");
}

#[test]
fn unsuccessful_child_exit_is_not_an_observation() {
    let result = run(
        Command::new("sh").args(["-c", "printf diagnostic; exit 7"]),
        Duration::from_secs(5),
    );
    let error = result.unwrap_err();
    assert!(error.contains("child-exit="));
    assert!(error.contains("diagnostic"));
}
