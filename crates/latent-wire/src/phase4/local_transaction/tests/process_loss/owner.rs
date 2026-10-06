use super::*;
use latent_test_process::{ProcessHarness, ProcessLimits};
use std::{io::Write, os::unix::fs::OpenOptionsExt, path::Path};

pub(super) async fn run(directory: &Path, kind: &str, expires_at: Instant) -> inventory::Probe {
    let probe = directory.join("child-probe.json");
    let child = ProcessHarness::new(std::env::current_exe().unwrap())
        .args(["--exact", CASE, "--ignored", "--nocapture"])
        .env(CHILD_KIND, kind)
        .env(CHILD_PROBE, probe.as_os_str())
        .env("LATENT_STATE_TEST_ROOT", directory.as_os_str())
        .spawn_bounded(ProcessLimits {
            maximum_stdout_bytes: 64 * 1024,
            maximum_stderr_bytes: 64 * 1024,
            timeout: expires_at
                .saturating_duration_since(Instant::now())
                .min(Duration::from_secs(300)),
        })
        .unwrap();
    let pid = child.id();
    let captured = child.wait().await.unwrap();
    for (name, bytes) in [
        ("child-stdout.log", &captured.stdout),
        ("child-stderr.log", &captured.stderr),
    ] {
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(directory.join(name))
            .unwrap();
        file.write_all(bytes).unwrap();
        file.sync_all().unwrap();
    }
    assert_eq!(
        captured.status.code(),
        Some(LOST_PROCESS_EXIT),
        "child {pid} failed; retained evidence {}",
        directory.display()
    );
    let bytes = fs::read(probe).unwrap();
    assert!(bytes.len() <= 64 * 1024);
    let probe: inventory::Probe = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(probe.pid, pid);
    assert_eq!(probe.root.parent().unwrap(), directory);
    probe
}
