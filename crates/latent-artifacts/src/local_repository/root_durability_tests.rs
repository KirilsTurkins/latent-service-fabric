use latent_core::PlatformError;

use super::super::root_durability::faults::Guard;
use super::*;

fn open(root: &Path) -> Result<DirectoryArtifactRepository, PlatformError> {
    DirectoryArtifactRepository::open(root, DirectoryArtifactRepositoryConfig::default())
}

fn ancestors(root: &Path) -> Vec<PathBuf> {
    root.ancestors().map(Path::to_owned).collect()
}

fn assert_uncertain(failure: &PlatformError) {
    assert_eq!(failure.code, PlatformErrorCode::Unavailable);
    assert_eq!(failure.message, "catalog-path-durability-uncertain");
    assert!(failure.retryable);
}

fn assert_release(repo: &DirectoryArtifactRepository, expected: &CapsuleArtifact) {
    let digest = &expected.descriptor.release_digest;
    assert_eq!(block_on(repo.fetch(digest)).expect("fetch"), *expected);
    assert_eq!(
        block_on(repo.resolve(&ArtifactQuery {
            reference: Some(expected.descriptor.reference.clone()),
            release_digest: None,
            media_type: None,
        }))
        .expect("resolve"),
        Some(expected.descriptor.clone())
    );
    assert_eq!(
        block_on(repo.list(None, 2)).expect("list").entries,
        vec![expected.descriptor.clone()]
    );
}

#[test]
fn nested_root_initialization_syncs_every_ancestor_leaf_first() {
    let scratch = TempRoot::new();
    let root = fs::canonicalize(scratch.path())
        .expect("absolute scratch")
        .join("one/two/catalog");
    let guard = Guard::new(None);
    let repo = open(&root).expect("nested root initialization");
    assert_eq!(guard.events(), ancestors(&root));
    assert!(root.join(".catalog.lock").is_file());
    assert!(root.join("releases").is_dir());
    assert!(root.join(".tmp").is_dir());
    assert!(block_on(repo.list(None, 1))
        .expect("empty catalog")
        .entries
        .is_empty());
}

#[test]
fn every_ancestor_failure_stops_initialization_and_retry_resyncs_existing_paths() {
    let scratch = TempRoot::new();
    let base = fs::canonicalize(scratch.path()).expect("absolute scratch");
    let depth = ancestors(&base.join("one/two/catalog")).len();
    for failed_index in 0..depth {
        let root = base.join(format!("case-{failed_index}/two/catalog"));
        let expected = ancestors(&root);
        let guard = Guard::new(Some(expected[failed_index].clone()));
        assert_uncertain(&open(&root).expect_err("ancestor sync must fail open"));
        assert_eq!(guard.events(), expected[..=failed_index]);
        assert!(root.is_dir(), "failed creation remains available for retry");
        for name in [".catalog.lock", "releases", ".tmp"] {
            assert!(!root.join(name).exists(), "initialization must not proceed");
        }
        drop(guard);

        let guard = Guard::new(None);
        drop(open(&root).expect("retry must complete initialization"));
        assert_eq!(guard.events(), expected);
        drop(guard);

        // A successful open also repeats the chain for an established root.
        let guard = Guard::new(None);
        drop(open(&root).expect("established root"));
        assert_eq!(guard.events(), expected);
    }
}

#[test]
fn relative_nested_roots_retry_using_the_complete_absolute_chain() {
    // Never mutate the process-wide working directory while other tests run.
    let scratch = TempRoot::under(Path::new("."));
    let root = scratch.path().join("one/./two/catalog");
    assert!(root.is_relative());
    let absolute = fs::canonicalize(scratch.path())
        .expect("absolute scratch")
        .join("one/two/catalog");
    let expected = ancestors(&absolute);
    let guard = Guard::new(Some(expected[2].clone()));
    assert_uncertain(&open(&root).expect_err("relative ancestor sync failure"));
    assert_eq!(guard.events(), expected[..=2]);
    drop(guard);

    let guard = Guard::new(None);
    let repo = open(&root).expect("relative root retry");
    assert_eq!(guard.events(), expected);
    assert_eq!(repo.root(), absolute, "retain the owned canonical identity");
    assert!(block_on(repo.list(None, 1))
        .expect("empty catalog")
        .entries
        .is_empty());
}

#[test]
fn existing_root_failure_preserves_release_and_exclusive_ownership_on_retry() {
    let scratch = TempRoot::new();
    let root = fs::canonicalize(scratch.path())
        .expect("absolute scratch")
        .join("one/two/catalog");
    let expected = artifact("durable-root", b"tiny durable release");
    let first = open(&root).expect("first owner");
    block_on(first.publish(expected.clone())).expect("tiny publication");
    let active_stage = root.join(".tmp/active-publisher");
    fs::create_dir(&active_stage).expect("active stage");
    fs::write(active_stage.join("component.wasm"), b"active").expect("active data");

    let guard = Guard::new(None);
    let failure = open(&root).expect_err("second live owner must be rejected");
    assert_eq!(failure.code, PlatformErrorCode::Unavailable);
    assert_eq!(
        failure.message,
        "catalog root is already owned by another live repository handle"
    );
    assert_eq!(guard.events(), ancestors(&root));
    assert!(
        active_stage.exists(),
        "rejected opener cannot clean live staging"
    );
    assert_release(&first, &expected);
    drop(guard);
    drop(first);

    let release = root.join("releases").join(
        expected
            .descriptor
            .release_digest
            .0
            .strip_prefix("sha256:")
            .expect("SHA-256 digest"),
    );
    let persisted = [
        "metadata.json",
        "manifest.json",
        "component.wasm",
        "COMPLETE",
    ]
    .map(|name| {
        (
            name,
            fs::read(release.join(name)).expect("persisted release"),
        )
    });
    let guard = Guard::new(Some(root.parent().expect("nested root parent").to_owned()));
    assert_uncertain(&open(&root).expect_err("established root sync failure"));
    assert!(
        active_stage.exists(),
        "failed opening cannot clean crash debris"
    );
    for (name, bytes) in persisted {
        assert_eq!(
            fs::read(release.join(name)).expect("preserved release"),
            bytes
        );
    }
    drop(guard);

    let guard = Guard::new(None);
    let reopened = open(&root).expect("retry acquires ownership and recovers");
    assert_eq!(guard.events(), ancestors(&root));
    assert!(!active_stage.exists(), "new owner cleans abandoned staging");
    assert_release(&reopened, &expected);
    assert_eq!(
        open(&root).expect_err("retry owns root exclusively").code,
        PlatformErrorCode::Unavailable
    );
    drop(guard);
    drop(reopened);
    assert_release(
        &open(&root).expect("restart after successful retry"),
        &expected,
    );
}

#[test]
fn root_sync_failpoints_are_local_to_the_installing_thread() {
    let scratch = TempRoot::new();
    let root = fs::canonicalize(scratch.path())
        .expect("absolute scratch")
        .join("catalog");
    let guard = Guard::new(Some(root.clone()));
    thread::scope(|scope| {
        scope
            .spawn(|| drop(open(&root).expect("other thread has no failpoint")))
            .join()
            .expect("other opener completes");
    });
    assert!(guard.events().is_empty());
    assert_uncertain(&open(&root).expect_err("installing thread retains its failpoint"));
    assert_eq!(guard.events(), vec![root.clone()]);
    drop(open(&root).expect("failpoint fires only once"));
    let mut expected = vec![root.clone()];
    expected.extend(ancestors(&root));
    assert_eq!(guard.events(), expected);
}

#[test]
fn root_sync_fault_guard_clears_thread_state_during_unwind() {
    let result = std::panic::catch_unwind(|| {
        let _guard = Guard::new(Some(PathBuf::from("unused-root-failpoint")));
        panic!("exercise fault guard unwinding");
    });
    assert!(result.is_err());
    let guard = Guard::new(None);
    assert!(guard.events().is_empty());
}

#[test]
fn root_creation_errors_keep_the_existing_error_semantics() {
    let scratch = TempRoot::new();
    let root = scratch.path().join("file");
    fs::write(&root, b"not a directory").expect("conflicting file");
    let guard = Guard::new(None);
    let failure = open(&root).expect_err("root cannot be a file");
    assert_eq!(failure.code, PlatformErrorCode::Internal);
    assert!(!failure.retryable);
    assert!(failure
        .message
        .starts_with("catalog filesystem operation failed:"));
    assert!(guard.events().is_empty());
    assert_eq!(
        fs::read(root).expect("existing file unchanged"),
        b"not a directory"
    );
}
#[path = "root_durability_restart_tests.rs"]
mod restart;
