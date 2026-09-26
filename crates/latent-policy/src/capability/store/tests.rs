use super::super::tests::{binding, policy, principal, publication_id};
use super::*;
use latent_artifacts::DirectoryArtifactRepository;
use latent_core::{PlatformErrorCode, TenantId};
use std::{fs, sync::atomic::Ordering, time::Duration};
use tempfile::TempDir;
mod authority;
mod perimeter;

fn deadline() -> Instant {
    Instant::now() + Duration::from_secs(10)
}
struct Fixture {
    dir: TempDir,
    catalog: DirectoryArtifactRepository,
}
impl Fixture {
    fn new() -> Self {
        let dir = TempDir::new().unwrap();
        let catalog = DirectoryArtifactRepository::open(
            dir.path().join("artifacts"),
            latent_artifacts::DirectoryArtifactRepositoryConfig::default(),
        )
        .unwrap();
        Self { dir, catalog }
    }
    fn store(&self, limits: PolicyStoreLimits) -> PolicyStore {
        PolicyStore::open(
            &self.dir.path().join("policies"),
            limits,
            self.catalog.lifecycle_authority(),
        )
        .unwrap()
    }
}
fn mutate(
    store: &PolicyStore,
    id: &str,
    op: &str,
    revision: u64,
    document: Option<&[u8]>,
) -> Result<PolicyRead<OperationReceipt>, PlatformError> {
    store.mutate(
        MutationRequest {
            tenant: "a",
            actor: "operator",
            id,
            operation_id: op,
            kind: RecordKind::Policy,
            expected_revision: revision,
            document,
        },
        deadline(),
        |_| Ok(()),
    )
}
fn request(bytes: &[u8]) -> MutationRequest<'_> {
    MutationRequest {
        tenant: "a",
        actor: "operator",
        id: "p",
        operation_id: "create",
        kind: RecordKind::Policy,
        expected_revision: 0,
        document: Some(bytes),
    }
}
#[test]
fn exact_replay_does_not_restore_a_revoked_grant_and_survives_restart() {
    let fixture = Fixture::new();
    let store = fixture.store(PolicyStoreLimits::default());
    let bytes = serde_json::to_vec(&policy()).unwrap();
    let receipt = mutate(&store, "p", "create", 0, Some(&bytes))
        .unwrap()
        .value()
        .clone();
    assert_eq!(receipt.revision, 2);
    assert_eq!(
        mutate(&store, "p", "create", 0, Some(&bytes))
            .unwrap()
            .value(),
        &receipt
    );
    let revoked = mutate(&store, "p", "revoke", 2, None)
        .unwrap()
        .value()
        .clone();
    assert_eq!(revoked.revision, 3);
    assert!(mutate(&store, "p", "create", 1, Some(&bytes)).is_err());
    assert_eq!(
        mutate(&store, "p", "create", 0, Some(&bytes))
            .unwrap()
            .value(),
        &receipt
    );
    assert!(store
        .get("a", RecordKind::Policy, "p", 4096, deadline())
        .unwrap()
        .value()
        .as_ref()
        .unwrap()
        .document
        .is_none());
    drop(store);
    let store = fixture.store(PolicyStoreLimits::default());
    assert_eq!(
        store
            .outcome("a", "revoke", deadline())
            .unwrap()
            .value()
            .as_ref(),
        Some(&revoked)
    );
    assert!(store
        .outcome("b", "revoke", deadline())
        .unwrap()
        .value()
        .is_none());
    assert!(mutate(&store, "p", "stale-create", 0, Some(&bytes)).is_err());
}
#[test]
fn bounded_outcome_retention_never_evicts_identity_tombstones() {
    let fixture = Fixture::new();
    let store = fixture.store(PolicyStoreLimits {
        maximum_records: 1,
        maximum_outcomes: 1,
        ..PolicyStoreLimits::default()
    });
    let bytes = serde_json::to_vec(&policy()).unwrap();
    mutate(&store, "p", "create", 0, Some(&bytes)).unwrap();
    mutate(&store, "p", "revoke", 2, None).unwrap();
    assert!(store
        .outcome("a", "create", deadline())
        .unwrap()
        .value()
        .is_none());
    assert!(mutate(&store, "p", "create", 0, Some(&bytes)).is_err());
    assert_eq!(
        mutate(&store, "q", "other", 0, Some(&bytes))
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(
        mutate(&store, "p", "renew", 3, Some(&bytes))
            .unwrap()
            .value()
            .revision,
        4
    );
}
#[test]
fn response_preflight_deadline_and_disk_capacity_fail_before_any_persistence() {
    let fixture = Fixture::new();
    let store = fixture.store(PolicyStoreLimits {
        maximum_catalog_bytes: 4096,
        ..PolicyStoreLimits::default()
    });
    let bytes = serde_json::to_vec(&policy()).unwrap();
    let path = fixture.dir.path().join("policies/catalog.json");
    let before = fs::read(&path).unwrap();
    assert!(store
        .mutate(request(&bytes), deadline(), |_| Err(
            super::super::capacity()
        ))
        .is_err());
    assert!(store
        .mutate(request(&bytes), Instant::now(), |_| Ok(()))
        .is_err());
    let mut large = policy();
    for i in 0..12 {
        let mut rule = large["rules"][0].clone();
        rule["id"] = format!("rule{i}").into();
        large["rules"].as_array_mut().unwrap().push(rule);
    }
    let large = serde_json::to_vec(&large).unwrap();
    assert_eq!(
        mutate(&store, "p", "large", 0, Some(&large))
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(fs::read(&path).unwrap(), before);
    assert!(store
        .outcome("a", "create", deadline())
        .unwrap()
        .value()
        .is_none());
    mutate(&store, "p", "create", 0, Some(&bytes)).unwrap();
}
#[test]
fn every_uncertain_write_poison_invalidates_live_owner_and_recovery_checks_the_floor() {
    for point in 1..=6 {
        let fixture = Fixture::new();
        let store = fixture.store(PolicyStoreLimits::default());
        let bytes = serde_json::to_vec(&policy()).unwrap();
        mutate(&store, "p", "create", 0, Some(&bytes)).unwrap();
        store
            .state
            .lock()
            .unwrap()
            .ledger
            .as_ref()
            .expect("the production policy store has a durable ledger")
            .fault
            .store(point, Ordering::Release);
        assert!(mutate(&store, "p", "revoke", 2, None).is_err());
        assert!(store
            .get("a", RecordKind::Policy, "p", 4096, deadline())
            .is_err());
        drop(store);
        let store = fixture.store(PolicyStoreLimits::default());
        let row = store
            .get("a", RecordKind::Policy, "p", 4096, deadline())
            .unwrap();
        assert_eq!(row.value().as_ref().unwrap().document.is_none(), point >= 3);
        assert_eq!(
            store
                .outcome("a", "revoke", deadline())
                .unwrap()
                .value()
                .is_some(),
            point >= 3
        );
    }
}
#[test]
fn missing_floor_markers_corruption_and_links_never_become_a_new_store() {
    for name in ["floor.json", "INITIALIZED", "catalog.json"] {
        let fixture = Fixture::new();
        let store = fixture.store(PolicyStoreLimits::default());
        drop(store);
        fs::remove_file(fixture.dir.path().join("policies").join(name)).unwrap();
        assert!(
            PolicyStore::open(
                &fixture.dir.path().join("policies"),
                PolicyStoreLimits::default(),
                fixture.catalog.lifecycle_authority()
            )
            .is_err(),
            "{name}"
        );
    }
    let fixture = Fixture::new();
    let store = fixture.store(PolicyStoreLimits::default());
    drop(store);
    let floor = fixture.dir.path().join("policies/floor.json");
    fs::remove_file(&floor).unwrap();
    std::os::unix::fs::symlink("catalog.json", &floor).unwrap();
    assert!(PolicyStore::open(
        &fixture.dir.path().join("policies"),
        PolicyStoreLimits::default(),
        fixture.catalog.lifecycle_authority()
    )
    .is_err());
}
#[test]
fn reader_limits_include_cloned_body_owners_and_have_separate_mutation_headroom() {
    let fixture = Fixture::new();
    let store = fixture.store(PolicyStoreLimits {
        maximum_read_owners: 1,
        ..PolicyStoreLimits::default()
    });
    let bytes = serde_json::to_vec(&policy()).unwrap();
    mutate(&store, "p", "create", 0, Some(&bytes)).unwrap();
    let read = store
        .get("a", RecordKind::Policy, "p", 4096, deadline())
        .unwrap();
    let (value, lease) = read.into_parts();
    let clone = lease.clone();
    drop(lease);
    assert!(store
        .get("a", RecordKind::Policy, "p", 4096, deadline())
        .is_err());
    mutate(&store, "p", "revoke", 2, None).unwrap();
    assert_eq!(store.retained_read_owners(), 1);
    drop(value);
    drop(clone);
    assert_eq!(store.retained_read_owners(), 0);
    assert!(store
        .get("a", RecordKind::Policy, "p", 4096, deadline())
        .unwrap()
        .value()
        .as_ref()
        .unwrap()
        .document
        .is_none());
}
#[test]
fn opaque_cursor_binds_scope_kind_generation_and_session() {
    let fixture = Fixture::new();
    let store = fixture.store(PolicyStoreLimits::default());
    let bytes = serde_json::to_vec(&policy()).unwrap();
    for id in ["p", "q", "r"] {
        mutate(&store, id, id, 0, Some(&bytes)).unwrap();
    }
    let mut query = PolicyPageRequest {
        tenant: "a",
        kind: RecordKind::Policy,
        cursor: None,
        limit: 1,
        maximum_bytes: 8192,
        deadline: deadline(),
    };
    let first = store.list(&query).unwrap();
    let cursor = first.value().next_cursor.clone().unwrap();
    drop(first);
    query.cursor = Some(&cursor);
    assert_eq!(store.list(&query).unwrap().value().records[0].id, "q");
    query.tenant = "b";
    assert!(store.list(&query).is_err());
    query.tenant = "a";
    query.kind = RecordKind::ProviderBinding;
    assert!(store.list(&query).is_err());
    query.kind = RecordKind::Policy;
    mutate(&store, "p", "revoke", 2, None).unwrap();
    assert!(store.list(&query).is_err());
    drop(store);
    let store = fixture.store(PolicyStoreLimits::default());
    assert!(store.list(&query).is_err());
}
#[test]
fn competing_cas_writers_have_exactly_one_winner() {
    let fixture = Fixture::new();
    let store = fixture.store(PolicyStoreLimits::default());
    let bytes = serde_json::to_vec(&policy()).unwrap();
    let barrier = std::sync::Barrier::new(2);
    let results = std::thread::scope(|scope| {
        let handles: Vec<_> = ["left", "right"]
            .into_iter()
            .map(|operation| {
                let store = &store;
                let bytes = &bytes;
                let barrier = &barrier;
                scope.spawn(move || {
                    barrier.wait();
                    mutate(store, "p", operation, 0, Some(bytes)).is_ok()
                })
            })
            .collect();
        handles
            .into_iter()
            .map(|handle| handle.join().unwrap())
            .collect::<Vec<_>>()
    });
    assert_eq!(results.into_iter().filter(|value| *value).count(), 1);
}
