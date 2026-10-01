//! Shared-engine persistence/preparation ports. All returned rows/batches are
//! non-authorizing; the namespace/policy owner invokes its final currentness
//! callback inside `EmbeddedStore::apply_fenced` before physical commit. This
//! module never opens a path, creates a second database or holds a policy lock.

use std::sync::Arc;

use crate::embedded::{
    AtomicBatch, EmbeddedStore, ExpectedRow, Family, ReadView, RowKey, RowMutation, StoreError,
};
use latent_core::{StateNamespaceId, TenantId};

use super::{
    identity, namespace_operation_key, namespace_record_key, namespace_tenant_prefix,
    NamespaceError, NamespaceQuota, NamespaceRecord, NamespaceTransition, NamespaceVersion,
    RECORD_BYTES,
};

const RECEIPT_MAGIC: &[u8] = b"lsf-namespace-operation-v1\0";
const RECEIPT_BYTES: usize = 8192;

/// Host-derived authenticated context. It contains no reusable credentials.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NamespaceOperationContext {
    pub tenant: TenantId,
    pub actor: String,
    pub operation_id: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum NamespaceMutation {
    Create {
        id: StateNamespaceId,
        state_schema: String,
        quota: NamespaceQuota,
    },
    Transition {
        id: StateNamespaceId,
        expected: NamespaceVersion,
        action: NamespaceTransition,
    },
}

impl NamespaceMutation {
    fn id(&self) -> &StateNamespaceId {
        match self {
            Self::Create { id, .. } | Self::Transition { id, .. } => id,
        }
    }

    /// Exact bounded canonical request bytes. Expected versions survive replay.
    fn canonical(&self) -> Result<Vec<u8>, NamespaceError> {
        let (tag, record) = match self {
            Self::Create {
                id,
                state_schema,
                quota,
            } => (
                1,
                NamespaceRecord::create(
                    TenantId("request".into()),
                    id.clone(),
                    state_schema.clone(),
                    *quota,
                )?,
            ),
            Self::Transition {
                id,
                expected,
                action,
            } => {
                identity(&id.0)?;
                if expected.incarnation == 0 || expected.generation == 0 {
                    return Err(NamespaceError::Invalid);
                }
                let mut bytes = vec![2];
                super::frame(&mut bytes, id.0.as_bytes())?;
                bytes.extend_from_slice(&expected.incarnation.to_le_bytes());
                bytes.extend_from_slice(&expected.generation.to_le_bytes());
                match action {
                    NamespaceTransition::Quiesce => bytes.push(1),
                    NamespaceTransition::Retire => bytes.push(2),
                    NamespaceTransition::Destroy => bytes.push(3),
                    NamespaceTransition::Recreate {
                        state_schema,
                        quota,
                    } => {
                        bytes.push(4);
                        let next = NamespaceRecord::create(
                            TenantId("request".into()),
                            id.clone(),
                            state_schema.clone(),
                            *quota,
                        )?;
                        bytes.extend_from_slice(&next.encode()?);
                    }
                }
                return Ok(bytes);
            }
        };
        let mut bytes = vec![tag];
        bytes.extend_from_slice(&record.encode()?);
        Ok(bytes)
    }
}

/// Immutable historical outcome, distinct from current inspection permission.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NamespaceOperationReceipt {
    pub context: NamespaceOperationContext,
    pub record: NamespaceRecord,
    request: Vec<u8>,
}

impl NamespaceOperationReceipt {
    fn encode(&self) -> Result<Vec<u8>, NamespaceError> {
        identity(&self.context.actor)?;
        identity(&self.context.operation_id)?;
        let record = self.record.encode()?;
        let mut bytes = RECEIPT_MAGIC.to_vec();
        for value in [
            self.context.tenant.0.as_bytes(),
            self.context.actor.as_bytes(),
            self.context.operation_id.as_bytes(),
            self.request.as_slice(),
            record.as_slice(),
        ] {
            super::frame(&mut bytes, value)?;
        }
        if bytes.len() > RECEIPT_BYTES {
            return Err(NamespaceError::Capacity);
        }
        Ok(bytes)
    }

    fn decode(bytes: &[u8]) -> Result<Self, NamespaceError> {
        if bytes.len() > RECEIPT_BYTES || !bytes.starts_with(RECEIPT_MAGIC) {
            return Err(NamespaceError::Corrupt);
        }
        let mut cursor = super::Cursor {
            bytes,
            offset: RECEIPT_MAGIC.len(),
        };
        let context = NamespaceOperationContext {
            tenant: TenantId(cursor.text()?),
            actor: cursor.text()?,
            operation_id: cursor.text()?,
        };
        let request_bytes = usize::from(cursor.u16()?);
        if request_bytes > RECORD_BYTES + 1024 {
            return Err(NamespaceError::Corrupt);
        }
        let request = cursor.take(request_bytes)?.to_vec();
        let record_bytes = usize::from(cursor.u16()?);
        let record = NamespaceRecord::decode(cursor.take(record_bytes)?)?;
        if cursor.offset != bytes.len() || record.tenant != context.tenant {
            return Err(NamespaceError::Corrupt);
        }
        identity(&context.actor).map_err(|_| NamespaceError::Corrupt)?;
        identity(&context.operation_id).map_err(|_| NamespaceError::Corrupt)?;
        Ok(Self {
            context,
            record,
            request,
        })
    }
}

/// Keep the exact expected namespace/receipt rows in the final engine writer.
/// Consumers must not strip these expectations or publish the record separately.
#[derive(Debug)]
pub struct PreparedNamespaceMutation {
    pub batch: AtomicBatch,
    pub receipt: NamespaceOperationReceipt,
    pub replay: bool,
}

/// A decoded row and its exact bytes from one engine read view. It is data,
/// never an allow decision. Preserve `expectation()` in the actual writer.
pub struct NamespaceRead {
    record: NamespaceRecord,
    expected: ExpectedRow,
}

impl NamespaceRead {
    #[must_use]
    pub fn record(&self) -> &NamespaceRecord {
        &self.record
    }

    #[must_use]
    pub fn expectation(&self) -> ExpectedRow {
        self.expected.clone()
    }
}

/// Descriptive bounded page: callers authorize a tenant before loading, and bind
/// any public cursor to current actor/scope/view policy through the authority port.
#[derive(Debug)]
pub struct NamespacePage {
    pub records: Vec<NamespaceRecord>,
    pub next_after: Option<StateNamespaceId>,
}

pub struct NamespaceCatalog {
    store: Arc<EmbeddedStore>,
}

impl NamespaceCatalog {
    #[must_use]
    pub fn new(store: Arc<EmbeddedStore>) -> Self {
        Self { store }
    }

    pub fn inspect(
        &self,
        tenant: &TenantId,
        id: &StateNamespaceId,
    ) -> Result<Option<NamespaceRecord>, NamespaceError> {
        let view = self.store.snapshot().map_err(storage)?;
        Ok(Self::read_in(&view, tenant, id)?.map(|read| read.record))
    }

    /// Read namespace metadata in the same view used for state/OCC inputs.
    /// A transaction must keep the returned expectation beside every state,
    /// outbox and outcome mutation in its single `AtomicBatch`.
    pub fn read_in(
        view: &ReadView,
        tenant: &TenantId,
        id: &StateNamespaceId,
    ) -> Result<Option<NamespaceRead>, NamespaceError> {
        let key = RowKey {
            family: Family::Namespace,
            key: namespace_record_key(tenant, id)?,
        };
        view.get(&key)
            .map_err(storage)?
            .map(|bytes| {
                let record = decode_scoped(&bytes, tenant, id)?;
                Ok(NamespaceRead {
                    record,
                    expected: ExpectedRow {
                        key,
                        value: Some(bytes),
                    },
                })
            })
            .transpose()
    }

    pub fn outcome(
        &self,
        context: &NamespaceOperationContext,
    ) -> Result<Option<NamespaceOperationReceipt>, NamespaceError> {
        let key = RowKey {
            family: Family::Namespace,
            key: namespace_operation_key(&context.tenant, &context.actor, &context.operation_id)?,
        };
        let bytes = self
            .store
            .snapshot()
            .map_err(storage)?
            .get(&key)
            .map_err(storage)?;
        let receipt = bytes
            .map(|bytes| NamespaceOperationReceipt::decode(&bytes))
            .transpose()?;
        if receipt
            .as_ref()
            .is_some_and(|receipt| receipt.context != *context)
        {
            return Err(NamespaceError::Corrupt);
        }
        Ok(receipt)
    }

    /// Preparation can perform bounded reads. Authorization/cancellation and
    /// active owner checks must be repeated in the store's actual commit callback.
    pub fn prepare(
        &self,
        context: NamespaceOperationContext,
        mutation: &NamespaceMutation,
        active_commits: u64,
    ) -> Result<PreparedNamespaceMutation, NamespaceError> {
        let namespace_key = RowKey {
            family: Family::Namespace,
            key: namespace_record_key(&context.tenant, mutation.id())?,
        };
        let operation_key = RowKey {
            family: Family::Namespace,
            key: namespace_operation_key(&context.tenant, &context.actor, &context.operation_id)?,
        };
        let request = mutation.canonical()?;
        let view = self.store.snapshot().map_err(storage)?;
        if let Some(bytes) = view.get(&operation_key).map_err(storage)? {
            let receipt = NamespaceOperationReceipt::decode(&bytes)?;
            if receipt.context != context || receipt.request != request {
                return Err(NamespaceError::Conflict);
            }
            return Ok(PreparedNamespaceMutation {
                batch: AtomicBatch::default(),
                receipt,
                replay: true,
            });
        }
        let previous = view.get(&namespace_key).map_err(storage)?;
        let record = match mutation {
            NamespaceMutation::Create {
                id,
                state_schema,
                quota,
            } => {
                if previous.is_some() {
                    return Err(NamespaceError::Conflict);
                }
                NamespaceRecord::create(
                    context.tenant.clone(),
                    id.clone(),
                    state_schema.clone(),
                    *quota,
                )?
            }
            NamespaceMutation::Transition {
                id,
                expected,
                action,
            } => {
                let record = decode_scoped(
                    previous.as_deref().ok_or(NamespaceError::Conflict)?,
                    &context.tenant,
                    id,
                )?;
                record.transition(*expected, action, active_commits)?
            }
        };
        let receipt = NamespaceOperationReceipt {
            context,
            record,
            request,
        };
        let encoded_record = receipt.record.encode()?;
        let encoded_receipt = receipt.encode()?;
        let batch = AtomicBatch {
            expectations: vec![
                ExpectedRow {
                    key: namespace_key.clone(),
                    value: previous,
                },
                ExpectedRow {
                    key: operation_key.clone(),
                    value: None,
                },
            ],
            mutations: vec![
                RowMutation {
                    key: namespace_key,
                    value: Some(encoded_record),
                },
                RowMutation {
                    key: operation_key,
                    value: Some(encoded_receipt),
                },
            ],
        };
        Ok(PreparedNamespaceMutation {
            batch,
            receipt,
            replay: false,
        })
    }

    /// Internal scoped enumeration, not authorization or an external cursor.
    /// Fetch exactly one bounded tenant prefix; never compute global counts.
    pub fn page(
        &self,
        tenant: &TenantId,
        after: Option<&StateNamespaceId>,
        limit: usize,
    ) -> Result<NamespacePage, NamespaceError> {
        let view = self.store.snapshot().map_err(storage)?;
        Self::page_in(&view, tenant, after, limit)
    }

    /// An owned caller-scoped page resource retains this exact `ReadView` for
    /// every pull. The external authority binds its cursor before invoking us.
    pub fn page_in(
        view: &ReadView,
        tenant: &TenantId,
        after: Option<&StateNamespaceId>,
        limit: usize,
    ) -> Result<NamespacePage, NamespaceError> {
        if limit == 0 || limit > 128 {
            return Err(NamespaceError::Capacity);
        }
        let after_key = after
            .map(|id| namespace_record_key(tenant, id))
            .transpose()?;
        let page = view
            .scan_after(
                Family::Namespace,
                &namespace_tenant_prefix(tenant)?,
                after_key.as_deref(),
                limit,
                1024 * 1024,
            )
            .map_err(storage)?;
        let mut records = Vec::new();
        for (key, bytes) in page.rows {
            let record = NamespaceRecord::decode(&bytes)?;
            if record.tenant != *tenant || namespace_record_key(tenant, &record.id)? != key.key {
                return Err(NamespaceError::Corrupt);
            }
            records.push(record);
        }
        let next_after = page
            .resume
            .and_then(|_| records.last().map(|record| record.id.clone()));
        Ok(NamespacePage {
            records,
            next_after,
        })
    }
}

fn decode_scoped(
    bytes: &[u8],
    tenant: &TenantId,
    id: &StateNamespaceId,
) -> Result<NamespaceRecord, NamespaceError> {
    let record = NamespaceRecord::decode(bytes)?;
    if record.tenant != *tenant || record.id != *id {
        return Err(NamespaceError::Corrupt);
    }
    Ok(record)
}

fn storage(error: StoreError) -> NamespaceError {
    match error {
        StoreError::Invalid => NamespaceError::Invalid,
        StoreError::Capacity => NamespaceError::Capacity,
        StoreError::Conflict => NamespaceError::Conflict,
        StoreError::CommitUncertain => NamespaceError::RecoveryRequired,
        StoreError::Corrupt | StoreError::UnsupportedFormat => NamespaceError::Corrupt,
        StoreError::Unavailable | StoreError::SnapshotExpired => NamespaceError::Unavailable,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::embedded::StoreLimits;
    use std::fs::OpenOptions;

    fn context(operation_id: &str) -> NamespaceOperationContext {
        NamespaceOperationContext {
            tenant: TenantId("a".into()),
            actor: "alice".into(),
            operation_id: operation_id.into(),
        }
    }
    fn create(id: &str) -> NamespaceMutation {
        NamespaceMutation::Create {
            id: StateNamespaceId(id.into()),
            state_schema: format!("sha256:{}", "1".repeat(64)),
            quota: NamespaceQuota::default(),
        }
    }
    fn open(path: &std::path::Path) -> Arc<EmbeddedStore> {
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(path)
            .unwrap();
        Arc::new(EmbeddedStore::open_file(file, StoreLimits::default()).unwrap())
    }

    #[test]
    fn actual_engine_namespace_and_receipt_commit_atomically_and_recover_after_reopen() {
        let temporary = tempfile::tempdir().unwrap();
        let path = temporary.path().join("namespace.redb");
        let store = open(&path);
        let catalog = NamespaceCatalog::new(Arc::clone(&store));
        let prepared = catalog
            .prepare(context("create"), &create("opaque"), 0)
            .unwrap();
        let receipt = prepared.receipt.clone();
        // Trusted fixture persists data only; this is not production authorization.
        store.apply(prepared.batch).unwrap();
        assert_eq!(
            catalog
                .inspect(&TenantId("a".into()), &StateNamespaceId("opaque".into()))
                .unwrap(),
            Some(receipt.record.clone())
        );
        drop(catalog);
        drop(store);
        let store = open(&path);
        let catalog = NamespaceCatalog::new(Arc::clone(&store));
        assert_eq!(catalog.outcome(&context("create")).unwrap(), Some(receipt));
        assert!(
            catalog
                .prepare(context("create"), &create("opaque"), 0)
                .unwrap()
                .replay
        );
        assert!(catalog
            .inspect(&TenantId("b".into()), &StateNamespaceId("opaque".into()))
            .unwrap()
            .is_none());
    }

    #[test]
    fn concurrent_lifecycle_candidates_have_one_cas_winner_and_changed_operation_is_rejected() {
        let temporary = tempfile::tempdir().unwrap();
        let store = open(&temporary.path().join("namespace.redb"));
        let catalog = NamespaceCatalog::new(Arc::clone(&store));
        let first = catalog
            .prepare(context("create"), &create("opaque"), 0)
            .unwrap();
        let original = first.receipt.record;
        store.apply(first.batch).unwrap();
        let mutation = NamespaceMutation::Transition {
            id: original.id,
            expected: original.version,
            action: NamespaceTransition::Quiesce,
        };
        let left = catalog.prepare(context("left"), &mutation, 0).unwrap();
        let right = catalog.prepare(context("right"), &mutation, 0).unwrap();
        store.apply(left.batch).unwrap();
        assert_eq!(store.apply(right.batch), Err(StoreError::Conflict));
        assert!(catalog.outcome(&context("right")).unwrap().is_none());
        assert!(
            catalog
                .prepare(context("left"), &mutation, 0)
                .unwrap()
                .replay
        );
        assert!(matches!(
            catalog.prepare(context("left"), &create("other"), 0),
            Err(NamespaceError::Conflict)
        ));
    }

    #[test]
    fn scoped_enumeration_is_bounded_and_does_not_include_operation_receipts() {
        let temporary = tempfile::tempdir().unwrap();
        let store = open(&temporary.path().join("namespace.redb"));
        let catalog = NamespaceCatalog::new(Arc::clone(&store));
        for id in ["aa", "bb", "cc"] {
            store
                .apply(catalog.prepare(context(id), &create(id), 0).unwrap().batch)
                .unwrap();
        }
        let first = catalog.page(&TenantId("a".into()), None, 2).unwrap();
        assert_eq!(first.records.len(), 2);
        let next = catalog
            .page(&TenantId("a".into()), first.next_after.as_ref(), 2)
            .unwrap();
        assert_eq!(next.records.len(), 1);
        assert!(catalog
            .page(&TenantId("b".into()), None, 2)
            .unwrap()
            .records
            .is_empty());
        assert!(matches!(
            catalog.page(&TenantId("a".into()), None, 129),
            Err(NamespaceError::Capacity)
        ));
    }

    #[test]
    fn coherent_pages_cross_engine_limit_and_mixed_length_keys_without_omission() {
        let temporary = tempfile::tempdir().unwrap();
        let store = open(&temporary.path().join("namespace.redb"));
        let catalog = NamespaceCatalog::new(Arc::clone(&store));
        let mut batch = AtomicBatch::default();
        for index in 0..260 {
            let id = format!("{}-{index}", "n".repeat(index % 5 + 1));
            let prepared = catalog.prepare(context(&id), &create(&id), 0).unwrap();
            batch.expectations.extend(prepared.batch.expectations);
            batch.mutations.extend(prepared.batch.mutations);
            if batch.mutations.len() == 128 || index == 259 {
                store.apply(std::mem::take(&mut batch)).unwrap();
            }
        }
        let view = store.snapshot().unwrap();
        store
            .apply(
                catalog
                    .prepare(context("new"), &create("new"), 0)
                    .unwrap()
                    .batch,
            )
            .unwrap();
        let mut cursor = None;
        let mut found = std::collections::BTreeSet::new();
        loop {
            let page = NamespaceCatalog::page_in(&view, &TenantId("a".into()), cursor.as_ref(), 7)
                .unwrap();
            assert!(page.records.len() <= 7);
            for record in page.records {
                assert!(found.insert(record.id));
            }
            cursor = page.next_after;
            if cursor.is_none() {
                break;
            }
        }
        assert_eq!(found.len(), 260);
        assert!(!found.contains(&StateNamespaceId("new".into())));
    }
}
