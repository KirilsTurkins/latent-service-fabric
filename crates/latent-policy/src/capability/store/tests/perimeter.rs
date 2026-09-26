use super::*;
use std::os::unix::fs::PermissionsExt;

#[test]
fn storage_permissions_links_corruption_and_oversized_history_fail_closed() {
    for variant in 0..5 {
        let fixture = Fixture::new();
        drop(fixture.store(PolicyStoreLimits::default()));
        let root = fixture.dir.path().join("policies");
        let image = root.join("catalog.json");
        match variant {
            0 => fs::set_permissions(&image, fs::Permissions::from_mode(0o644)).unwrap(),
            1 => fs::hard_link(&image, root.join("duplicate")).unwrap(),
            2 => fs::write(&image, b"{\"formatVersion\":1}").unwrap(),
            3 => fs::OpenOptions::new()
                .write(true)
                .open(&image)
                .unwrap()
                .set_len(4 * 1024 * 1024 + 1)
                .unwrap(),
            _ => fs::set_permissions(&root, fs::Permissions::from_mode(0o755)).unwrap(),
        }
        assert!(
            PolicyStore::open(
                &root,
                PolicyStoreLimits::default(),
                fixture.catalog.lifecycle_authority()
            )
            .is_err(),
            "{variant}"
        );
    }
}

#[test]
fn unwinding_preflight_retires_authority_until_verified_reopen() {
    let fixture = Fixture::new();
    let store = fixture.store(PolicyStoreLimits::default());
    let bytes = serde_json::to_vec(&policy()).unwrap();
    let before = fs::read(fixture.dir.path().join("policies/catalog.json")).unwrap();
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        store.mutate(request(&bytes), deadline(), |_| {
            panic!("injected response preflight failure")
        })
    }));
    assert!(result.is_err());
    assert!(store
        .get("a", RecordKind::Policy, "p", 4096, deadline())
        .is_err());
    drop(store);
    assert_eq!(
        fs::read(fixture.dir.path().join("policies/catalog.json")).unwrap(),
        before
    );
    let reopened = fixture.store(PolicyStoreLimits::default());
    assert!(reopened
        .outcome("a", "create", deadline())
        .unwrap()
        .value()
        .is_none());
    mutate(&reopened, "p", "create", 0, Some(&bytes)).unwrap();
}
