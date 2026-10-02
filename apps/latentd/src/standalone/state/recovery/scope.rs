//! Descriptive row associations are compared with the original sealed scope.
//! They never add a second namespace or tenant grant to an offline operation.
use latent_core::TenantId;
use latent_state::{
    embedded::{ReadView, RowKey, StoreError},
    namespace::{NamespaceCatalog, NamespaceError},
};

pub(super) struct Scope<'a> {
    pub tenant: &'a TenantId,
    pub namespace: &'a str,
    pub incarnation: u64,
}
impl Scope<'_> {
    pub fn contains(&self, tenant: &str, namespace: &str, incarnation: u64) -> bool {
        self.tenant.0 == tenant && self.namespace == namespace && self.incarnation == incarnation
    }
    pub fn namespace_row(&self, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
        let (tenant, namespace, incarnation) =
            NamespaceCatalog::row_scope(key, bytes).map_err(|error| match error {
                NamespaceError::UnsupportedFormat => StoreError::UnsupportedFormat,
                _ => StoreError::Corrupt,
            })?;
        if self.contains(&tenant.0, &namespace.0, incarnation) {
            Ok(())
        } else {
            Err(StoreError::UnsupportedFormat)
        }
    }
    pub fn tenant_installation(&self, view: &ReadView) -> Result<(), StoreError> {
        if view.get(&latent_state::tenant::guard_key())?.is_none() {
            return Ok(());
        }
        let original = latent_state::tenant::inspect(view, self.tenant)?
            .ok_or(StoreError::UnsupportedFormat)?;
        // Only the already installed single-tenant manifest is accepted. This
        // performs no installation or inference of limits from namespaces.
        latent_state::tenant::require_installation(view, &[original.quota])?;
        Ok(())
    }
    pub fn tenant_row(&self, bytes: &[u8]) -> Result<(), StoreError> {
        let record = latent_state::tenant::TenantRecord::decode(bytes)?;
        if record.quota.tenant == *self.tenant {
            Ok(())
        } else {
            Err(StoreError::UnsupportedFormat)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use latent_core::StateNamespaceId;
    use latent_state::{
        embedded::{EmbeddedStore, Family, RowMutation, StoreLimits},
        namespace::{
            history::NamespaceHistory, NamespaceMutation, NamespaceOperationContext, NamespaceQuota,
        },
    };

    fn create(store: &EmbeddedStore, tenant: &str, namespace: &str) {
        let prepared = NamespaceCatalog::new()
            .prepare(
                store,
                NamespaceOperationContext {
                    tenant: TenantId(tenant.into()),
                    actor: "operator".into(),
                    operation_id: format!("create-{namespace}"),
                },
                &NamespaceMutation::Create {
                    id: StateNamespaceId(namespace.into()),
                    state_schema: format!("sha256:{}", "1".repeat(64)),
                    quota: NamespaceQuota::default(),
                },
                0,
            )
            .unwrap();
        let history = NamespaceHistory::initial(&prepared.receipt.record);
        let mut batch = prepared.batch;
        batch.mutations.push(RowMutation {
            key: latent_state::namespace::history::history_key(
                &history.tenant,
                &history.namespace,
                history.incarnation,
            )
            .unwrap(),
            value: Some(history.encode().unwrap()),
        });
        store.apply(batch).unwrap();
    }
    fn visit(scope: &Scope<'_>, view: &ReadView) -> Result<usize, StoreError> {
        let page = view.scan_after(Family::Namespace, b"", None, 32, 64 * 1024)?;
        for (key, bytes) in &page.rows {
            scope.namespace_row(key, bytes)?;
        }
        Ok(page.rows.len())
    }
    #[test]
    fn actual_namespace_rows_receipts_and_histories_refuse_unrelated_empty_scopes() {
        for (foreign_tenant, foreign_namespace) in [("tenant", "other"), ("other", "owned")] {
            let temporary = tempfile::tempdir().unwrap();
            let file = std::fs::OpenOptions::new()
                .read(true)
                .write(true)
                .create_new(true)
                .open(temporary.path().join("scope.redb"))
                .unwrap();
            let store = EmbeddedStore::open_file(file, StoreLimits::default()).unwrap();
            create(&store, "tenant", "owned");
            let tenant = TenantId("tenant".into());
            let scope = Scope {
                tenant: &tenant,
                namespace: "owned",
                incarnation: 1,
            };
            assert_eq!(visit(&scope, &store.snapshot().unwrap()), Ok(3));
            create(&store, foreign_tenant, foreign_namespace);
            let view = store.snapshot().unwrap();
            let page = view
                .scan_after(Family::Namespace, b"", None, 32, 64 * 1024)
                .unwrap();
            let mut refused = 0;
            for (key, bytes) in &page.rows {
                NamespaceCatalog::validate_row(key, bytes).unwrap();
                if scope.namespace_row(key, bytes) == Err(StoreError::UnsupportedFormat) {
                    refused += 1;
                }
            }
            assert_eq!(
                refused, 3,
                "namespace, operation receipt and history all remain scoped"
            );
            assert_eq!(visit(&scope, &view), Err(StoreError::UnsupportedFormat));
        }
    }
    #[test]
    fn malformed_owned_namespace_rows_do_not_become_foreign_scope_refusals() {
        let tenant = TenantId("tenant".into());
        let scope = Scope {
            tenant: &tenant,
            namespace: "owned",
            incarnation: 1,
        };
        for prefix in [b"ns-v1\0".as_slice(), b"ns-op-v1\0", b"ns-history-v1\0"] {
            let key = RowKey {
                family: Family::Namespace,
                key: prefix.to_vec(),
            };
            assert_eq!(
                scope.namespace_row(&key, b"malformed"),
                Err(StoreError::Corrupt)
            );
        }
        assert_eq!(
            scope.namespace_row(
                &RowKey {
                    family: Family::Namespace,
                    key: b"unknown".to_vec()
                },
                b"foreign"
            ),
            Err(StoreError::UnsupportedFormat)
        );
    }
}
