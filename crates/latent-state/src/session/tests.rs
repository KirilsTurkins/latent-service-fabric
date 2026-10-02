use super::*;
use crate::embedded::{EmbeddedStore, FencedStoreError, StoreLimits};
use crate::namespace::NamespaceQuota;
use std::fs::OpenOptions;

struct Fixture {
    store: EmbeddedStore,
    scope: StateScope,
    _directory: tempfile::TempDir,
}
fn allow(scope: &StateScope, _: StateAccess) -> Result<(), StateError> {
    if scope.tenant.0 == "tenant" {
        Ok(())
    } else {
        Err(StateError::PermissionDenied)
    }
}
fn value(bytes: &[u8]) -> Value {
    Value {
        bytes: bytes.to_vec(),
        media_type: "application/octet-stream".into(),
        metadata: vec![],
    }
}
impl Fixture {
    fn new() -> Self {
        Self::with_quota(NamespaceQuota::default(), 1)
    }
    fn with_quota(quota: NamespaceQuota, generation: u64) -> Self {
        let directory = tempfile::tempdir().unwrap();
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(directory.path().join("session.redb"))
            .unwrap();
        let store = EmbeddedStore::open_file(
            file,
            StoreLimits {
                cache_bytes: 1024 * 1024,
                maximum_key_bytes: 4096,
                maximum_value_bytes: 2 * 1024 * 1024,
                ..StoreLimits::default()
            },
        )
        .unwrap();
        let scope = StateScope {
            tenant: TenantId("tenant".into()),
            namespace: StateNamespaceId("business".into()),
            incarnation: 1,
            state_schema: format!("sha256:{}", "1".repeat(64)),
            entity: None,
            mode: StateMode::Command,
        };
        let mut namespace = NamespaceRecord::create(
            scope.tenant.clone(),
            scope.namespace.clone(),
            scope.state_schema.clone(),
            quota,
        )
        .unwrap();
        namespace.version.generation = generation;
        store
            .apply(AtomicBatch {
                expectations: vec![],
                mutations: vec![RowMutation {
                    key: namespace_key(&scope).unwrap(),
                    value: Some(namespace.encode().unwrap()),
                }],
            })
            .unwrap();
        Self {
            store,
            scope,
            _directory: directory,
        }
    }
    fn session(&self) -> (ReadView, StateSession) {
        self.in_scope(self.scope.clone(), SessionLimits::default())
    }
    fn in_scope(&self, scope: StateScope, limits: SessionLimits) -> (ReadView, StateSession) {
        let view = self.store.snapshot().unwrap();
        let session = StateSession::open(&view, scope, limits, allow).unwrap();
        (view, session)
    }
    fn write(&self, changes: &[(&[u8], Option<&[u8]>)]) {
        let (view, mut session) = self.session();
        for (key, data) in changes {
            if let Some(bytes) = data {
                session
                    .put(&view, key.to_vec(), value(bytes), allow)
                    .unwrap();
            } else {
                session.delete(&view, key.to_vec(), allow).unwrap();
            }
        }
        commit(&self.store, &view, session).unwrap();
    }
    fn read(&self, key: &[u8]) -> Option<ReadValue> {
        let (view, mut session) = self.session();
        session.get(&view, key, allow).unwrap()
    }
}
// State-only engine schedules test OCC. Production consumes this same affine
// plan inside the complete command/result/intent/inbox coordinator.
fn commit(store: &EmbeddedStore, view: &ReadView, session: StateSession) -> Result<(), StateError> {
    let plan = session.seal(view, allow)?;
    let mut batch = AtomicBatch::default();
    let pins = plan.pins();
    plan.append_to(&mut batch, pins)?;
    store
        .apply_fenced(batch, || Ok::<(), StateError>(()))
        .map_err(|error| match error {
            FencedStoreError::Store(error) => error.into(),
            FencedStoreError::Fence(error) => error,
        })
}

#[test]
fn lost_update_has_one_serializable_winner_without_guest_retry() {
    let fixture = Fixture::new();
    fixture.write(&[(b"counter", Some(b"0"))]);
    let (first_view, mut first) = fixture.session();
    let (second_view, mut second) = fixture.session();
    for (view, session) in [(&first_view, &mut first), (&second_view, &mut second)] {
        assert_eq!(
            session
                .get(view, b"counter", allow)
                .unwrap()
                .unwrap()
                .value
                .bytes,
            b"0"
        );
        session
            .put(view, b"counter".to_vec(), value(b"1"), allow)
            .unwrap();
    }
    assert_eq!(commit(&fixture.store, &first_view, first), Ok(()));
    assert_eq!(
        commit(&fixture.store, &second_view, second),
        Err(StateError::Conflict)
    );
    assert_eq!(fixture.read(b"counter").unwrap().value.bytes, b"1");
}

#[test]
fn write_skew_and_absent_creation_validate_the_entire_namespace() {
    let fixture = Fixture::new();
    fixture.write(&[(b"a", Some(b"1")), (b"b", Some(b"1"))]);
    let (left_view, mut left) = fixture.session();
    let (right_view, mut right) = fixture.session();
    for (view, session) in [(&left_view, &mut left), (&right_view, &mut right)] {
        for key in [b"a".as_slice(), b"b".as_slice(), b"missing".as_slice()] {
            let _ = session.get(view, key, allow).unwrap();
        }
    }
    left.put(&left_view, b"a".to_vec(), value(b"0"), allow)
        .unwrap();
    right
        .put(&right_view, b"b".to_vec(), value(b"0"), allow)
        .unwrap();
    commit(&fixture.store, &left_view, left).unwrap();
    assert_eq!(
        commit(&fixture.store, &right_view, right),
        Err(StateError::Conflict)
    );
    assert_eq!(fixture.read(b"b").unwrap().value.bytes, b"1");
    let (view, mut observer) = fixture.session();
    assert_eq!(observer.get(&view, b"missing", allow), Ok(None));
    fixture.write(&[(b"missing", Some(b"created"))]);
    observer
        .put(&view, b"other".to_vec(), value(b"from-absence"), allow)
        .unwrap();
    assert_eq!(
        commit(&fixture.store, &view, observer),
        Err(StateError::Conflict)
    );
    assert_eq!(fixture.read(b"other"), None);
}

#[test]
fn blind_writers_and_delete_recreate_cannot_reuse_a_version() {
    let fixture = Fixture::new();
    let (a_view, mut a) = fixture.session();
    let (b_view, mut b) = fixture.session();
    a.put(&a_view, b"key".to_vec(), value(b"same"), allow)
        .unwrap();
    b.put(&b_view, b"key".to_vec(), value(b"other"), allow)
        .unwrap();
    commit(&fixture.store, &a_view, a).unwrap();
    assert_eq!(
        commit(&fixture.store, &b_view, b),
        Err(StateError::Conflict)
    );
    let old = fixture.read(b"key").unwrap().version;
    let (view, mut stale) = fixture.session();
    stale.get(&view, b"key", allow).unwrap();
    fixture.write(&[(b"key", None)]);
    fixture.write(&[(b"key", Some(b"same"))]);
    stale
        .put(&view, b"key".to_vec(), value(b"late"), allow)
        .unwrap();
    assert_eq!(
        commit(&fixture.store, &view, stale),
        Err(StateError::Conflict)
    );
    assert_ne!(fixture.read(b"key").unwrap().version, old);
}

#[test]
fn empty_and_truncated_prefix_scans_conflict_on_phantom_insert_delete() {
    let fixture = Fixture::new();
    let (view, mut empty) = fixture.session();
    assert!(empty
        .scan(&view, b"p/", None, 1, 1000, allow)
        .unwrap()
        .entries
        .is_empty());
    fixture.write(&[(b"p/a", Some(b"a")), (b"p/z", Some(b"z"))]);
    empty
        .put(&view, b"summary".to_vec(), value(b"empty"), allow)
        .unwrap();
    assert_eq!(
        commit(&fixture.store, &view, empty),
        Err(StateError::Conflict)
    );
    for (changed_key, change) in [
        (b"p/y".as_slice(), Some(b"inserted".as_slice())),
        (b"p/z".as_slice(), None),
    ] {
        let (view, mut page) = fixture.session();
        let first = page.scan(&view, b"p/", None, 1, 1000, allow).unwrap();
        assert_eq!(first.entries[0].key, b"p/a");
        assert!(first.continuation.is_some());
        fixture.write(&[(changed_key, change)]);
        page.put(&view, b"summary".to_vec(), value(b"only-a"), allow)
            .unwrap();
        assert_eq!(
            commit(&fixture.store, &view, page),
            Err(StateError::Conflict)
        );
    }
}

#[test]
fn staged_overlay_is_bytewise_ordered_and_pages_keep_one_view() {
    let fixture = Fixture::new();
    fixture.write(&[
        (b"p/1", Some(b"one")),
        (b"p/3", Some(b"three")),
        (b"p/5", Some(b"five")),
    ]);
    let (view, mut session) = fixture.session();
    session
        .put(&view, b"p/0".to_vec(), value(b"zero"), allow)
        .unwrap();
    session
        .put(&view, b"p/2".to_vec(), value(b"two"), allow)
        .unwrap();
    session.delete(&view, b"p/3".to_vec(), allow).unwrap();
    session
        .put(&view, b"p/5".to_vec(), value(b"changed"), allow)
        .unwrap();
    assert_eq!(session.get(&view, b"p/3", allow), Ok(None));
    assert_eq!(
        session
            .get(&view, b"p/5", allow)
            .unwrap()
            .unwrap()
            .value
            .bytes,
        b"changed"
    );
    let first = session.scan(&view, b"p/", None, 2, 1000, allow).unwrap();
    assert_eq!(
        first
            .entries
            .iter()
            .map(|entry| entry.key.as_slice())
            .collect::<Vec<_>>(),
        vec![b"p/0".as_slice(), b"p/1".as_slice()]
    );
    fixture.write(&[(b"p/4", Some(b"later"))]);
    let next = session
        .scan(&view, b"p/", first.continuation.as_ref(), 2, 1000, allow)
        .unwrap();
    assert_eq!(
        next.entries
            .iter()
            .map(|entry| entry.key.as_slice())
            .collect::<Vec<_>>(),
        vec![b"p/2".as_slice(), b"p/5".as_slice()]
    );
    assert!(next.continuation.is_none());
    assert_eq!(
        commit(&fixture.store, &view, session),
        Err(StateError::Conflict)
    );
}

#[test]
fn cursor_scope_query_overlay_generation_and_once_only_use_are_enforced() {
    let fixture = Fixture::new();
    fixture.write(&[
        (b"p/1", Some(b"one")),
        (b"p/2", Some(b"two")),
        (b"p/3", Some(b"three")),
    ]);
    let (view, mut session) = fixture.session();
    let (foreign_view, mut foreign) = fixture.session();
    let page = session.scan(&view, b"p/", None, 1, 1000, allow).unwrap();
    let cursor = page.continuation.unwrap();
    assert_eq!(
        foreign.cursor(cursor.bytes()),
        Err(StateError::InvalidCursor)
    );
    assert_eq!(
        foreign.scan(&foreign_view, b"p/", Some(&cursor), 1, 1000, allow),
        Err(StateError::InvalidCursor)
    );
    assert_eq!(
        session.scan(&view, b"other/", Some(&cursor), 1, 1000, allow),
        Err(StateError::InvalidCursor)
    );
    assert_eq!(
        session.get(&foreign_view, b"p/1", allow),
        Err(StateError::Invalid)
    );
    let mut forged = cursor.bytes().to_vec();
    forged[0] ^= 1;
    assert_eq!(session.cursor(&forged), Err(StateError::InvalidCursor));
    let second = session
        .scan(&view, b"p/", Some(&cursor), 1, 1000, allow)
        .unwrap();
    assert_eq!(
        session.scan(&view, b"p/", Some(&cursor), 1, 1000, allow),
        Err(StateError::InvalidCursor)
    );
    session
        .put(&view, b"p/0".to_vec(), value(b"zero"), allow)
        .unwrap();
    assert_eq!(
        session.scan(&view, b"p/", second.continuation.as_ref(), 1, 1000, allow),
        Err(StateError::InvalidCursor)
    );
    session.close().unwrap();
    assert_eq!(session.close(), Err(StateError::Closed));
    assert_eq!(session.cursor(cursor.bytes()), Err(StateError::Closed));
    assert_eq!(session.get(&view, b"p/1", allow), Err(StateError::Closed));
}

#[test]
fn byte_limited_pages_require_continuation_and_never_omit_an_entry() {
    let fixture = Fixture::new();
    fixture.write(&[(b"a", Some(b"1")), (b"b", Some(b"2")), (b"c", Some(b"3"))]);
    let (view, mut session) = fixture.session();
    let mut cursor = None;
    let mut keys = vec![];
    loop {
        let page = session
            .scan(&view, b"", cursor.as_ref(), 128, 120, allow)
            .unwrap();
        assert_eq!(page.entries.len(), 1);
        keys.extend(page.entries.into_iter().map(|entry| entry.key));
        cursor = page.continuation;
        if cursor.is_none() {
            break;
        }
    }
    assert_eq!(keys, vec![b"a".to_vec(), b"b".to_vec(), b"c".to_vec()]);
    assert_eq!(
        session.scan(&view, b"", None, 128, 10, allow),
        Err(StateError::Limit)
    );
}

#[test]
fn read_only_queries_allocate_no_command_result_outbox_or_state_version() {
    let fixture = Fixture::new();
    fixture.write(&[(b"a", Some(b"1")), (b"b", Some(b"2"))]);
    let before = fixture
        .store
        .snapshot()
        .unwrap()
        .get(&namespace_key(&fixture.scope).unwrap())
        .unwrap();
    for _ in 0..5 {
        let mut scope = fixture.scope.clone();
        scope.mode = StateMode::Query;
        let (view, mut query) = fixture.in_scope(scope, SessionLimits::default());
        assert_eq!(
            query.get(&view, b"a", allow).unwrap().unwrap().value.bytes,
            b"1"
        );
        assert_eq!(
            query.put(&view, b"a".to_vec(), value(b"bad"), allow),
            Err(StateError::PermissionDenied)
        );
        assert_eq!(
            query.delete(&view, b"b".to_vec(), allow),
            Err(StateError::PermissionDenied)
        );
        assert_eq!(
            query
                .scan(&view, b"", None, 128, 1000, allow)
                .unwrap()
                .entries
                .len(),
            2
        );
        assert!(matches!(
            query.seal(&view, allow),
            Err(StateError::PermissionDenied)
        ));
    }
    let after = fixture.store.snapshot().unwrap();
    assert_eq!(
        after.get(&namespace_key(&fixture.scope).unwrap()).unwrap(),
        before
    );
    for family in [
        Family::Command,
        Family::Result,
        Family::Outbox,
        Family::Inbox,
    ] {
        assert!(after.scan(family, b"", 128, 1000).unwrap().is_empty());
    }
}

#[test]
fn current_authorization_and_namespace_schema_incarnation_fences_fail_closed() {
    let fixture = Fixture::new();
    let view = fixture.store.snapshot().unwrap();
    let denied = |_: &StateScope, _: StateAccess| Err(StateError::PermissionDenied);
    assert!(matches!(
        StateSession::open(
            &view,
            fixture.scope.clone(),
            SessionLimits::default(),
            denied
        ),
        Err(StateError::PermissionDenied)
    ));
    let mut wrong = fixture.scope.clone();
    wrong.incarnation += 1;
    assert!(matches!(
        StateSession::open(&view, wrong, SessionLimits::default(), allow),
        Err(StateError::PermissionDenied)
    ));
    let mut wrong = fixture.scope.clone();
    wrong.tenant = TenantId("foreign".into());
    assert!(matches!(
        StateSession::open(&view, wrong, SessionLimits::default(), allow),
        Err(StateError::PermissionDenied)
    ));
    let mut wrong = fixture.scope.clone();
    wrong.state_schema = format!("sha256:{}", "2".repeat(64));
    assert!(matches!(
        StateSession::open(&view, wrong, SessionLimits::default(), allow),
        Err(StateError::PermissionDenied)
    ));
    let (_, mut session) = fixture.session();
    // The correct view still fails when the current policy operation is revoked.
    let (view, mut session2) = fixture.session();
    assert_eq!(
        session2.get(&view, b"a", denied),
        Err(StateError::PermissionDenied)
    );
    assert_eq!(session.get(&view, b"a", allow), Err(StateError::Invalid));
}

#[test]
fn namespace_state_quota_is_shared_across_entity_key_spaces() {
    let fixture = Fixture::with_quota(
        NamespaceQuota {
            state_keys: 1,
            ..NamespaceQuota::default()
        },
        1,
    );
    let mut scope = fixture.scope.clone();
    scope.entity = Some("one".into());
    let (view, mut first) = fixture.in_scope(scope, SessionLimits::default());
    first
        .put(&view, b"key".to_vec(), value(b"one"), allow)
        .unwrap();
    commit(&fixture.store, &view, first).unwrap();
    let mut scope = fixture.scope.clone();
    scope.entity = Some("two".into());
    let (view, mut second) = fixture.in_scope(scope, SessionLimits::default());
    second
        .put(&view, b"key".to_vec(), value(b"two"), allow)
        .unwrap();
    assert!(matches!(second.seal(&view, allow), Err(StateError::Limit)));
    assert_eq!(fixture.read(b"key"), None);
}

#[test]
fn attempted_overwrites_reads_and_open_cursors_remain_bounded() {
    let fixture = Fixture::new();
    let (view, mut session) = fixture.in_scope(
        fixture.scope.clone(),
        SessionLimits {
            staged_bytes: 150,
            ..SessionLimits::default()
        },
    );
    session
        .put(&view, b"key".to_vec(), value(b"one"), allow)
        .unwrap();
    assert_eq!(
        session.put(&view, b"key".to_vec(), value(b"two"), allow),
        Err(StateError::Limit)
    );
    assert!(matches!(session.seal(&view, allow), Err(StateError::Limit)));
    fixture.write(&[(b"a", Some(b"1")), (b"b", Some(b"2"))]);
    let (view, mut session) = fixture.in_scope(
        fixture.scope.clone(),
        SessionLimits {
            open_cursors: 1,
            observed_keys: 1,
            ..SessionLimits::default()
        },
    );
    let page = session.scan(&view, b"", None, 1, 1000, allow).unwrap();
    assert!(page.continuation.is_some());
    assert_eq!(
        session.scan(&view, b"", None, 1, 1000, allow),
        Err(StateError::Limit)
    );
    assert_eq!(session.get(&view, b"b", allow), Err(StateError::Limit));
    let (view, mut session) = fixture.in_scope(
        fixture.scope.clone(),
        SessionLimits {
            host_calls: 1,
            ..SessionLimits::default()
        },
    );
    session.get(&view, b"a", allow).unwrap();
    assert_eq!(session.get(&view, b"a", allow), Err(StateError::Limit));
}

#[test]
fn logical_age_and_close_do_not_refund_a_live_physical_view() {
    let fixture = Fixture::new();
    let (view, mut session) = fixture.session();
    assert_eq!(fixture.store.live_views(), 1);
    session.opened -= Duration::from_secs(31);
    assert_eq!(session.get(&view, b"a", allow), Err(StateError::Expired));
    session.close().unwrap();
    assert_eq!(fixture.store.live_views(), 1);
    drop(session);
    assert_eq!(fixture.store.live_views(), 1);
    drop(view);
    assert_eq!(fixture.store.live_views(), 0);
}

#[test]
fn stale_edit_preconditions_are_original_key_scoped_and_not_refreshed() {
    let fixture = Fixture::new();
    fixture.write(&[(b"a", Some(b"1")), (b"b", Some(b"1"))]);
    let old = fixture.read(b"a").unwrap().version;
    assert_ne!(old, fixture.read(b"b").unwrap().version);
    fixture.write(&[(b"a", Some(b"2"))]);
    let (view, mut session) = fixture.session();
    assert_eq!(
        session.check_preconditions(
            &view,
            &[Precondition {
                key: b"a".to_vec(),
                expected: ExpectedVersion::Present(old.clone())
            }],
            allow
        ),
        Err(StateError::Conflict)
    );
    assert_eq!(
        session.check_preconditions(
            &view,
            &[Precondition {
                key: b"b".to_vec(),
                expected: ExpectedVersion::Present(old)
            }],
            allow
        ),
        Err(StateError::Conflict)
    );
    assert_eq!(fixture.read(b"a").unwrap().value.bytes, b"2");
}

#[test]
fn malformed_lengths_and_unknown_state_formats_are_storage_errors_not_absence() {
    let fixture = Fixture::new();
    let mut truncated = b"LSV\x01".to_vec();
    truncated.extend_from_slice(&1u64.to_le_bytes());
    truncated.push(1);
    truncated.extend_from_slice(&u32::MAX.to_le_bytes());
    for (bytes, expected) in [
        (truncated, StateError::Corrupt),
        (
            b"LSV\x02unsupported".to_vec(),
            StateError::UnsupportedFormat,
        ),
        (vec![0; codec::CELL_BYTES + 1], StateError::Corrupt),
    ] {
        fixture
            .store
            .apply(AtomicBatch {
                expectations: vec![],
                mutations: vec![RowMutation {
                    key: state_key(&fixture.scope, b"bad").unwrap(),
                    value: Some(bytes),
                }],
            })
            .unwrap();
        let (view, mut session) = fixture.session();
        assert_eq!(session.get(&view, b"bad", allow), Err(expected));
        assert!(expected.storage_error().is_some());
    }
}

#[test]
fn exact_maximum_key_value_and_generation_exhaustion_do_not_wrap() {
    let fixture = Fixture::new();
    let (view, mut session) = fixture.session();
    let key = vec![7; contract::KEY_BYTES];
    let bytes = vec![8; contract::VALUE_BYTES];
    session
        .put(&view, key.clone(), value(&bytes), allow)
        .unwrap();
    commit(&fixture.store, &view, session).unwrap();
    let read = fixture.read(&key).unwrap();
    assert_eq!(read.value.bytes, bytes);
    assert!(read.version.len() <= contract::VERSION_BYTES);
    let (view, mut session) = fixture.session();
    assert_eq!(
        session.put(
            &view,
            vec![7; contract::KEY_BYTES + 1],
            value(b"bad"),
            allow
        ),
        Err(StateError::Limit)
    );
    let exhausted = Fixture::with_quota(NamespaceQuota::default(), u64::MAX);
    let (view, mut session) = exhausted.session();
    session
        .put(&view, b"key".to_vec(), value(b"never"), allow)
        .unwrap();
    assert!(matches!(session.seal(&view, allow), Err(StateError::Limit)));
    assert_eq!(exhausted.read(b"key"), None);
}

#[test]
fn controlled_parallel_history_matches_the_serializable_generation_model() {
    use std::sync::{Arc, Barrier};
    let fixture = Arc::new(Fixture::new());
    fixture.write(&[(b"counter", Some(b"0"))]);
    let ready = Arc::new(Barrier::new(3));
    let threads = (0..2)
        .map(|_| {
            let fixture = Arc::clone(&fixture);
            let ready = Arc::clone(&ready);
            std::thread::spawn(move || {
                let (view, mut session) = fixture.session();
                assert_eq!(
                    session
                        .get(&view, b"counter", allow)
                        .unwrap()
                        .unwrap()
                        .value
                        .bytes,
                    b"0"
                );
                session
                    .put(&view, b"counter".to_vec(), value(b"1"), allow)
                    .unwrap();
                ready.wait();
                commit(&fixture.store, &view, session)
            })
        })
        .collect::<Vec<_>>();
    ready.wait();
    let outcomes = threads
        .into_iter()
        .map(|thread| thread.join().unwrap())
        .collect::<Vec<_>>();
    assert_eq!(outcomes.iter().filter(|outcome| outcome.is_ok()).count(), 1);
    assert_eq!(
        outcomes
            .iter()
            .filter(|outcome| **outcome == Err(StateError::Conflict))
            .count(),
        1
    );
    assert_eq!(fixture.read(b"counter").unwrap().value.bytes, b"1");
}
