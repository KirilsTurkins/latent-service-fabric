//! Parent-only process supervision; no extra resources enter child measurements.

use std::fs::File;
use std::io::{self, Read, Write};
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

use super::{MODE_ENV, ROOT_ENV};

#[derive(Clone, Copy)]
struct Budget {
    total: Duration,
    silence: Duration,
}

// Keep the CI job budget above the sum, including build, cleanup and upload time.
// Real file/directory syncs on shared disks are not a throughput benchmark.
const PUBLISH_BUDGET: Budget = Budget {
    total: Duration::from_hours(1),
    silence: Duration::from_mins(10),
};
const REOPEN_BUDGET: Budget = Budget {
    total: Duration::from_mins(30),
    // Rebuild has no per-entry progress callback; allow its full phase budget.
    silence: Duration::from_mins(30),
};

struct Watchdog {
    budget: Budget,
    last_output: Duration,
}

impl Watchdog {
    fn new(budget: Budget) -> Self {
        Self {
            budget,
            last_output: Duration::ZERO,
        }
    }

    fn observe(&mut self, elapsed: Duration, output_bytes: usize) -> Option<&'static str> {
        // Log activity must never extend the absolute wall-clock deadline.
        if elapsed >= self.budget.total {
            return Some("total runtime budget exceeded");
        }
        if output_bytes != 0 {
            self.last_output = elapsed;
        }
        if elapsed.saturating_sub(self.last_output) >= self.budget.silence {
            return Some("no child progress output within silence budget");
        }
        None
    }
}

// Ensure errors/panics in polling or log forwarding do not orphan the child.
struct OwnedChild(Child);

impl Drop for OwnedChild {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

fn forward_chunk(log: &mut File, output: &mut impl Write) -> io::Result<usize> {
    let mut buffer = [0_u8; 8 * 1024];
    let count = log.read(&mut buffer)?;
    if count != 0 {
        output.write_all(&buffer[..count])?;
        output.flush()?;
    }
    Ok(count)
}

pub(super) fn run_child(root: &Path, mode: &str, log_path: &Path) {
    let budget = match mode {
        "publish" => PUBLISH_BUDGET,
        "reopen" => REOPEN_BUDGET,
        _ => panic!("unsupported scale child mode: {mode}"),
    };
    let log = File::create(log_path).expect("probe diagnostics");
    // A separate open file description keeps the read cursor independent of
    // the child's shared stdout/stderr write offset.
    let mut reader = File::open(log_path).expect("open probe log for live forwarding");
    let mut child = OwnedChild(
        Command::new(std::env::current_exe().expect("acceptance test binary"))
            .args([
                "--exact",
                "catalog_scale_child",
                "--ignored",
                "--nocapture",
                "--test-threads=1",
            ])
            .env(ROOT_ENV, root)
            .env(MODE_ENV, mode)
            .stdout(Stdio::from(log.try_clone().expect("clone log")))
            .stderr(Stdio::from(log))
            .spawn()
            .expect("spawn isolated catalog process"),
    );
    let started = Instant::now();
    let mut watchdog = Watchdog::new(budget);
    let mut output = io::stdout();
    eprintln!(
        "{mode} child: total budget={:?}, silence budget={:?}, log={}",
        budget.total,
        budget.silence,
        log_path.display()
    );
    let status = loop {
        let forwarded = forward_chunk(&mut reader, &mut output).expect("forward child log");
        // Completion wins over the deadline, and final output is drained below.
        if let Some(status) = child.0.try_wait().expect("poll probe") {
            break status;
        }
        if let Some(reason) = watchdog.observe(started.elapsed(), forwarded) {
            drop(child); // Kill and reap before draining the final diagnostics.
            while forward_chunk(&mut reader, &mut output).expect("drain child log") != 0 {}
            panic!(
                "{mode} scale child timed out after {:?}: {reason}; log={}",
                started.elapsed(),
                log_path.display()
            );
        }
        thread::sleep(Duration::from_millis(100));
    };
    while forward_chunk(&mut reader, &mut output).expect("drain child log") != 0 {}
    assert!(
        status.success(),
        "{mode} scale child failed: {status}; log={}",
        log_path.display()
    );
}

#[test]
fn progressing_publication_can_exceed_twenty_minutes() {
    let mut watchdog = Watchdog::new(PUBLISH_BUDGET);
    for minute in 0..60 {
        assert_eq!(watchdog.observe(Duration::from_mins(minute), 1), None);
    }
}

#[test]
fn progress_never_extends_the_absolute_deadline() {
    let mut watchdog = Watchdog::new(PUBLISH_BUDGET);
    assert_eq!(
        watchdog.observe(PUBLISH_BUDGET.total, 1),
        Some("total runtime budget exceeded")
    );
}

#[test]
fn silent_publication_times_out_and_output_resets_only_the_silence_clock() {
    let mut watchdog = Watchdog::new(PUBLISH_BUDGET);
    assert_eq!(watchdog.observe(Duration::from_mins(9), 0), None);
    assert_eq!(watchdog.observe(Duration::from_mins(9), 1), None);
    assert_eq!(watchdog.observe(Duration::from_mins(18), 0), None);
    assert_eq!(
        watchdog.observe(Duration::from_mins(19), 0),
        Some("no child progress output within silence budget")
    );
}

#[test]
fn reopen_allows_silent_rebuild_but_remains_bounded() {
    let mut watchdog = Watchdog::new(REOPEN_BUDGET);
    assert_eq!(watchdog.observe(Duration::from_mins(29), 0), None);
    assert_eq!(
        watchdog.observe(REOPEN_BUDGET.total, 0),
        Some("total runtime budget exceeded")
    );
}

#[test]
fn log_forwarding_is_bounded_and_resumes_after_eof() {
    let directory = tempfile::tempdir().expect("log directory");
    let path = directory.path().join("child.log");
    let mut writer = File::create(&path).expect("create log");
    let mut reader = File::open(&path).expect("read log independently");
    let mut output = Vec::new();
    assert_eq!(forward_chunk(&mut reader, &mut output).unwrap(), 0);
    let payload = vec![b'x'; 20_000];
    writer.write_all(&payload).unwrap();
    let first = forward_chunk(&mut reader, &mut output).unwrap();
    assert!((1..=8 * 1024).contains(&first));
    while forward_chunk(&mut reader, &mut output).unwrap() != 0 {}
    assert_eq!(output, payload);
    writer.write_all(b"after EOF").unwrap();
    assert_eq!(forward_chunk(&mut reader, &mut output).unwrap(), 9);
    assert!(output.ends_with(b"after EOF"));
    assert_eq!(forward_chunk(&mut reader, &mut output).unwrap(), 0);
}
