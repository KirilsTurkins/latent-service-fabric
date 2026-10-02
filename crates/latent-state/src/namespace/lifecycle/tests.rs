//! Native-row schedules for mutable lifecycle ownership, not policy permission.
use super::*;
use crate::{
    embedded::{
        AtomicBatch, EmbeddedStore, Family, FencedStoreError, RowKey, RowMutation, StoreLimits,
    },
    namespace::{
        catalog::{NamespaceCatalog, NamespaceMutation, NamespaceOperationContext},
        NamespaceQuota, NamespaceTransition,
    },
};
use latent_core::{StateNamespaceId, TenantId};
use std::fs::OpenOptions;

struct Fixture {
    store: EmbeddedStore,
    catalog: NamespaceCatalog,
    _directory: tempfile::TempDir,
}
impl Fixture {
    fn new() -> Self {
        let directory = tempfile::tempdir().unwrap();
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(directory.path().join("state.redb"))
            .unwrap();
        Self {
            store: EmbeddedStore::open_file(file, StoreLimits::default()).unwrap(),
            catalog: NamespaceCatalog::new(),
            _directory: directory,
        }
    }
    fn record(id: &str) -> NamespaceRecord {
        NamespaceRecord::create(
            TenantId("a".into()),
            StateNamespaceId(id.into()),
            format!("sha256:{}", "1".repeat(64)),
            NamespaceQuota::default(),
        )
        .unwrap()
    }
    fn create(&self, id: &str) -> NamespaceRead {
        let record = Self::record(id);
        let prepared = self
            .catalog
            .prepare(
                &self.store,
                NamespaceOperationContext {
                    tenant: record.tenant.clone(),
                    actor: "fixture".into(),
                    operation_id: id.into(),
                },
                &NamespaceMutation::Create {
                    id: record.id.clone(),
                    state_schema: record.state_schema,
                    quota: record.quota,
                },
                0,
            )
            .unwrap();
        // Trusted fixture population, not production namespace authorization.
        self.store.apply(prepared.batch).unwrap();
        self.read(id)
    }
    fn read(&self, id: &str) -> NamespaceRead {
        NamespaceCatalog::read_in(
            &self.store.snapshot().unwrap(),
            &TenantId("a".into()),
            &StateNamespaceId(id.into()),
        )
        .unwrap()
        .unwrap()
    }
    fn replacement(before: &NamespaceRead, after: &NamespaceRecord) -> AtomicBatch {
        AtomicBatch {
            expectations: vec![before.expectation()],
            mutations: vec![RowMutation {
                key: before.expectation().key,
                value: Some(after.encode().unwrap()),
            }],
        }
    }
}

#[test]
fn retained_native_snapshot_loses_read_authority_at_lifecycle_acceptance_before_commit_io() {
    let fixture = Fixture::new();
    let before = fixture.create("orders");
    let registry = fixture.catalog.lifecycle();
    let handle = registry.pin(&before).unwrap();
    let after = before
        .record()
        .transition(before.record().version, &NamespaceTransition::Quiesce, 0)
        .unwrap();
    let mut completion = None;
    fixture
        .store
        .apply_fenced(Fixture::replacement(&before, &after), || {
            completion = Some(registry.begin_transition(&before, &after, false)?);
            assert!(handle.with_current(&before, false, || Ok(())).is_err());
            Ok::<_, NamespaceError>(())
        })
        .unwrap();
    let current = fixture.read("orders");
    completion.unwrap().resolve(&current).unwrap();
    assert!(handle.with_current(&before, false, || Ok(())).is_err());
    assert!(handle.with_current(&current, false, || Ok(())).is_err());
    let fresh = registry.pin(&current).unwrap();
    fresh.with_current(&current, false, || Ok(())).unwrap();
    assert!(fresh.with_current(&current, true, || Ok(())).is_err());
}

#[test]
fn creation_capacity_is_reserved_before_commit_and_unresolved_completion_stays_closed() {
    let fixture = Fixture::new();
    let registry = NamespaceLifecycleRegistry::new(NamespaceLifecycleLimits {
        namespaces: 1,
        owners: 1,
    })
    .unwrap();
    let first = Fixture::record("first");
    let first_key = RowKey {
        family: Family::Namespace,
        key: crate::namespace::namespace_record_key(&first.tenant, &first.id).unwrap(),
    };
    let first_batch = AtomicBatch {
        expectations: vec![crate::embedded::ExpectedRow {
            key: first_key.clone(),
            value: None,
        }],
        mutations: vec![RowMutation {
            key: first_key,
            value: Some(first.encode().unwrap()),
        }],
    };
    let mut completion = None;
    fixture
        .store
        .apply_fenced(first_batch, || {
            registry
                .begin_create(&first)
                .map(|value| completion = Some(value))
        })
        .unwrap();
    let read = fixture.read("first");
    assert!(registry.pin(&read).is_err());
    completion.unwrap().resolve(&read).unwrap();
    let second = Fixture::record("second");
    let key = RowKey {
        family: Family::Namespace,
        key: crate::namespace::namespace_record_key(&second.tenant, &second.id).unwrap(),
    };
    let batch = AtomicBatch {
        expectations: vec![crate::embedded::ExpectedRow {
            key: key.clone(),
            value: None,
        }],
        mutations: vec![RowMutation {
            key: key.clone(),
            value: Some(second.encode().unwrap()),
        }],
    };
    assert!(matches!(
        fixture
            .store
            .apply_fenced(batch, || registry.begin_create(&second).map(|_| ())),
        Err(FencedStoreError::Fence(NamespaceError::Capacity))
    ));
    assert!(fixture
        .store
        .snapshot()
        .unwrap()
        .get(&key)
        .unwrap()
        .is_none());
    let after = read
        .record()
        .transition(read.record().version, &NamespaceTransition::Quiesce, 0)
        .unwrap();
    fixture
        .store
        .apply_fenced(Fixture::replacement(&read, &after), || {
            registry.begin_transition(&read, &after, false).map(drop)
        })
        .unwrap();
    assert!(registry.pin(&fixture.read("first")).is_err());
    // A fresh startup owner obtains its state from the real native row.
    let restarted = NamespaceLifecycleRegistry::new(NamespaceLifecycleLimits::default()).unwrap();
    restarted.pin(&fixture.read("first")).unwrap();
}

#[test]
fn actual_retained_handles_block_retirement_until_drop_even_when_reported_count_is_zero() {
    let fixture = Fixture::new();
    let before = fixture.create("orders");
    let registry = fixture.catalog.lifecycle();
    let handle = registry.pin(&before).unwrap();
    let quiesced = before
        .record()
        .transition(before.record().version, &NamespaceTransition::Quiesce, 0)
        .unwrap();
    let mut completion = None;
    fixture
        .store
        .apply_fenced(Fixture::replacement(&before, &quiesced), || {
            registry
                .begin_transition(&before, &quiesced, false)
                .map(|value| completion = Some(value))
        })
        .unwrap();
    let current = fixture.read("orders");
    completion.unwrap().resolve(&current).unwrap();
    let retired = current
        .record()
        .transition(current.record().version, &NamespaceTransition::Retire, 0)
        .unwrap();
    assert!(matches!(
        fixture
            .store
            .apply_fenced(Fixture::replacement(&current, &retired), || registry
                .begin_transition(&current, &retired, true)
                .map(drop)),
        Err(FencedStoreError::Fence(NamespaceError::InUse))
    ));
    assert_eq!(
        fixture.read("orders").record().status,
        NamespaceStatus::Quiescing
    );
    assert_eq!(registry.retained_owners(), 1);
    drop(handle);
    assert_eq!(registry.retained_owners(), 0);
    let mut completion = None;
    fixture
        .store
        .apply_fenced(Fixture::replacement(&current, &retired), || {
            registry
                .begin_transition(&current, &retired, true)
                .map(|value| completion = Some(value))
        })
        .unwrap();
    completion
        .unwrap()
        .resolve(&fixture.read("orders"))
        .unwrap();
}

#[test]
fn bounded_handles_and_registry_retirement_cannot_be_revived_by_retaining_descriptors() {
    let fixture = Fixture::new();
    let read = fixture.create("orders");
    let registry = NamespaceLifecycleRegistry::new(NamespaceLifecycleLimits {
        namespaces: 1,
        owners: 1,
    })
    .unwrap();
    let handle = registry.pin(&read).unwrap();
    assert!(matches!(registry.pin(&read), Err(NamespaceError::Capacity)));
    registry.retire().unwrap();
    assert_eq!(
        handle.with_current(&read, false, || Ok(())),
        Err(NamespaceError::Unavailable)
    );
    assert!(registry.pin(&read).is_err());
    drop(handle);
    assert_eq!(registry.retained_owners(), 0);
    let registry = NamespaceLifecycleRegistry::new(NamespaceLifecycleLimits::default()).unwrap();
    let handle = registry.pin(&read).unwrap();
    drop(registry);
    assert_eq!(
        handle.with_current(&read, false, || Ok(())),
        Err(NamespaceError::Unavailable)
    );
}
