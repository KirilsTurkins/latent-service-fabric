use std::fs::File;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use latent_core::{PlatformError, PlatformErrorCode};
use latent_wasmtime::{
    AotCompilationJob, AotJobControl, AotProcessLimits, AotResourceSnapshot, IsolatedAotCompiler,
    TrustedAotOutput, ValidatedAotProfile, WasmtimeConfig,
};
use sha2::{Digest, Sha256};

use super::support::{self, Directory, Fixture};

pub fn run() {
    let compiler = compiler(support::limits());
    protocol_failures(&compiler);
    cancel_running_prefix(&compiler);
    compiler.shutdown(Duration::from_secs(1)).unwrap();
    malformed_readiness();
    running_deadline();
    last_owner_drop();
    active_shutdown();
    super::inherited::run();
    eprintln!("isolated AOT supervisor: 13 bounded protocol/ownership scenarios passed");
}

fn protocol_failures(compiler: &IsolatedAotCompiler) {
    for (mode, code) in [
        ("oversized", PlatformErrorCode::ResourceExhausted),
        ("zero", PlatformErrorCode::ResourceExhausted),
        ("truncated-header", PlatformErrorCode::Unavailable),
        ("truncated-body", PlatformErrorCode::Unavailable),
        ("trailing", PlatformErrorCode::PermissionDenied),
        ("nonzero-exit", PlatformErrorCode::Unavailable),
        ("diagnostic-overflow", PlatformErrorCode::ResourceExhausted),
    ] {
        let directory = Directory::new();
        let marker = directory.path().join("worker.pid");
        let fixture = fixture(mode, &marker);
        let failure = compiler
            .reserve(fixture.source(), fixture.release())
            .unwrap()
            .run()
            .unwrap_err();
        assert_eq!(failure.code, code, "{mode}");
        assert_eq!(
            compiler.snapshot(),
            AotResourceSnapshot::default(),
            "{mode}"
        );
        if let Some(pid) = marker_pid(&marker) {
            assert_reaped(pid);
        }
    }
}

fn cancel_running_prefix(compiler: &IsolatedAotCompiler) {
    let directory = Directory::new();
    let marker = directory.path().join("worker.pid");
    let fixture = fixture("complete-then-hang", &marker);
    let running = Running::start(
        compiler
            .reserve(fixture.source(), fixture.release())
            .unwrap(),
    );
    let pid = wait_for_marker(&marker, &running);
    assert!(Path::new(&format!("/proc/{pid}")).exists());
    let reserved = compiler.snapshot();
    assert_eq!(reserved.jobs, 1);
    assert_eq!(reserved.output_owners, 1);
    assert_eq!(reserved.native_bytes, support::OUTPUT_BYTES);
    running.control.cancel();
    assert_eq!(
        running.finish().unwrap_err().code,
        PlatformErrorCode::Cancelled
    );
    assert_reaped(pid);
    assert_eq!(compiler.snapshot(), AotResourceSnapshot::default());
    assert_eq!(std::sync::Arc::strong_count(&fixture.repository), 1);
}

fn malformed_readiness() {
    let mut limits = support::limits();
    limits.compiler.maximum_output_bytes = 17;
    let compiler = compiler(limits);
    let directory = Directory::new();
    let marker = directory.path().join("worker.pid");
    let fixture = fixture("hang", &marker);
    assert_eq!(
        compiler
            .reserve(fixture.source(), fixture.release())
            .unwrap()
            .run()
            .unwrap_err()
            .code,
        PlatformErrorCode::PermissionDenied
    );
    assert!(
        !marker.exists(),
        "malformed readiness must not receive component input"
    );
    assert_eq!(compiler.snapshot(), AotResourceSnapshot::default());
}

fn running_deadline() {
    let mut limits = support::limits();
    limits.job_timeout = Duration::from_secs(20);
    let compiler = compiler(limits);
    let directory = Directory::new();
    let marker = directory.path().join("worker.pid");
    let fixture = fixture("hang", &marker);
    let running = Running::start(
        compiler
            .reserve(fixture.source(), fixture.release())
            .unwrap(),
    );
    let pid = wait_for_marker(&marker, &running);
    assert_eq!(compiler.snapshot().jobs, 1);
    assert_eq!(
        running.finish().unwrap_err().code,
        PlatformErrorCode::DeadlineExceeded
    );
    assert_reaped(pid);
    assert_eq!(compiler.snapshot(), AotResourceSnapshot::default());
}

fn last_owner_drop() {
    let compiler = compiler(support::limits());
    let directory = Directory::new();
    let marker = directory.path().join("worker.pid");
    let fixture = fixture("hang", &marker);
    let running = Running::start(
        compiler
            .reserve(fixture.source(), fixture.release())
            .unwrap(),
    );
    let pid = wait_for_marker(&marker, &running);
    assert_eq!(compiler.snapshot().jobs, 1);
    // Keep no producer clone: the job's internal State must not keep Owner alive.
    drop(compiler);
    assert_eq!(
        running.finish().unwrap_err().code,
        PlatformErrorCode::Cancelled
    );
    assert_reaped(pid);
    assert_eq!(std::sync::Arc::strong_count(&fixture.repository), 1);
}

fn active_shutdown() {
    let compiler = compiler(support::limits());
    let directory = Directory::new();
    let marker = directory.path().join("worker.pid");
    let fixture = fixture("hang", &marker);
    let running = Running::start(
        compiler
            .reserve(fixture.source(), fixture.release())
            .unwrap(),
    );
    let pid = wait_for_marker(&marker, &running);
    assert_eq!(compiler.snapshot().jobs, 1);
    // Cleanup may finish concurrently with this zero-duration observation.
    if let Err(error) = compiler.shutdown(Duration::ZERO) {
        assert_eq!(error.code, PlatformErrorCode::DeadlineExceeded);
    }
    assert_eq!(
        running.finish().unwrap_err().code,
        PlatformErrorCode::Cancelled
    );
    assert_reaped(pid);
    assert_eq!(compiler.snapshot(), AotResourceSnapshot::default());
    compiler.shutdown(Duration::from_secs(1)).unwrap();
}

fn fixture(mode: &str, marker: &Path) -> Fixture {
    let bytes = serde_json::to_vec(&serde_json::json!({"mode": mode, "marker": marker})).unwrap();
    assert!(bytes.len() < 4096);
    Fixture::new(bytes)
}

fn compiler(limits: AotProcessLimits) -> IsolatedAotCompiler {
    static EXECUTABLE: OnceLock<(PathBuf, [u8; 32])> = OnceLock::new();
    let (executable, digest) = EXECUTABLE.get_or_init(|| {
        let path = std::env::current_exe().unwrap().canonicalize().unwrap();
        let mut file = File::open(&path).unwrap();
        let mut hash = Sha256::new();
        let mut buffer = [0; 16 * 1024];
        loop {
            let count = file.read(&mut buffer).unwrap();
            if count == 0 {
                break;
            }
            hash.update(&buffer[..count]);
        }
        (path, hash.finalize().into())
    });
    let profile =
        ValidatedAotProfile::from_config(&WasmtimeConfig::default(), limits.compiler).unwrap();
    IsolatedAotCompiler::new(
        executable,
        *digest,
        profile,
        support::authority(limits),
        limits,
    )
    .unwrap()
}

struct Running {
    control: AotJobControl,
    owner: Option<JoinHandle<Result<TrustedAotOutput, PlatformError>>>,
}
impl Running {
    fn start(job: AotCompilationJob) -> Self {
        Self {
            control: job.control(),
            owner: Some(thread::spawn(move || job.run())),
        }
    }
    fn finish(mut self) -> Result<TrustedAotOutput, PlatformError> {
        self.owner
            .take()
            .unwrap()
            .join()
            .expect("supervisor thread must not panic")
    }
    fn finished(&self) -> bool {
        self.owner.as_ref().unwrap().is_finished()
    }
}
impl Drop for Running {
    fn drop(&mut self) {
        self.control.cancel();
        if let Some(owner) = self.owner.take() {
            let _ = owner.join();
        }
    }
}

fn marker_pid(path: &Path) -> Option<u32> {
    let mut bytes = Vec::with_capacity(16);
    match File::open(path) {
        Ok(file) => {
            file.take(16).read_to_end(&mut bytes).unwrap();
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return None,
        Err(error) => panic!("read fixture rendezvous: {error}"),
    }
    std::str::from_utf8(&bytes)
        .ok()?
        .strip_suffix('\n')?
        .parse::<u32>()
        .ok()
        .filter(|pid| *pid > 0)
}

fn wait_for_marker(path: &Path, running: &Running) -> u32 {
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        if let Some(pid) = marker_pid(path) {
            return pid;
        }
        assert!(!running.finished(), "fixture exited before consuming input");
        assert!(
            Instant::now() < deadline,
            "fixture input rendezvous timed out"
        );
        thread::sleep(Duration::from_millis(1));
    }
}

fn assert_reaped(pid: u32) {
    assert!(
        !Path::new(&format!("/proc/{pid}")).exists(),
        "owned child must be reaped before returning"
    );
}
