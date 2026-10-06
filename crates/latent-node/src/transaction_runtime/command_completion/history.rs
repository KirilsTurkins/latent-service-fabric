//! Original committed views cannot be renewed by another recovery history.
use latent_commit::atomic::CommandRecord;
use latent_core::{StateNamespaceId, TenantId};
use latent_state::{
    embedded::{ReadView, StoreError},
    session::{version::capture_view_identity, StateError, StateMode, StateScope},
};

pub(super) fn require_record(view: &ReadView, record: &CommandRecord) -> Result<(), StoreError> {
    let key = record.key();
    require_token(
        view,
        &StateScope {
            tenant: TenantId(key.tenant.clone()),
            namespace: StateNamespaceId(key.namespace.clone()),
            incarnation: key.incarnation.parse().map_err(|_| StoreError::Corrupt)?,
            state_schema: record.source().state_schema.clone(),
            entity: key.entity.clone(),
            mode: StateMode::Query,
        },
        record.committed_view_token(),
    )
}

pub(super) fn require_result_record(
    view: &ReadView,
    record: &CommandRecord,
    authorization: &super::super::StateAuthorization,
) -> Result<(), StoreError> {
    if authorization.authority.original_result().is_some() {
        let key = record.key();
        let namespace = latent_state::namespace::catalog::NamespaceCatalog::read_in(
            view,
            &TenantId(key.tenant.clone()),
            &StateNamespaceId(key.namespace.clone()),
        )
        .map_err(|_| StoreError::Corrupt)?
        .ok_or(StoreError::Unavailable)?;
        authorization
            .authority
            .require_result_history(view, &namespace, record)
    } else {
        require_record(view, record)
    }
}

fn require_token(
    view: &ReadView,
    scope: &StateScope,
    original: Option<&[u8]>,
) -> Result<(), StoreError> {
    let current = capture_view_identity(view, scope).map_err(history_error)?;
    if let Some(original) = original {
        current
            .require_minimum(scope, original)
            .map_err(history_error)?;
    }
    Ok(())
}

fn history_error(error: StateError) -> StoreError {
    match error {
        StateError::Corrupt | StateError::Invalid => StoreError::Corrupt,
        _ => StoreError::Unavailable,
    }
}

pub(super) fn atomic_error(error: StoreError) -> latent_commit::atomic::AtomicError {
    use latent_commit::atomic::AtomicError;
    match error {
        StoreError::Corrupt => AtomicError::Corrupt,
        StoreError::UnsupportedFormat => AtomicError::UnsupportedFormat,
        _ => AtomicError::RecoveryRequired,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use latent_state::{
        embedded::{AtomicBatch, EmbeddedStore, Family, RowKey, RowMutation, StoreLimits},
        namespace::{
            history::{history_key, NamespaceHistory},
            namespace_record_key, NamespaceQuota, NamespaceRecord,
        },
    };
    use std::fs::OpenOptions;

    #[test]
    fn actual_retained_view_allows_business_advance_and_refuses_new_recovery_or_schema() {
        let directory = tempfile::tempdir().unwrap();
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(directory.path().join("result-history.redb"))
            .unwrap();
        let store = EmbeddedStore::open_file(file, StoreLimits::default()).unwrap();
        let scope = StateScope {
            tenant: TenantId("tenant".into()),
            namespace: StateNamespaceId("business".into()),
            incarnation: 1,
            state_schema: format!("sha256:{}", "1".repeat(64)),
            entity: None,
            mode: StateMode::Query,
        };
        let mut namespace = NamespaceRecord::create(
            scope.tenant.clone(),
            scope.namespace.clone(),
            scope.state_schema.clone(),
            NamespaceQuota::default(),
        )
        .unwrap();
        let key = RowKey {
            family: Family::Namespace,
            key: namespace_record_key(&scope.tenant, &scope.namespace).unwrap(),
        };
        write(&store, key.clone(), namespace.encode().unwrap());
        let view = store.snapshot().unwrap();
        let original = capture_view_identity(&view, &scope)
            .unwrap()
            .token(&scope)
            .unwrap();
        drop(view);
        namespace.version.generation += 1;
        write(&store, key, namespace.encode().unwrap());
        require_token(&store.snapshot().unwrap(), &scope, Some(&original)).unwrap();
        let history_key = history_key(&scope.tenant, &scope.namespace, 1).unwrap();
        let mut history = NamespaceHistory::initial(&namespace);
        history.epochs.recovery += 1;
        write(&store, history_key.clone(), history.encode().unwrap());
        assert_eq!(
            require_token(&store.snapshot().unwrap(), &scope, Some(&original)),
            Err(StoreError::Unavailable)
        );
        history.epochs.recovery = 1;
        history.epochs.schema += 1;
        write(&store, history_key, history.encode().unwrap());
        assert_eq!(
            require_token(&store.snapshot().unwrap(), &scope, Some(&original)),
            Err(StoreError::Unavailable)
        );
    }

    fn write(store: &EmbeddedStore, key: latent_state::embedded::RowKey, bytes: Vec<u8>) {
        let view = store.snapshot().unwrap();
        let old = view.get(&key).unwrap();
        drop(view);
        store
            .apply(AtomicBatch {
                expectations: vec![latent_state::embedded::ExpectedRow {
                    key: key.clone(),
                    value: old,
                }],
                mutations: vec![RowMutation {
                    key,
                    value: Some(bytes),
                }],
            })
            .unwrap();
    }
}
