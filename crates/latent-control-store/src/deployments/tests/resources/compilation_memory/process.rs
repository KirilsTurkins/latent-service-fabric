//! Bounded pipe capture for the three fresh, non-spawning probe children.

use std::io::Read;
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

use super::super::ReapedChild;

const OUTPUT_BYTES: usize = 64 * 1024;

fn capture(mut pipe: impl Read, exceeded: &AtomicBool) -> std::io::Result<Vec<u8>> {
    let mut output = Vec::new();
    let mut buffer = [0; 4096];
    loop {
        let count = pipe.read(&mut buffer)?;
        if count == 0 {
            return Ok(output);
        }
        // Each pipe gets half the total cap. No unbounded log file is created.
        if output.len() + count > OUTPUT_BYTES / 2 {
            exceeded.store(true, Ordering::Relaxed);
            return Ok(output);
        }
        output.extend_from_slice(&buffer[..count]);
    }
}

pub(super) fn run(mut command: Command, timeout: Duration) -> Result<String, String> {
    let exceeded = AtomicBool::new(false);
    std::thread::scope(|scope| {
        let mut child = ReapedChild(
            command
                .stdin(Stdio::null())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()
                .map_err(|error| format!("probe-spawn: {error}"))?,
        );
        let stdout = child.0.stdout.take().expect("piped stdout");
        let stderr = child.0.stderr.take().expect("piped stderr");
        let stdout = scope.spawn(|| capture(stdout, &exceeded));
        let stderr = scope.spawn(|| capture(stderr, &exceeded));
        let deadline = Instant::now() + timeout;
        let status = loop {
            if exceeded.load(Ordering::Relaxed) {
                break Err("probe-output-limit".to_owned());
            }
            if Instant::now() >= deadline {
                break Err("probe-timeout".to_owned());
            }
            match child.0.try_wait() {
                Ok(Some(status)) => break Ok(status),
                Ok(None) => std::thread::sleep(Duration::from_millis(10)),
                Err(error) => break Err(format!("probe-wait: {error}")),
            }
        };
        if status.is_err() {
            // Own kill and wait even on timeout, output-limit and observation errors.
            let _ = child.0.kill();
            let _ = child.0.wait();
        }
        let stdout = stdout
            .join()
            .map_err(|_| "probe-stdout-thread".to_owned())?
            .map_err(|error| format!("probe-stdout: {error}"))?;
        let stderr = stderr
            .join()
            .map_err(|_| "probe-stderr-thread".to_owned())?
            .map_err(|error| format!("probe-stderr: {error}"))?;
        if exceeded.load(Ordering::Relaxed) {
            return Err("probe-output-limit".to_owned());
        }
        let status = status?;
        let mut output = String::from_utf8(stdout).map_err(|_| "probe-stdout-utf8".to_owned())?;
        output.push_str(&String::from_utf8(stderr).map_err(|_| "probe-stderr-utf8".to_owned())?);
        if !status.success() {
            return Err(format!("probe-failed ({status}): {output}"));
        }
        Ok(output)
    })
}

#[test]
fn capture_is_bounded_even_when_one_pipe_floods() {
    let exceeded = AtomicBool::new(false);
    let result = capture(std::io::repeat(b'x').take(OUTPUT_BYTES as u64), &exceeded).unwrap();
    assert!(exceeded.load(Ordering::Relaxed));
    assert!(result.len() <= OUTPUT_BYTES / 2);
}

#[test]
fn capture_preserves_small_output_and_io_errors() {
    let exceeded = AtomicBool::new(false);
    assert_eq!(
        capture(&b"observation\n"[..], &exceeded).unwrap(),
        b"observation\n"
    );
    assert!(!exceeded.load(Ordering::Relaxed));
    struct Broken;
    impl Read for Broken {
        fn read(&mut self, _: &mut [u8]) -> std::io::Result<usize> {
            Err(std::io::Error::other("negative-control"))
        }
    }
    assert!(capture(Broken, &exceeded).is_err());
}
