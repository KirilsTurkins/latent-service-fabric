use crate::{
    embedded::{ExpectedRow, Family, ReadView, RowKey, StoreError},
    namespace::{
        catalog::NamespaceCatalog,
        history::{history_key, NamespaceHistory},
        namespace_record_key, NamespaceRecord,
    },
    recovery::RecoveryGuard,
    session::{version::ViewIdentity, StateMode, StateScope},
};
use latent_core::{StateNamespaceId, TenantId};

/// Same-view descriptive namespace/history/control inputs. No permission or
/// quiescence is inferred from these fields, an epoch, or a caller's clean flag.
pub struct NamespaceMigrationView {
    pub namespace: NamespaceRecord,
    pub history: NamespaceHistory,
    pub guard: Option<RecoveryGuard>,
    pub(super) namespace_expectation: ExpectedRow,
    pub(super) history_expectation: ExpectedRow,
    pub(super) guard_expectation: ExpectedRow,
}

impl NamespaceMigrationView {
    pub fn capture(
        view: &ReadView,
        tenant: &TenantId,
        namespace: &StateNamespaceId,
    ) -> Result<Self, StoreError> {
        let key = RowKey {
            family: Family::Namespace,
            key: namespace_record_key(tenant, namespace).map_err(|_| StoreError::Invalid)?,
        };
        let namespace_bytes = view
            .get_bounded(&key, crate::namespace::RECORD_BYTES)?
            .ok_or(StoreError::Invalid)?;
        NamespaceCatalog::validate_row(&key, &namespace_bytes).map_err(|_| StoreError::Corrupt)?;
        let record = NamespaceRecord::decode(&namespace_bytes).map_err(|_| StoreError::Corrupt)?;
        let (history, bytes) = NamespaceHistory::capture(view, &record)?;
        let guard = super::super::guard_key();
        let guard_bytes = view.get_bounded(&guard, super::super::GUARD_BYTES)?;
        Ok(Self {
            history_expectation: ExpectedRow {
                key: history_key(tenant, namespace, record.version.incarnation)
                    .map_err(|_| StoreError::Corrupt)?,
                value: bytes,
            },
            namespace_expectation: ExpectedRow {
                key,
                value: Some(namespace_bytes),
            },
            namespace: record,
            history,
            guard: guard_bytes
                .as_deref()
                .map(RecoveryGuard::decode)
                .transpose()?,
            guard_expectation: ExpectedRow {
                key: guard,
                value: guard_bytes,
            },
        })
    }

    #[must_use]
    pub fn scope(&self) -> StateScope {
        StateScope {
            tenant: self.namespace.tenant.clone(),
            namespace: self.namespace.id.clone(),
            incarnation: self.namespace.version.incarnation,
            state_schema: self.namespace.state_schema.clone(),
            entity: None,
            mode: StateMode::Command,
        }
    }

    pub fn view_token(&self) -> Result<Vec<u8>, StoreError> {
        ViewIdentity {
            namespace: self.namespace.version,
            epochs: self.history.epochs,
        }
        .token(&self.scope())
        .map_err(|_| StoreError::Corrupt)
    }
}
