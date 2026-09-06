//! Opt-in Linux acceptance probe: real publication, then a new-process rebuild.
//! Ordinary workspace tests compile this target but leave the expensive tests ignored.

#![cfg(target_os = "linux")]

use std::collections::BTreeSet;
use std::fs::{self, File};
use std::future::Future;
use std::path::Path;
use std::pin::Pin;
use std::process::{Command, Stdio};
use std::sync::Arc;
use std::task::{Context, Poll, Wake, Waker};
use std::thread;
use std::time::{Duration, Instant};

use latent_artifacts::{
    ArtifactDescriptor, ArtifactQuery, ArtifactRepository, CapsuleArtifact,
    DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig,
};
use latent_core::{ArtifactReference, Metadata, NodeId, ReleaseDigest};
use latent_manifest::{CapsuleManifest, JsonManifestCodec, ManifestCodec};
use latent_scheduler::{CellClass, FixedCellPool, FixedCellPoolConfig};
use serde::Serialize;
use sha2::{Digest, Sha256};

const RELEASE_COUNT: u32 = 100_000;
const MODE_ENV: &str = "LSF_CATALOG_SCALE_MODE";
const ROOT_ENV: &str = "LSF_CATALOG_SCALE_ROOT";

struct NoopWake;
impl Wake for NoopWake {
    fn wake(self: Arc<Self>) {}
}

fn block_on<T>(mut future: Pin<Box<dyn Future<Output = T> + Send + '_>>) -> T {
    let waker = Waker::from(Arc::new(NoopWake));
    let mut context = Context::from_waker(&waker);
    loop {
        match future.as_mut().poll(&mut context) {
            Poll::Ready(value) => return value,
            Poll::Pending => thread::yield_now(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
struct Topology {
    process_id: u32,
    child_processes: usize,
    threads: usize,
    socket_fds: usize,
    listening_sockets: usize,
    open_fds: usize,
    generic_cells: u32,
    available_cells: u32,
    active_leases: u32,
    queued_activations: u32,
    quarantined_cells: u32,
}

fn topology(pool: &FixedCellPool) -> Topology {
    let tasks: Vec<_> = fs::read_dir("/proc/self/task")
        .expect("task directory")
        .map(|entry| entry.expect("task entry").path())
        .collect();
    let mut children = BTreeSet::new();
    for task in &tasks {
        let text = fs::read_to_string(task.join("children")).expect("task children");
        children.extend(text.split_whitespace().map(str::to_owned));
    }
    let mut sockets = BTreeSet::new();
    let mut socket_fds = 0;
    let mut open_fds = 0;
    for entry in fs::read_dir("/proc/self/fd").expect("file descriptors") {
        let entry = entry.expect("descriptor entry");
        open_fds += 1;
        let target = fs::read_link(entry.path()).expect("descriptor target");
        let target = target.to_string_lossy();
        if let Some(inode) = target
            .strip_prefix("socket:[")
            .and_then(|value| value.strip_suffix(']'))
        {
            sockets.insert(inode.to_owned());
            socket_fds += 1;
        }
    }
    let mut listening_sockets = 0;
    for table in ["tcp", "tcp6", "unix"] {
        let text = fs::read_to_string(format!("/proc/self/net/{table}")).expect("socket table");
        for row in text.lines().skip(1) {
            let fields: Vec<_> = row.split_whitespace().collect();
            if table == "unix" {
                if fields.len() >= 7 && fields[3] == "00010000" && sockets.contains(fields[6]) {
                    listening_sockets += 1;
                }
            } else if fields.len() >= 10 && fields[3] == "0A" && sockets.contains(fields[9]) {
                listening_sockets += 1;
            }
        }
    }
    let cells = pool.observations();
    Topology {
        process_id: std::process::id(),
        child_processes: children.len(),
        threads: tasks.len(),
        socket_fds,
        listening_sockets,
        open_fds,
        generic_cells: cells.capacity,
        available_cells: cells.available,
        active_leases: cells.active_leases,
        queued_activations: cells.queue_depth,
        quarantined_cells: cells.quarantined,
    }
}

fn synthetic_release(template: &CapsuleManifest, index: u32) -> CapsuleArtifact {
    // A minimal Component Model binary with a distinct custom-section payload.
    // The catalog verifies bytes/digests but deliberately does not instantiate it.
    let mut component_bytes = vec![
        0, 97, 115, 109, 13, 0, 1, 0, 0, 9, 4, b's', b'e', b'e', b'd',
    ];
    component_bytes.extend_from_slice(&index.to_le_bytes());
    let digest = ReleaseDigest(format!("sha256:{:x}", Sha256::digest(&component_bytes)));
    let mut manifest = template.clone();
    manifest.component_digest = digest.clone();
    CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference(format!("local://scale/{index:06}")),
            release_digest: digest,
            media_type: "application/vnd.wasm.component.v1+wasm".to_owned(),
            size_bytes: component_bytes.len() as u64,
            publisher: None,
            layers: Vec::new(),
            annotations: Metadata::new(),
        },
        manifest,
        contracts: Vec::new(),
        component_bytes,
    }
}

fn verify_catalog(repo: &dyn ArtifactRepository, template: &CapsuleManifest) {
    let mut after = None;
    let mut seen = 0_u32;
    loop {
        let page = block_on(repo.list(after.as_ref(), 1_000)).expect("bounded listing");
        assert!(page.entries.len() <= 1_000);
        let last = page
            .entries
            .last()
            .map(|entry| entry.release_digest.clone());
        for descriptor in &page.entries {
            if let Some(previous) = &after {
                assert!(
                    &descriptor.release_digest > previous,
                    "strict ordering with no duplicates"
                );
            }
            let index: u32 = descriptor
                .reference
                .0
                .strip_prefix("local://scale/")
                .expect("scale reference")
                .parse()
                .expect("scale index");
            assert!(index < RELEASE_COUNT);
            let expected = synthetic_release(template, index);
            assert_eq!(descriptor, &expected.descriptor);
            assert_eq!(
                block_on(repo.resolve(&ArtifactQuery {
                    reference: Some(descriptor.reference.clone()),
                    release_digest: Some(descriptor.release_digest.clone()),
                    media_type: Some(descriptor.media_type.clone()),
                }))
                .expect("resolve published release"),
                Some(descriptor.clone())
            );
            assert_eq!(
                block_on(repo.fetch(&descriptor.release_digest)).expect("byte-for-byte fetch"),
                expected
            );
            after = Some(descriptor.release_digest.clone());
            seen += 1;
        }
        match page.next_after {
            Some(cursor) => {
                assert_eq!(
                    Some(&cursor),
                    last.as_ref(),
                    "continuation must match last entry"
                );
                assert!(!page.entries.is_empty(), "pagination must make progress");
                after = Some(cursor);
            }
            None => break,
        }
    }
    assert_eq!(
        seen, RELEASE_COUNT,
        "all persisted releases must be retrievable"
    );
}

#[test]
#[ignore = "run through production_catalog_100k; requires a parent-owned persistent root"]
fn catalog_scale_child() {
    let mode = std::env::var(MODE_ENV).expect("scale child mode");
    let root = std::env::var_os(ROOT_ENV).expect("scale root");
    assert!(mode == "publish" || mode == "reopen");
    let pool = FixedCellPool::new(FixedCellPoolConfig::new(
        NodeId("catalog-scale-node".to_owned()),
        CellClass::Standard,
        2,
        2,
    ))
    .expect("fixed node-owned pool");
    let baseline = topology(&pool);
    assert_eq!(baseline.active_leases, 0);
    assert_eq!(baseline.generic_cells, 2);
    let repo = DirectoryArtifactRepository::open(
        root,
        DirectoryArtifactRepositoryConfig {
            max_index_entries: RELEASE_COUNT as usize,
            max_index_bytes: 256 * 1024 * 1024,
            ..DirectoryArtifactRepositoryConfig::default()
        },
    )
    .expect("open or rebuild production repository");
    let mut opened = baseline.clone();
    opened.open_fds += 1; // One root-ownership lock, not one FD per release.
    assert_eq!(
        topology(&pool),
        opened,
        "opening adds only a fixed ownership FD"
    );
    let template = JsonManifestCodec::default()
        .decode_capsule(include_bytes!(
            "../../../examples/echo-contract/capsule.json"
        ))
        .expect("valid capsule template");
    let repository: &dyn ArtifactRepository = &repo;
    if mode == "publish" {
        for index in 0..RELEASE_COUNT {
            let release = synthetic_release(&template, index);
            let descriptor = release.descriptor.clone();
            assert_eq!(
                block_on(repository.publish(release)).expect("durable publication"),
                descriptor
            );
            if (index + 1) % 10_000 == 0 {
                assert_eq!(
                    topology(&pool),
                    opened,
                    "registration checkpoint {}",
                    index + 1
                );
                eprintln!(
                    "published {} complete releases through ArtifactRepository::publish",
                    index + 1
                );
            }
        }
    }
    verify_catalog(repository, &template);
    let after = topology(&pool);
    assert_eq!(
        after, opened,
        "no per-release execution or OS resource growth"
    );
    println!(
        "{}",
        serde_json::json!({
            "mode": mode,
            "registered_and_fetched": RELEASE_COUNT,
            "baseline": baseline,
            "after": after,
            "fixed_helpers": {
                "probe_processes": 1,
                "harness_threads": baseline.threads,
                "node_generic_cells": baseline.generic_cells,
                "catalog_ownership_fds": 1
            },
            "service_specific_growth": {
                "processes": after.child_processes - baseline.child_processes,
                "threads": after.threads - baseline.threads,
                "listening_sockets": after.listening_sockets - baseline.listening_sockets,
                "execution_cells": after.generic_cells - baseline.generic_cells,
                "active_leases": after.active_leases - baseline.active_leases
            }
        })
    );
    drop(repo);
    assert_eq!(
        topology(&pool),
        baseline,
        "dropping repository releases its ownership FD"
    );
}

fn run_child(root: &Path, mode: &str, log_path: &Path) {
    let log = File::create(log_path).expect("probe diagnostics");
    let mut child = Command::new(std::env::current_exe().expect("acceptance test binary"))
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
        .expect("spawn isolated catalog process");
    let deadline = Instant::now() + Duration::from_secs(1_200);
    let status = loop {
        if let Some(status) = child.try_wait().expect("poll probe") {
            break status;
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            panic!(
                "{mode} scale child timed out:\n{}",
                fs::read_to_string(log_path).unwrap_or_default()
            );
        }
        thread::sleep(Duration::from_millis(25));
    };
    let diagnostics = fs::read_to_string(log_path).expect("read probe diagnostics");
    print!("{diagnostics}");
    assert!(
        status.success(),
        "{mode} scale child failed: {status}\n{diagnostics}"
    );
}

#[test]
#[ignore = "100,000 real fsynced publications; run in the dedicated catalog acceptance CI job"]
fn production_catalog_100k() {
    let root = tempfile::tempdir().expect("persistent catalog root");
    let logs = tempfile::tempdir().expect("probe logs");
    run_child(root.path(), "publish", &logs.path().join("publish.log"));
    assert_eq!(
        fs::read_dir(root.path().join("releases"))
            .expect("completed directories")
            .count(),
        RELEASE_COUNT as usize
    );
    // The publisher process is gone before the second process acquires the
    // root, rebuilds its index, and fetches every release from persistent files.
    run_child(root.path(), "reopen", &logs.path().join("reopen.log"));
}
