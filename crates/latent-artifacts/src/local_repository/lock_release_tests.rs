use super::super::OwnerLock;
use super::*;

#[test]
#[allow(clippy::used_underscore_binding)] // Inspect the private RAII field to model inheritance.
fn dropping_owner_releases_lock_while_duplicate_descriptor_remains_open() {
    let root = TempRoot::new();
    let expected = artifact("duplicated-owner", b"tiny preserved release");
    let owner = repository(root.path());
    block_on(owner.publish(expected.clone())).expect("publish");
    // A duplicate shares the same open-file description as a descriptor
    // inherited by a concurrently starting child before its exec closes it.
    let inherited = owner
        ._owner_lock
        .0
        .try_clone()
        .expect("duplicate descriptor");
    assert_eq!(
        DirectoryArtifactRepository::open(
            root.path(),
            DirectoryArtifactRepositoryConfig::default()
        )
        .expect_err("live owner still excludes independent openers")
        .code,
        PlatformErrorCode::Unavailable,
    );
    drop(owner);
    let replacement = repository(root.path());
    assert_eq!(
        block_on(replacement.fetch(&expected.descriptor.release_digest))
            .expect("preserved release"),
        expected,
    );
    drop(inherited);
    assert_eq!(
        DirectoryArtifactRepository::open(
            root.path(),
            DirectoryArtifactRepositoryConfig::default()
        )
        .expect_err("closing stale duplicate must not unlock replacement owner")
        .code,
        PlatformErrorCode::Unavailable,
    );
}

#[test]
fn initialization_error_releases_lock_before_repository_construction() {
    let root = TempRoot::new();
    let mut inherited = None;
    let result = fail_after_locking(root.path(), &mut inherited);
    assert_eq!(result, Err("controlled initialization failure"));
    let replacement = repository(root.path());
    drop(inherited);
    assert_eq!(
        DirectoryArtifactRepository::open(
            root.path(),
            DirectoryArtifactRepositoryConfig::default()
        )
        .expect_err("replacement remains exclusive")
        .code,
        PlatformErrorCode::Unavailable,
    );
    drop(replacement);
}

fn fail_after_locking(
    root: &std::path::Path,
    inherited: &mut Option<std::fs::File>,
) -> Result<(), &'static str> {
    let file = fs::OpenOptions::new()
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
