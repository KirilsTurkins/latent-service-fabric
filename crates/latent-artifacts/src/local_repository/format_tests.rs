use super::*;

fn reject_without_cleanup(root: &TempRoot) {
    let Err(error) = DirectoryArtifactRepository::open(
        root.path(),
        DirectoryArtifactRepositoryConfig::default(),
    ) else {
        panic!("obsolete catalog must be rejected");
    };
    assert_eq!(error.code, PlatformErrorCode::Unavailable);
    assert!(error.message.contains("provision fresh state"));
    assert_eq!(
        fs::read(root.path().join(".tmp/staged")).unwrap(),
        b"retained"
    );
    assert!(!root.path().join("publications").exists());
    assert!(!root.path().join("lifecycle/HEAD").exists());
}

fn preserved_root() -> TempRoot {
    let root = TempRoot::new();
    fs::create_dir_all(root.path().join(".tmp")).unwrap();
    fs::write(root.path().join(".tmp/staged"), b"retained").unwrap();
    root
}

#[test]
fn unsupported_lifecycle_formats_preserve_source_and_staged_bytes() {
    for version in [0, 1, 3] {
        let root = preserved_root();
        fs::create_dir(root.path().join("lifecycle")).unwrap();
        let mode = format!("{{\"formatVersion\":{version}}}");
        fs::write(root.path().join("lifecycle/MODE"), &mode).unwrap();
        fs::write(
            root.path().join("LIFECYCLE_MODE"),
            b"lsf-release-lifecycle-v1\n",
        )
        .unwrap();
        reject_without_cleanup(&root);
        assert_eq!(
            fs::read(root.path().join("lifecycle/MODE")).unwrap(),
            mode.as_bytes()
        );
        assert_eq!(
            fs::read(root.path().join("LIFECYCLE_MODE")).unwrap(),
            b"lsf-release-lifecycle-v1\n"
        );
    }
}

#[test]
fn obsolete_catalog_names_and_migration_fences_are_rejected_before_cleanup() {
    for name in ["releases", ".publication-migration"] {
        let root = preserved_root();
        fs::create_dir(root.path().join(name)).unwrap();
        fs::write(root.path().join(name).join("original"), b"original").unwrap();
        reject_without_cleanup(&root);
        assert_eq!(
            fs::read(root.path().join(name).join("original")).unwrap(),
            b"original"
        );
    }
    let root = preserved_root();
    let fence = b"{\"formatVersion\":1,\"kind\":\"migration\"}";
    fs::write(root.path().join("LIFECYCLE_MODE"), fence).unwrap();
    reject_without_cleanup(&root);
    assert_eq!(fs::read(root.path().join("LIFECYCLE_MODE")).unwrap(), fence);
}

#[test]
fn current_publication_catalog_reopens_with_the_same_identity() {
    let root = TempRoot::new();
    let value = artifact("current", b"current component");
    let repo = repository(root.path());
    block_on(repo.publish(value.clone())).unwrap();
    let mode = fs::read(root.path().join("lifecycle/MODE")).unwrap();
    drop(repo);
    let reopened = repository(root.path());
    let recovered = block_on(reopened.fetch(&value.descriptor.release_digest)).unwrap();
    assert_eq!(recovered, value);
    assert_eq!(fs::read(root.path().join("lifecycle/MODE")).unwrap(), mode);
}
