//! Bounded descriptive inventory. It never grants deletion or read authority.
use super::{tenant, Arc, LocalBlobError, LocalBlobStore, Ordering, Result, TenantId, Work};
use crate::BlobReference;
use std::ops::Bound::{Excluded, Unbounded};

/// One page of references belonging to the requested tenant. `complete` says
/// only that this exact in-memory generation was traversed, not that any object
/// is an orphan or can be deleted.
pub struct LocalReferencePage {
    references: Vec<BlobReference>,
    pub complete: bool,
    // The copied page remains charged until its actual owner retires.
    _work: Work,
}

impl LocalReferencePage {
    #[must_use]
    pub fn references(&self) -> &[BlobReference] {
        &self.references
    }
}

/// A bounded physical inventory bound to its original local owner, tenant and
/// mutation generation. The trusted host must authorize the tenant separately.
/// Holding it consumes an existing native work slot; it grants no blob access.
pub struct LocalReferenceInventory {
    work: Work,
    tenant: TenantId,
    generation: u64,
    after: Option<String>,
    complete: bool,
}

impl LocalReferenceInventory {
    pub fn begin(store: &LocalBlobStore, scope: &TenantId) -> Result<Self> {
        tenant(scope)?;
        let work = store.inner.work()?;
        let generation = {
            let state = store.inner.state()?;
            if store.inner.publishing.load(Ordering::Acquire) {
                return Err(LocalBlobError::Busy);
            }
            state.inventory_generation
        };
        Ok(Self {
            work,
            tenant: scope.clone(),
            generation,
            after: None,
            complete: false,
        })
    }

    /// Visit at most 64 physical entries per call, including entries for other
    /// tenants and released records. A mutation invalidates the entire cursor.
    pub fn next_page(
        &mut self,
        store: &LocalBlobStore,
        maximum_entries: usize,
        checkpoint: &dyn Fn() -> Result<()>,
    ) -> Result<LocalReferencePage> {
        if self.complete
            || maximum_entries == 0
            || maximum_entries > 64
            || !Arc::ptr_eq(&self.work.inner, &store.inner)
        {
            return Err(LocalBlobError::Invalid);
        }
        checkpoint()?;
        let page_work = store.inner.work()?;
        let (references, after, complete) = {
            let state = store.inner.state()?;
            if store.inner.publishing.load(Ordering::Acquire)
                || state.inventory_generation != self.generation
            {
                return Err(LocalBlobError::Busy);
            }
            let lower = self.after.as_ref().map_or(Unbounded, Excluded);
            let mut entries = state.objects.range::<String, _>((lower, Unbounded));
            let mut references = Vec::with_capacity(maximum_entries);
            let mut after = self.after.clone();
            let mut visited = 0;
            for (key, object) in entries.by_ref().take(maximum_entries) {
                visited += 1;
                after = Some(key.clone());
                if object.referenced.load(Ordering::Acquire) {
                    let record = object.record.as_ref().ok_or(LocalBlobError::Corrupt)?;
                    if record.tenant == self.tenant.0 {
                        references.push(record.reference());
                    }
                }
            }
            // An exactly full page may need one final empty call; never inspect
            // an extra physical entry beyond the caller's bound.
            (references, after, visited < maximum_entries)
        };
        checkpoint()?;
        {
            let state = store.inner.state()?;
            if store.inner.publishing.load(Ordering::Acquire)
                || state.inventory_generation != self.generation
            {
                return Err(LocalBlobError::Busy);
            }
            self.after = after;
            self.complete = complete;
        }
        Ok(LocalReferencePage {
            references,
            complete,
            _work: page_work,
        })
    }
}
