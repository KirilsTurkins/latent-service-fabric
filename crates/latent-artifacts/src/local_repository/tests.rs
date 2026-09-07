#[path = "integrity_tests.rs"]
mod integrity;
#[path = "integrity_publication_tests.rs"]
mod integrity_publication;
#[cfg(unix)]
#[path = "lock_release_tests.rs"]
mod lock_release;
#[path = "regression_tests.rs"]
mod regressions;
#[path = "root_durability_tests.rs"]
mod root_durability;
#[path = "visibility_tests.rs"]
mod visibility;

use std::fs;
use std::future::Future;
use std::path::{Path, PathBuf};
use std::pin::Pin;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Barrier};
use std::task::{Context, Poll, Wake, Waker};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use latent_contracts::{
    ContractDescriptor, FieldDescriptor, FunctionDescriptor, InterfaceDescriptor, ValueType,
};
use latent_core::{
    ArtifactReference, ContractId, FunctionId, InterfaceId, Metadata, PlatformErrorCode,
    ReleaseDigest,
};
use latent_manifest::{
    JsonManifestCodec, ManifestCodec, ManifestValidator, Phase1ManifestValidator,
};

use super::{
    release_digest, ArtifactDescriptor, ArtifactQuery, ArtifactRepository, CapsuleArtifact,
    DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig,
};
use crate::ArtifactLayer;

const PLACEHOLDER_DIGEST: &str =
    "sha256:1111111111111111111111111111111111111111111111111111111111111111";
static NEXT_TEMP_ID: AtomicU64 = AtomicU64::new(0);

struct TempRoot(PathBuf);

impl TempRoot {
    fn new() -> Self {
        Self::under(&std::env::temp_dir())
    }

    fn under(parent: &Path) -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("test clock must be after Unix epoch")
            .as_nanos();
        let sequence = NEXT_TEMP_ID.fetch_add(1, Ordering::Relaxed);
        let path = parent.join(format!(
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
    // Keep the example's name, tenant, world and exports in the same scope.
    let manifest_source = include_str!("../../../../examples/echo-contract/capsule.json")
        .replace(PLACEHOLDER_DIGEST, &release.0);
    let manifest = JsonManifestCodec::default()
        .decode_capsule(manifest_source.as_bytes())
        .expect("test capsule must decode");
    Phase1ManifestValidator::new()
        .validate_capsule(&manifest)
        .expect("test capsule must satisfy semantic validation");
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

fn release_dir(root: &Path, digest: &ReleaseDigest) -> PathBuf {
    root.join("releases").join(
        digest
            .0
            .strip_prefix("sha256:")
            .expect("test digest must use sha256"),
    )
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
    assert_eq!(
        block_on(repo.publish(expected.clone())).expect("first publish"),
        expected.descriptor
    );
    assert_eq!(
        block_on(repo.publish(expected.clone())).expect("duplicate publish"),
        expected.descriptor
    );
    assert_eq!(block_on(repo.fetch(&digest)).expect("fetch"), expected);
    drop(repo);
    let reopened = repository(temp.path());
    assert_eq!(
        block_on(reopened.fetch(&digest)).expect("restart fetch"),
        expected
    );
}

#[test]
fn digest_disagreement_is_corrupt_and_not_visible() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let mut invalid = artifact("bad-digest", b"component-one");
    invalid.manifest.component_digest = release_digest(b"component-two");
    let failure = block_on(repo.publish(invalid)).expect_err("digest mismatch must fail");
    assert_eq!(failure.code, PlatformErrorCode::CorruptArtifact);
    assert!(block_on(repo.list(None, 10))
        .expect("list")
        .entries
        .is_empty());
}

#[test]
fn missing_and_corrupt_entries_are_rejected() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let missing = release_digest(b"missing");
    assert_eq!(
        block_on(repo.fetch(&missing)).expect_err("missing").code,
        PlatformErrorCode::NotFound
    );
    let expected = artifact("corrupt", b"component-before-corruption");
    let release = expected.descriptor.release_digest.clone();
    block_on(repo.publish(expected)).expect("publish");
    fs::write(
        release_dir(temp.path(), &release).join("component.wasm"),
        b"corrupted",
    )
    .expect("corrupt component");
    assert_eq!(
        block_on(repo.fetch(&release)).expect_err("corruption").code,
        PlatformErrorCode::CorruptArtifact
    );
}

#[test]
fn full_contract_metadata_round_trips() {
    let temp = TempRoot::new();
    let expected = artifact("contracts", b"contracts-component");
    let digest = expected.descriptor.release_digest.clone();
    let repo = repository(temp.path());
    block_on(repo.publish(expected.clone())).expect("publish");
    drop(repo);
    let reopened = repository(temp.path());
    assert_eq!(
        block_on(reopened.fetch(&digest)).expect("fetch").contracts,
        expected.contracts
    );
}

#[test]
fn post_rename_parent_sync_failure_is_not_success_and_retry_repairs_visibility() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let expected = artifact("sync-recovery", b"sync-recovery-component");
    let digest = expected.descriptor.release_digest.clone();
    repo.inject_parent_sync_failure_once();
    assert_eq!(
        block_on(repo.publish(expected.clone()))
            .expect_err("injected durability failure must be returned")
            .code,
        PlatformErrorCode::Internal
    );
    assert!(block_on(repo.resolve(&ArtifactQuery {
        reference: None,
        release_digest: Some(digest.clone()),
        media_type: None,
    }))
    .expect("resolve after failure")
    .is_none());
    assert_eq!(
        block_on(repo.fetch(&digest))
            .expect_err("fetch after failure")
            .code,
        PlatformErrorCode::NotFound
    );
    assert!(block_on(repo.list(None, 10))
        .expect("list after failure")
        .entries
        .is_empty());
    assert_eq!(
        block_on(repo.publish(expected.clone())).expect("retry must durably adopt"),
        expected.descriptor
    );
    assert!(block_on(repo.resolve(&ArtifactQuery {
        reference: None,
        release_digest: Some(digest.clone()),
        media_type: None,
    }))
    .expect("resolve after retry")
    .is_some());
    assert_eq!(
        block_on(repo.fetch(&digest)).expect("fetch after retry"),
        expected
    );
    assert_eq!(
        block_on(repo.list(None, 10))
            .expect("list after retry")
            .entries
            .len(),
        1
    );
}

#[test]
fn root_is_exclusively_owned_before_cleanup_and_rebuild() {
    let temp = TempRoot::new();
    let first = repository(temp.path());
    let active_stage = temp.path().join(".tmp").join("active-publisher");
    fs::create_dir_all(&active_stage).expect("active stage");
    fs::write(active_stage.join("component.wasm"), b"active").expect("active data");
    let failure = DirectoryArtifactRepository::open(
        temp.path(),
        DirectoryArtifactRepositoryConfig::default(),
    )
    .expect_err("second live opener must fail");
    assert_eq!(failure.code, PlatformErrorCode::Unavailable);
    assert!(
        active_stage.exists(),
        "rejected opener must not run cleanup"
    );
    drop(first);
    let reopened = repository(temp.path());
    assert!(
        !active_stage.exists(),
        "new owner cleans abandoned staging data"
    );
    drop(reopened);
}

#[test]
fn exclusive_root_ownership_prevents_conflicting_independent_handles() {
    let temp = TempRoot::new();
    let first = repository(temp.path());
    block_on(first.publish(artifact("same-reference", b"one"))).expect("first publish");
    assert_eq!(
        DirectoryArtifactRepository::open(
            temp.path(),
            DirectoryArtifactRepositoryConfig::default()
        )
        .expect_err("second handle cannot publish identical or conflicting releases")
        .code,
        PlatformErrorCode::Unavailable
    );
    drop(first);
    let reopened = repository(temp.path());
    assert_eq!(
        block_on(reopened.list(None, 10))
            .expect("reopen list")
            .entries
            .len(),
        1
    );
}

#[test]
fn listing_is_entry_and_byte_bounded_and_deterministic() {
    let temp = TempRoot::new();
    let repo = DirectoryArtifactRepository::open(
        temp.path(),
        DirectoryArtifactRepositoryConfig {
            max_page_size: 2,
            max_page_bytes: 16 * 1024,
            max_descriptor_bytes: 8 * 1024,
            ..DirectoryArtifactRepositoryConfig::default()
        },
    )
    .expect("open");
    for index in 0..5 {
        block_on(repo.publish(artifact(
            &format!("page-{index}"),
            format!("component-{index}").as_bytes(),
        )))
        .expect("publish");
    }
    let first = block_on(repo.list(None, 100)).expect("first page");
    assert_eq!(first.entries.len(), 2);
    assert!(first.next_after.is_some());
    assert!(first.entries[0].release_digest < first.entries[1].release_digest);
    let second = block_on(repo.list(first.next_after.as_ref(), 100)).expect("second page");
    assert_eq!(second.entries.len(), 2);
    let third = block_on(repo.list(second.next_after.as_ref(), 100)).expect("third page");
    assert_eq!(third.entries.len(), 1);
    assert!(third.next_after.is_none());
}

#[test]
fn oversized_descriptor_fields_are_rejected_before_visibility() {
    for variant in ["reference", "annotation", "layer"] {
        let temp = TempRoot::new();
        let repo = DirectoryArtifactRepository::open(
            temp.path(),
            DirectoryArtifactRepositoryConfig {
                max_descriptor_bytes: 512,
                max_page_bytes: 1024,
                max_metadata_bytes: 2048,
                ..DirectoryArtifactRepositoryConfig::default()
            },
        )
        .expect("open");
        let mut value = artifact(variant, b"bounded-component");
        match variant {
            "reference" => {
                value.descriptor.reference =
                    ArtifactReference(format!("local://{}", "x".repeat(2048)))
            }
            "annotation" => {
                value
                    .descriptor
                    .annotations
                    .insert("large".to_owned(), "x".repeat(2048));
            }
            "layer" => value.descriptor.layers.push(ArtifactLayer {
                media_type: "x".repeat(2048),
                digest: release_digest(b"layer").0,
                size_bytes: 1,
                annotations: Metadata::new(),
            }),
            _ => unreachable!(),
        }
        assert_eq!(
            block_on(repo.publish(value))
                .expect_err("oversized descriptor")
                .code,
            PlatformErrorCode::ResourceExhausted
        );
        assert!(block_on(repo.list(None, 10))
            .expect("list")
            .entries
            .is_empty());
    }
}

#[test]
fn aggregate_index_byte_budget_is_enforced_before_persistence() {
    let temp = TempRoot::new();
    let repo = DirectoryArtifactRepository::open(
        temp.path(),
        DirectoryArtifactRepositoryConfig {
            max_index_entries: 100,
            max_index_bytes: 3_000,
            ..DirectoryArtifactRepositoryConfig::default()
        },
    )
    .expect("open");
    block_on(repo.publish(artifact("budget-one", b"budget-one"))).expect("first release fits");
    assert_eq!(
        block_on(repo.publish(artifact("budget-two", b"budget-two")))
            .expect_err("aggregate budget must reject second release")
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(
        block_on(repo.list(None, 10)).expect("list").entries.len(),
        1
    );
}

#[test]
fn oversized_persisted_metadata_is_rejected_before_allocation_on_reopen() {
    let temp = TempRoot::new();
    let expected = artifact("oversized-reopen", b"oversized-reopen-component");
    let digest = expected.descriptor.release_digest.clone();
    let repo = repository(temp.path());
    block_on(repo.publish(expected)).expect("publish");
    drop(repo);
    fs::write(
        release_dir(temp.path(), &digest).join("metadata.json"),
        vec![b'x'; 8192],
    )
    .expect("replace metadata");
    let failure = DirectoryArtifactRepository::open(
        temp.path(),
        DirectoryArtifactRepositoryConfig {
            max_metadata_bytes: 1024,
            max_descriptor_bytes: 512,
            max_page_bytes: 1024,
            ..DirectoryArtifactRepositoryConfig::default()
        },
    )
    .expect_err("oversized persisted metadata must fail bounded reopen");
    assert_eq!(failure.code, PlatformErrorCode::ResourceExhausted);
}

#[test]
fn incomplete_directories_do_not_consume_completed_index_quota() {
    let temp = TempRoot::new();
    let config = DirectoryArtifactRepositoryConfig {
        max_index_entries: 1,
        max_recovery_directories: 16,
        ..DirectoryArtifactRepositoryConfig::default()
    };
    let repo = DirectoryArtifactRepository::open(temp.path(), config).expect("open");
    block_on(repo.publish(artifact("complete", b"complete-component"))).expect("publish");
    drop(repo);
    for index in 0..8 {
        fs::create_dir_all(
            temp.path()
                .join("releases")
                .join(format!("incomplete-{index:02}")),
        )
        .expect("incomplete directory");
    }
    let reopened = DirectoryArtifactRepository::open(temp.path(), config)
        .expect("incomplete debris must not consume completed quota");
    assert_eq!(
        block_on(reopened.list(None, 10))
            .expect("list")
            .entries
            .len(),
        1
    );
}

#[test]
fn separate_recovery_scan_bound_is_enforced() {
    let temp = TempRoot::new();
    drop(repository(temp.path()));
    for index in 0..3 {
        fs::create_dir_all(temp.path().join("releases").join(format!("debris-{index}")))
            .expect("debris");
    }
    assert_eq!(
        DirectoryArtifactRepository::open(
            temp.path(),
            DirectoryArtifactRepositoryConfig {
                max_index_entries: 100,
                max_recovery_directories: 2,
                ..DirectoryArtifactRepositoryConfig::default()
            }
        )
        .expect_err("separate recovery scan bound")
        .code,
        PlatformErrorCode::ResourceExhausted
    );
}

#[test]
fn concurrent_identical_publishers_on_one_owned_handle_observe_one_release() {
    let temp = TempRoot::new();
    let repo = Arc::new(repository(temp.path()));
    let expected = artifact("concurrent", b"concurrent-component");
    let barrier = Arc::new(Barrier::new(17));
    let mut tasks = Vec::new();
    for _ in 0..16 {
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
            task.join().expect("publisher join").expect("publish"),
            expected.descriptor
        );
    }
    assert_eq!(
        block_on(repo.list(None, 10)).expect("list").entries.len(),
        1
    );
}

#[test]
fn restart_cleans_abandoned_temporary_writes() {
    let temp = TempRoot::new();
    drop(repository(temp.path()));
    let orphan = temp.path().join(".tmp").join("interrupted-publish");
    fs::create_dir_all(&orphan).expect("orphan");
    fs::write(orphan.join("component.wasm"), b"partial").expect("partial");
    let reopened = repository(temp.path());
    assert!(!orphan.exists());
    assert!(block_on(reopened.list(None, 10))
        .expect("list")
        .entries
        .is_empty());
}

#[test]
fn one_hundred_thousand_index_adoptions_are_bounded() {
    // This is deliberately only an index unit test. Durable publication and
    // measured topology belong to latentd's isolated catalog_scale acceptance.
    let temp = TempRoot::new();
    let repo = DirectoryArtifactRepository::open(
        temp.path(),
        DirectoryArtifactRepositoryConfig {
            max_index_entries: 100_000,
            max_index_bytes: 256 * 1024 * 1024,
            ..DirectoryArtifactRepositoryConfig::default()
        },
    )
    .expect("open index fixture");
    for value in 0_u32..100_000 {
        let descriptor = ArtifactDescriptor {
            reference: ArtifactReference(format!("local://synthetic/{value}")),
            release_digest: ReleaseDigest(format!("sha256:{value:064x}")),
            media_type: "application/vnd.wasm.component.v1+wasm".to_owned(),
            size_bytes: 0,
            publisher: None,
            layers: Vec::new(),
            annotations: Metadata::new(),
        };
        repo.preflight_adoption(&descriptor)
            .expect("index preflight");
        repo.finalize_adoption(descriptor).expect("index adoption");
    }
    assert_eq!(repo.index.read().expect("index").by_digest.len(), 100_000);
    assert!(repo.index.read().expect("index").accounted_bytes <= repo.config.max_index_bytes);
}
