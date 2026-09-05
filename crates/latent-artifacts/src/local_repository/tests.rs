use std::fs;
use std::future::Future;
use std::path::{Path, PathBuf};
use std::pin::Pin;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Barrier};
use std::task::{Context, Poll, Wake, Waker};
use std::thread;
use std::time::{SystemTime, UNIX_EPOCH};

use latent_contracts::{
    ContractDescriptor, FieldDescriptor, FunctionDescriptor, InterfaceDescriptor, ValueType,
};
use latent_core::{
    ArtifactReference, ContractId, FunctionId, InterfaceId, Metadata, PlatformErrorCode,
    ReleaseDigest,
};
use latent_manifest::{JsonManifestCodec, ManifestCodec};

use super::{
    release_digest, ArtifactDescriptor, ArtifactQuery, ArtifactRepository, CapsuleArtifact,
    CatalogIndex, DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig,
};

const PLACEHOLDER_DIGEST: &str =
    "sha256:1111111111111111111111111111111111111111111111111111111111111111";

static NEXT_TEMP_ID: AtomicU64 = AtomicU64::new(0);

struct TempRoot(PathBuf);

impl TempRoot {
    fn new() -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("test clock must be after Unix epoch")
            .as_nanos();
        let sequence = NEXT_TEMP_ID.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "latent-artifact-catalog-{}-{nonce}-{sequence}",
            std::process::id()
        ));
        fs::create_dir_all(&path).expect("temporary catalog root must be created");
        Self(path)
    }

    fn path(&self) -> &Path {
        &self.0
    }
}

impl Drop for TempRoot {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

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

fn repository(root: &Path) -> DirectoryArtifactRepository {
    DirectoryArtifactRepository::open(root, DirectoryArtifactRepositoryConfig::default())
        .expect("repository must open")
}

fn artifact(name: &str, bytes: &[u8]) -> CapsuleArtifact {
    let release = release_digest(bytes);
    let manifest_source = include_str!("../../../../examples/echo-contract/capsule.json")
        .replace(PLACEHOLDER_DIGEST, &release.0)
        .replace(
            "\"name\": \"examples/echo\"",
            &format!("\"name\": \"tests/{name}\""),
        );
    let manifest = JsonManifestCodec::default()
        .decode_capsule(manifest_source.as_bytes())
        .expect("test capsule must decode");

    CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference(format!("local://tests/{name}")),
            release_digest: release,
            media_type: "application/vnd.wasm.component.v1+wasm".to_owned(),
            size_bytes: u64::try_from(bytes.len()).expect("test component length must fit u64"),
            publisher: None,
            layers: Vec::new(),
            annotations: Metadata::new(),
        },
        manifest,
        contracts: vec![contract_fixture()],
        component_bytes: bytes.to_vec(),
    }
}

fn contract_fixture() -> ContractDescriptor {
    let mut attributes = Metadata::new();
    attributes.insert("latent.dev/test".to_owned(), "catalog".to_owned());
    ContractDescriptor {
        id: ContractId("tests:catalog/api@0.1.0".to_owned()),
        package_name: "tests:catalog".to_owned(),
        semantic_version: "0.1.0".to_owned(),
        interfaces: vec![InterfaceDescriptor {
            id: InterfaceId("tests:catalog/api@0.1.0".to_owned()),
            functions: vec![FunctionDescriptor {
                id: FunctionId("round-trip".to_owned()),
                name: "round-trip".to_owned(),
                asynchronous: true,
                parameters: vec![FieldDescriptor {
                    name: "input".to_owned(),
                    value_type: ValueType::List(Box::new(ValueType::Option(Box::new(
                        ValueType::String,
                    )))),
                    documentation: Some("input field".to_owned()),
                }],
                results: vec![FieldDescriptor {
                    name: "output".to_owned(),
                    value_type: ValueType::Result {
                        ok: Some(Box::new(ValueType::Bytes)),
                        error: Some(Box::new(ValueType::Record("failure".to_owned()))),
                    },
                    documentation: None,
                }],
                documentation: Some("round-trip function".to_owned()),
                attributes,
            }],
            documentation: Some("catalog test interface".to_owned()),
            digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                .to_owned(),
        }],
        dependencies: vec![ContractId("latent:context/context@0.1.0".to_owned())],
        digest: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            .to_owned(),
    }
}

#[test]
fn sha256_matches_known_vector() {
    assert_eq!(
        release_digest(b"abc").0,
        "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    );
}

#[test]
fn publish_duplicate_resolve_fetch_and_restart_round_trip() {
    let temp = TempRoot::new();
    let expected = artifact("round-trip", b"component-round-trip");
    let digest = expected.descriptor.release_digest.clone();

    let repo = repository(temp.path());
    let published = block_on(repo.publish(expected.clone())).expect("first publish must succeed");
    assert_eq!(published, expected.descriptor);
    assert_eq!(
        block_on(repo.publish(expected.clone())).expect("identical publish must be idempotent"),
        expected.descriptor
    );

    let resolved = block_on(repo.resolve(&ArtifactQuery {
        reference: Some(expected.descriptor.reference.clone()),
        release_digest: Some(digest.clone()),
        media_type: Some(expected.descriptor.media_type.clone()),
    }))
    .expect("resolve must succeed")
    .expect("published descriptor must resolve");
    assert_eq!(resolved, expected.descriptor);
    assert_eq!(
        block_on(repo.fetch(&digest)).expect("fetch must succeed"),
        expected
    );

    drop(repo);
    let reopened = repository(temp.path());
    assert_eq!(
        block_on(reopened.fetch(&digest)).expect("restart fetch must succeed"),
        expected
    );
}

#[test]
fn resolve_requires_all_supplied_query_fields_to_match() {
    let temp = TempRoot::new();
    let expected = artifact("query", b"query-component");
    let digest = expected.descriptor.release_digest.clone();
    let repo = repository(temp.path());
    block_on(repo.publish(expected)).expect("publish must succeed");

    assert!(block_on(repo.resolve(&ArtifactQuery {
        reference: Some(ArtifactReference("local://tests/wrong".to_owned())),
        release_digest: Some(digest),
        media_type: None,
    }))
    .expect("resolve must succeed")
    .is_none());
}

#[test]
fn digest_disagreement_is_corrupt_and_not_visible() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let mut invalid = artifact("bad-digest", b"component-one");
    invalid.manifest.component_digest = release_digest(b"component-two");

    let failure = block_on(repo.publish(invalid)).expect_err("digest disagreement must fail");
    assert_eq!(failure.code, PlatformErrorCode::CorruptArtifact);
    assert!(block_on(repo.list(None, 10))
        .expect("list must succeed")
        .entries
        .is_empty());
}

#[test]
fn missing_and_corrupt_entries_are_rejected() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let missing = release_digest(b"missing");
    assert_eq!(
        block_on(repo.fetch(&missing))
            .expect_err("unknown release must fail")
            .code,
        PlatformErrorCode::NotFound
    );

    let expected = artifact("corrupt", b"component-before-corruption");
    let release = expected.descriptor.release_digest.clone();
    block_on(repo.publish(expected)).expect("publish before corruption must succeed");
    let release_dir = temp.path().join("releases").join(
        release
            .0
            .strip_prefix("sha256:")
            .expect("test digest must use sha256"),
    );
    fs::write(release_dir.join("component.wasm"), b"corrupted")
        .expect("test must corrupt stored component");

    assert_eq!(
        block_on(repo.fetch(&release))
            .expect_err("corrupt release must fail")
            .code,
        PlatformErrorCode::CorruptArtifact
    );
}

#[test]
fn missing_file_in_completed_entry_is_corrupt() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let expected = artifact("missing-file", b"component-missing-file");
    let release = expected.descriptor.release_digest.clone();
    block_on(repo.publish(expected)).expect("publish must succeed");
    let release_dir = temp.path().join("releases").join(
        release
            .0
            .strip_prefix("sha256:")
            .expect("test digest must use sha256"),
    );
    fs::remove_file(release_dir.join("manifest.json")).expect("manifest must be removed");

    assert_eq!(
        block_on(repo.fetch(&release))
            .expect_err("missing completed data must fail")
            .code,
        PlatformErrorCode::CorruptArtifact
    );
}

#[test]
fn conflicting_metadata_under_existing_digest_is_rejected() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let expected = artifact("conflict", b"same-component");
    block_on(repo.publish(expected.clone())).expect("first publish must succeed");

    let mut conflicting = expected;
    conflicting.descriptor.reference = ArtifactReference("local://tests/other".to_owned());
    assert_eq!(
        block_on(repo.publish(conflicting))
            .expect_err("conflicting metadata must fail")
            .code,
        PlatformErrorCode::AlreadyExists
    );
}

#[test]
fn listing_is_bounded_deterministic_and_paginated_from_memory() {
    let temp = TempRoot::new();
    let repo = DirectoryArtifactRepository::open(
        temp.path(),
        DirectoryArtifactRepositoryConfig {
            max_index_entries: 100,
            max_page_size: 2,
        },
    )
    .expect("repository must open");

    for index in 0..5 {
        block_on(repo.publish(artifact(
            &format!("page-{index}"),
            format!("component-{index}").as_bytes(),
        )))
        .expect("publish must succeed");
    }

    let first = block_on(repo.list(None, 100)).expect("first page must list");
    assert_eq!(first.entries.len(), 2);
    assert!(first.next_after.is_some());
    assert!(first.entries[0].release_digest < first.entries[1].release_digest);

    let second = block_on(repo.list(first.next_after.as_ref(), 100)).expect("second page must list");
    assert_eq!(second.entries.len(), 2);
    assert!(second.next_after.is_some());
    assert!(first.entries[1].release_digest < second.entries[0].release_digest);

    let third = block_on(repo.list(second.next_after.as_ref(), 100)).expect("third page must list");
    assert_eq!(third.entries.len(), 1);
    assert!(third.next_after.is_none());
}

#[test]
fn zero_list_limit_is_rejected() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    assert_eq!(
        block_on(repo.list(None, 0))
            .expect_err("zero page size must fail")
            .code,
        PlatformErrorCode::InvalidArgument
    );
}

#[test]
fn index_capacity_is_enforced_before_second_release_is_written() {
    let temp = TempRoot::new();
    let repo = DirectoryArtifactRepository::open(
        temp.path(),
        DirectoryArtifactRepositoryConfig {
            max_index_entries: 1,
            max_page_size: 1,
        },
    )
    .expect("repository must open");
    block_on(repo.publish(artifact("first", b"first-component"))).expect("first publish");
    assert_eq!(
        block_on(repo.publish(artifact("second", b"second-component")))
            .expect_err("second publish must exceed index bound")
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(
        fs::read_dir(temp.path().join("releases"))
            .expect("release directory must be readable")
            .count(),
        1
    );
}

#[test]
fn concurrent_identical_publishers_observe_one_complete_release() {
    let temp = TempRoot::new();
    let repo = Arc::new(repository(temp.path()));
    let expected = artifact("concurrent", b"concurrent-component");
    let digest = expected.descriptor.release_digest.clone();
    let barrier = Arc::new(Barrier::new(33));
    let mut tasks = Vec::new();

    for _ in 0..32 {
        let repo = Arc::clone(&repo);
        let artifact = expected.clone();
        let barrier = Arc::clone(&barrier);
        tasks.push(thread::spawn(move || {
            barrier.wait();
            block_on(repo.publish(artifact))
        }));
    }
    barrier.wait();
    for task in tasks {
        assert_eq!(
            task.join()
                .expect("publisher thread must complete")
                .expect("identical concurrent publish must succeed"),
            expected.descriptor
        );
    }

    assert_eq!(
        block_on(repo.list(None, 10))
            .expect("list must succeed")
            .entries
            .len(),
        1
    );
    assert_eq!(
        block_on(repo.fetch(&digest)).expect("fetch must succeed"),
        expected
    );
}

#[test]
fn readers_never_observe_partial_publication() {
    let temp = TempRoot::new();
    let repo = Arc::new(repository(temp.path()));
    let expected = artifact("atomic", &vec![0x5a; 2 * 1024 * 1024]);
    let query = ArtifactQuery {
        reference: None,
        release_digest: Some(expected.descriptor.release_digest.clone()),
        media_type: None,
    };
    let writer_repo = Arc::clone(&repo);
    let writer_artifact = expected.clone();
    let writer = thread::spawn(move || block_on(writer_repo.publish(writer_artifact)));

    loop {
        match block_on(repo.resolve(&query)).expect("resolve must not fail during publish") {
            Some(descriptor) => {
                assert_eq!(descriptor, expected.descriptor);
                assert_eq!(
                    block_on(repo.fetch(&descriptor.release_digest))
                        .expect("visible release must be complete"),
                    expected
                );
                break;
            }
            None => thread::yield_now(),
        }
    }
    writer
        .join()
        .expect("writer thread must complete")
        .expect("writer must succeed");
}

#[test]
fn restart_cleans_incomplete_temporary_writes_without_exposing_them() {
    let temp = TempRoot::new();
    drop(repository(temp.path()));

    let orphan = temp.path().join(".tmp").join("interrupted-publish");
    fs::create_dir_all(&orphan).expect("orphan directory must be created");
    fs::write(orphan.join("component.wasm"), b"partial")
        .expect("partial file must be created");

    let reopened = repository(temp.path());
    assert!(!orphan.exists());
    assert!(block_on(reopened.list(None, 10))
        .expect("list must succeed")
        .entries
        .is_empty());
}

#[test]
fn restart_ignores_incomplete_final_directory_without_complete_marker() {
    let temp = TempRoot::new();
    drop(repository(temp.path()));
    let release = release_digest(b"incomplete-final");
    let incomplete = temp.path().join("releases").join(
        release
            .0
            .strip_prefix("sha256:")
            .expect("test digest must use sha256"),
    );
    fs::create_dir_all(&incomplete).expect("incomplete final directory must be created");
    fs::write(incomplete.join("component.wasm"), b"partial")
        .expect("partial component must be written");

    let reopened = repository(temp.path());
    assert!(block_on(reopened.list(None, 10))
        .expect("list must succeed")
        .entries
        .is_empty());
}

#[cfg(target_os = "linux")]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct ProcessTopology {
    process_id: u32,
    child_processes: usize,
    threads: u64,
    sockets: u64,
}

#[cfg(target_os = "linux")]
fn process_topology() -> ProcessTopology {
    let process_id = std::process::id();
    let status = fs::read_to_string("/proc/self/status").expect("Linux process status must exist");
    let threads = status
        .lines()
        .find_map(|line| line.strip_prefix("Threads:"))
        .and_then(|value| value.split_whitespace().next())
        .and_then(|value| value.parse().ok())
        .expect("Linux thread count must parse");
    let children = fs::read_to_string(format!("/proc/self/task/{process_id}/children"))
        .expect("Linux child process list must exist");
    let child_processes = children.split_whitespace().count();
    let sockets = fs::read_dir("/proc/self/fd")
        .expect("Linux file-descriptor directory must exist")
        .filter_map(Result::ok)
        .filter(|entry| {
            fs::read_link(entry.path())
                .ok()
                .is_some_and(|target| target.to_string_lossy().starts_with("socket:["))
        })
        .count() as u64;
    ProcessTopology {
        process_id,
        child_processes,
        threads,
        sockets,
    }
}

#[cfg(target_os = "linux")]
#[test]
fn one_hundred_thousand_dormant_records_do_not_create_runtime_topology() {
    let before = process_topology();
    let mut index = CatalogIndex::default();
    for value in 0_u32..100_000 {
        let digest = ReleaseDigest(format!("sha256:{value:064x}"));
        index
            .insert(ArtifactDescriptor {
                reference: ArtifactReference(format!("local://synthetic/{value}")),
                release_digest: digest,
                media_type: "application/vnd.wasm.component.v1+wasm".to_owned(),
                size_bytes: 0,
                publisher: None,
                layers: Vec::new(),
                annotations: Metadata::new(),
            })
            .expect("synthetic descriptor must register");
    }
    assert_eq!(index.by_digest.len(), 100_000);
    assert_eq!(index.by_reference.len(), 100_000);
    assert_eq!(process_topology(), before);
}
