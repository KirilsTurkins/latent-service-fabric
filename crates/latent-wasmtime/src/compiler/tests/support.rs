use std::future::Future;
use std::path::PathBuf;
use std::pin::Pin;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{mpsc, Arc};
use std::task::{Context, Poll, Waker};
use std::time::{Duration, Instant};

use latent_artifacts::{
    ArtifactDescriptor, ArtifactRepository, CapsuleArtifact, DirectoryArtifactRepository,
    DirectoryArtifactRepositoryConfig,
};
use latent_core::{ArtifactReference, Metadata, ReleaseDigest};
use latent_executor::PreparationKey;
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use sha2::{Digest as _, Sha256};

use crate::cache::{PrepareAccess, PreparedCache};
use crate::compiler::{
    Acquisition, Admission, CoalescingKey, CompilationResult, CompilerPool, PreparationWait,
    ReadyPin,
};
use crate::{PreparationObserver, WasmtimeConfig};

pub(super) fn config() -> WasmtimeConfig {
    WasmtimeConfig {
        maximum_concurrent_preparations: 4,
        compiler_workers: Some(2),
        maximum_preparation_waiters: 8,
        maximum_waiters_per_preparation: 8,
        maximum_ready_preparations: 12,
        prepared_cache_maximum_entries: 8,
        prepared_cache_maximum_source_bytes: 128,
        prepared_cache_maximum_metadata_bytes: 256,
        prepared_cache_maximum_compiled_image_bytes: 256,
        maximum_preparation_document_bytes: 1024,
        ..WasmtimeConfig::default()
    }
}

pub(super) fn pool(config: &WasmtimeConfig) -> CompilerPool<u8> {
    let cache = Arc::new(PreparedCache::new(config.cache_limits()).unwrap());
    CompilerPool::new(
        config,
        cache,
        PreparationObserver::new(config.maximum_concurrent_preparations),
        |_| (8, 16),
    )
    .unwrap()
}

pub(super) fn input(name: &str, identity: Option<CoalescingKey>) -> Admission {
    Admission {
        identity,
        handle: name.to_owned(),
        source_bytes: 8,
        metadata_bytes: 16,
        document_bytes: 0,
    }
}

pub(super) fn waiting(
    pool: &CompilerPool<u8>,
    name: &str,
    identity: Option<CoalescingKey>,
) -> (PreparationWait<u8>, bool) {
    match pool.acquire(input(name, identity)).unwrap() {
        Acquisition::Waiting { future, owner } => (future, owner),
        Acquisition::Ready(_) => panic!("expected a preparation waiter"),
    }
}

pub(super) fn blocked(
    pool: &CompilerPool<u8>,
    future: &PreparationWait<u8>,
) -> (mpsc::Receiver<()>, mpsc::Sender<()>) {
    let (started_send, started) = mpsc::channel();
    let (release, released) = mpsc::channel();
    let observer = pool.core.observer.clone();
    future
        .start(move |reservation| {
            Box::new(move |queue| {
                let observation =
                    observer.begin(&ReleaseDigest(format!("sha256:{}", "a".repeat(64))));
                observation.record_queue_wait(queue.started_nanos, queue.finished_nanos);
                let _ = started_send.send(());
                released
                    .recv_timeout(Duration::from_secs(5))
                    .expect("test releases its bounded worker");
                Ok(CompilationResult {
                    runtime: Arc::new(7),
                    reservation: Some(reservation),
                    observation,
                })
            })
        })
        .unwrap();
    (started, release)
}

pub(super) fn complete<T>(future: impl Future<Output = T>) -> T {
    let mut future = Box::pin(future);
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        if let Poll::Ready(value) = future
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop()))
        {
            return value;
        }
        assert!(
            Instant::now() < deadline,
            "bounded compiler future did not complete"
        );
        std::thread::sleep(Duration::from_millis(1));
    }
}

pub(super) fn pending(future: &mut PreparationWait<u8>) {
    assert!(Pin::new(future)
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
}

pub(super) fn idle(pool: &CompilerPool<u8>) {
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        let snapshot = pool.observer().snapshot();
        if snapshot.assigned_jobs == 0 && snapshot.queued_jobs == 0 {
            return;
        }
        assert!(
            Instant::now() < deadline,
            "compiler did not release its job"
        );
        std::thread::sleep(Duration::from_millis(1));
    }
}

pub(super) fn cached(pool: &CompilerPool<u8>, handle: &str) {
    let PrepareAccess::Compile(reservation) =
        pool.core.cache.begin(handle.to_owned(), 8, 16).unwrap()
    else {
        panic!("empty cache")
    };
    reservation
        .publish_with_metadata(Arc::new(3), 16, 8)
        .unwrap();
}

pub(super) fn ready(acquired: Acquisition<u8>) -> ReadyPin<u8> {
    let Acquisition::Ready(pin) = acquired else {
        panic!("expected a warm pin")
    };
    pin
}

pub(super) struct Directory(pub(super) PathBuf);

impl Directory {
    pub(super) fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "latent-compiler-test-{}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&path).unwrap();
        Self(path)
    }

    pub(super) fn open(&self) -> DirectoryArtifactRepository {
        DirectoryArtifactRepository::open(&self.0, DirectoryArtifactRepositoryConfig::default())
            .unwrap()
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

pub(super) fn source() -> (Directory, Arc<DirectoryArtifactRepository>, CoalescingKey) {
    let directory = Directory::new();
    let repository = Arc::new(directory.open());
    let bytes = b"bounded compiler pool protocol fixture".to_vec();
    let release = ReleaseDigest(format!("sha256:{:x}", Sha256::digest(&bytes)));
    let mut document: serde_json::Value = serde_json::from_str(include_str!(
        "../../../../../examples/echo-contract/capsule.json"
    ))
    .unwrap();
    document["component"]["digest"] = serde_json::Value::String(release.0.clone());
    let manifest = JsonManifestCodec::default()
        .decode_capsule(&serde_json::to_vec(&document).unwrap())
        .unwrap();
    let artifact = CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference("local://compiler/protocol".to_owned()),
            release_digest: release.clone(),
            media_type: "application/vnd.wasm.component.v1+wasm".to_owned(),
            size_bytes: bytes.len() as u64,
            publisher: None,
            layers: Vec::new(),
            annotations: Metadata::new(),
        },
        manifest,
        contracts: Vec::new(),
        component_bytes: bytes,
    };
    complete(repository.publish(artifact)).unwrap();
    let source = repository
        .preparation_source()
        .unwrap()
        .identity(&release)
        .unwrap()
        .unwrap();
    let key = PreparationKey {
        release,
        engine_version: "test".to_owned(),
        engine_configuration_digest: "test".to_owned(),
        target_triple: "test".to_owned(),
        cpu_feature_set: "test".to_owned(),
    };
    (
        directory,
        repository,
        CoalescingKey {
            key,
            source,
            eligibility: None,
        },
    )
}

#[cfg(unix)]
pub(super) fn supervised_abort(scenario: &str, environment: &str, ready: &str) {
    use std::io::Read as _;
    use std::process::{Child, Command, Stdio};
    struct Supervised(Child);
    impl Drop for Supervised {
        fn drop(&mut self) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
    let executable = std::env::current_exe().unwrap();
    let mut child = Supervised(
        Command::new("sh")
            .args(["-c", "ulimit -c 0; exec \"$@\"", "latent-compiler-test"])
            .arg(executable)
            .args(["--exact", scenario, "--nocapture", "--test-threads=1"])
            .env(environment, scenario)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .unwrap(),
    );
    let deadline = Instant::now() + Duration::from_secs(8);
    let status = loop {
        if let Some(status) = child.0.try_wait().unwrap() {
            break status;
        }
        assert!(
            Instant::now() < deadline,
            "reentrant child exceeded its watchdog"
        );
        std::thread::sleep(Duration::from_millis(5));
    };
    let mut output = String::new();
    child
        .0
        .stdout
        .take()
        .unwrap()
        .take(16 * 1024)
        .read_to_string(&mut output)
        .unwrap();
    assert!(
        output.contains(ready),
        "the intended child branch must execute"
    );
    use std::os::unix::process::ExitStatusExt as _;
    assert_eq!(
        status.signal(),
        Some(6),
        "child must terminate by SIGABRT: {status}"
    );
}
