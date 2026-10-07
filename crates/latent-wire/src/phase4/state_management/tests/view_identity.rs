use super::*;
use latent_core::TenantId;
use latent_state::{
    embedded::{AtomicBatch, ExpectedRow, RowMutation, StoreError},
    namespace::{
        history::{history_key, HistoryEpochs, HistoryStatus, NamespaceHistory},
        NamespaceRecord, NamespaceVersion,
    },
    session::{
        version::{ViewIdentity, VIEW_TOKEN_BYTES},
        StateError, StateMode, StateScope,
    },
    store_io::StoreIoKind,
};

fn inspected(response: &OwnedPhase4Response) -> &c::NamespaceInspection {
    let contract::Response::InspectNamespace(value) = &response.response else {
        panic!("wrong namespace inspection response")
    };
    value.namespace.as_ref().unwrap()
}

fn scope(inspection: &c::NamespaceInspection) -> StateScope {
    let view = inspection.view.as_ref().unwrap();
    let namespace = view.namespace.as_ref().unwrap();
    StateScope {
        tenant: TenantId(namespace.tenant.clone()),
        namespace: StateNamespaceId(namespace.namespace.clone()),
        incarnation: namespace.incarnation.parse().unwrap(),
        state_schema: view.state_schema.clone(),
        entity: None,
        mode: StateMode::Query,
    }
}

async fn write_history(
    fixture: &Fixture,
    rewrite: impl FnOnce(&NamespaceRecord) -> Option<Vec<u8>> + Send + 'static,
) {
    fixture
        .store
        .with_store(StoreIoKind::RecoveryWrite, 65_536, move |engine| {
            let view = engine.snapshot()?;
            let read = NamespaceCatalog::read_in(
                &view,
                &TenantId("a".into()),
                &StateNamespaceId("orders".into()),
            )
            .map_err(inspection::native_namespace)?
            .unwrap();
            let key = history_key(
                &read.record().tenant,
                &read.record().id,
                read.record().version.incarnation,
            )
            .unwrap();
            let old = view.get(&key)?;
            // Trusted fixture setup changes only real history metadata. It
            // retains the exact namespace and history expectations in one CAS.
            engine.apply(AtomicBatch {
                expectations: vec![
                    read.expectation(),
                    ExpectedRow {
                        key: key.clone(),
                        value: old,
                    },
                ],
                mutations: vec![RowMutation {
                    key,
                    value: rewrite(read.record()),
                }],
            })
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
}

#[tokio::test]
async fn authenticated_namespace_inspection_uses_canonical_scope_bound_legacy_history_token() {
    let mut fixture = Fixture::new(true).await;
    drop(fixture.create().await);
    // Absence is the codec's supported legacy epoch1, rather than a synthetic
    // replacement for present history or an execution-readiness decision.
    write_history(&fixture, |_| None).await;
    let response = fixture
        .backend
        .execute_state(context("alice"), fixture.target().into())
        .await
        .unwrap();
    let inspection = inspected(&response);
    let scope = scope(inspection);
    let token = &inspection.view.as_ref().unwrap().version;
    assert_eq!(token.len(), VIEW_TOKEN_BYTES);
    assert_eq!(token.len(), 67);
    assert_eq!(
        ViewIdentity::from_token(&scope, token).unwrap(),
        ViewIdentity {
            namespace: NamespaceVersion {
                incarnation: 1,
                generation: 1,
            },
            epochs: HistoryEpochs {
                schema: 1,
                recovery: 1,
            },
        }
    );
    for changed in [
        StateScope {
            namespace: StateNamespaceId("other".into()),
            ..scope.clone()
        },
        StateScope {
            state_schema: format!("sha256:{}", "3".repeat(64)),
            ..scope.clone()
        },
        StateScope {
            entity: Some("order-1".into()),
            ..scope.clone()
        },
    ] {
        assert_eq!(
            ViewIdentity::from_token(&changed, token),
            Err(StateError::Invalid)
        );
    }
    response.owner.with_current(&mut || {}).unwrap();
    drop(response);
    assert!(fixture.store.failure().is_none());
    fixture.finish().await;
}

#[tokio::test]
async fn paused_namespace_history_remains_inspectable_with_actual_schema_and_recovery_epochs() {
    let mut fixture = Fixture::new(true).await;
    drop(fixture.create().await);
    let original = fixture
        .backend
        .execute_state(context("alice"), fixture.target().into())
        .await
        .unwrap();
    let scope = scope(inspected(&original));
    let old = inspected(&original).view.as_ref().unwrap().version.clone();
    drop(original);
    for (epochs, status) in [
        (
            HistoryEpochs {
                schema: 2,
                recovery: 1,
            },
            HistoryStatus::Ready,
        ),
        (
            HistoryEpochs {
                schema: 2,
                recovery: 2,
            },
            HistoryStatus::ReconciliationRequired,
        ),
    ] {
        write_history(&fixture, move |namespace| {
            let mut history = NamespaceHistory::initial(namespace);
            history.epochs = epochs;
            history.status = status;
            Some(history.encode().unwrap())
        })
        .await;
        let response = fixture
            .backend
            .execute_state(context("alice"), fixture.target().into())
            .await
            .unwrap();
        let inspection = inspected(&response);
        let identity =
            ViewIdentity::from_token(&scope, &inspection.view.as_ref().unwrap().version).unwrap();
        assert_eq!(inspection.generation, 1);
        assert_eq!(inspection.status, c::NamespaceStatus::Active as i32);
        assert_eq!(identity.namespace.generation, 1);
        assert_eq!(identity.epochs, epochs);
        assert_eq!(
            identity.require_minimum(&scope, &old),
            Err(StateError::RecoveryRequired)
        );
        response.owner.with_current(&mut || {}).unwrap();
        drop(response);
        // Paused history is healthy descriptive metadata, not physical failure.
        assert!(fixture.store.failure().is_none());
    }
    fixture.finish().await;
}

#[tokio::test]
async fn malformed_or_wrong_scope_history_cannot_fall_back_to_an_inspection_token_on_restart() {
    for invalid in 0..3 {
        let fixture = Fixture::new(false).await;
        drop(fixture.create().await);
        write_history(&fixture, move |namespace| {
            let mut history = NamespaceHistory::initial(namespace);
            match invalid {
                0 => {
                    history.namespace = StateNamespaceId("other".into());
                    Some(history.encode().unwrap())
                }
                1 => Some(b"NSH\x7f".to_vec()),
                _ => {
                    let mut bytes = history.encode().unwrap();
                    bytes.pop();
                    Some(bytes)
                }
            }
        })
        .await;
        let error = fixture
            .backend
            .execute_state(context("alice"), fixture.target().into())
            .await
            .err()
            .unwrap();
        assert_eq!(error.code, PlatformErrorCode::Unavailable);
        assert_eq!(
            fixture.store.failure(),
            Some(ProtectedStoreError::Store(StoreError::Corrupt))
        );
        fixture.store.close();
        let drained = tokio::time::timeout(
            Duration::from_secs(5),
            fixture
                .store
                .drain_async(deadline(), std::future::pending())
                .unwrap(),
        )
        .await
        .unwrap();
        assert!(!drained.clean);
        assert!(drained.snapshot.physically_retired());
        assert!(fixture
            .admission
            .native
            .snapshot()
            .unwrap()
            .physically_retired());
        assert_eq!(fixture.admission.budget.outstanding_reservations(), 0);
        let mut config = fixture.config.clone();
        config.create_if_missing = false;
        let mut reopened = Box::pin(
            ProtectedStoreOwner::start_validated(config, 0, |key, bytes| {
                NamespaceCatalog::validate_row(key, bytes).map_err(inspection::native_namespace)
            })
            .unwrap(),
        );
        assert!(matches!(
            tokio::time::timeout(Duration::from_secs(5), reopened.as_mut())
                .await
                .unwrap(),
            Err(ProtectedStoreError::Store(StoreError::Corrupt))
        ));
        let retired = tokio::time::timeout(
            Duration::from_secs(5),
            reopened
                .drain_async(deadline(), std::future::pending())
                .unwrap(),
        )
        .await
        .unwrap();
        assert!(!retired.clean);
        assert!(retired.snapshot.physically_retired());
    }
}
