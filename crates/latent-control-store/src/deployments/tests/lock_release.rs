use super::super::OwnerLock;
use super::*;

#[test]
#[allow(clippy::used_underscore_binding)] // Inspect the private RAII field to model inheritance.
fn dropping_owner_releases_lock_while_duplicate_descriptor_remains_open() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let digest = releases.add("one");
    let expected = deployment("blue", "alice", &digest);
    let owner = open(&root, &releases);
    run(owner.apply(expected.clone())).expect("apply");
    // Duplicating the private lock descriptor reproduces Unix fork inheritance
    // without a timing-dependent child process or unsafe post-fork code.
    let inherited = owner
        ._owner_lock
        .0
        .try_clone()
        .expect("duplicate descriptor");
    assert_code(
        run(Store::open(&root.0, releases.clone(), Limits::default())),
        Code::Unavailable,
    );
    drop(owner);
    let replacement = open(&root, &releases);
    assert_eq!(replacement.generation(), RouteGeneration(1));
    assert_eq!(
        run(DeploymentStore::get(&replacement, &expected.id)).expect("preserved deployment"),
        Some(expected),
    );
    drop(inherited);
    assert_code(
        run(Store::open(&root.0, releases, Limits::default())),
        Code::Unavailable,
    );
}

#[test]
fn initialization_error_releases_lock_before_repository_construction() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let mut inherited = None;
    let result = fail_after_locking(&root.0, &mut inherited);
    assert_eq!(result, Err("controlled initialization failure"));
    let replacement = open(&root, &releases);
    drop(inherited);
    assert_code(
        run(Store::open(&root.0, releases, Limits::default())),
        Code::Unavailable,
    );
    drop(replacement);
}

fn fail_after_locking(
    root: &std::path::Path,
    inherited: &mut Option<std::fs::File>,
) -> Result<(), &'static str> {
    let file = std::fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(root.join(".catalog.lock"))
        .expect("owner file");
    file.try_lock().expect("acquire before initialization");
    let owner = OwnerLock(file);
    *inherited = Some(owner.0.try_clone().expect("inherited descriptor"));
    Err("controlled initialization failure")
}
