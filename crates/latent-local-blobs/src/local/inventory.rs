//! Bounded descriptive inventory. It never grants deletion or read authority.
use super::{
    tenant, Arc, Inner, LocalBlobError, LocalBlobStore, Ordering, Result, TenantId, Work,
    HANDLE_BYTES, OBJECT_BYTES,
};
use crate::BlobReference;
use std::ops::Bound::{Excluded, Unbounded};

// Conservative metadata reservations, independent of the finite work-slot cap.
// HANDLE_BYTES covers a cursor or page plus its bounded continuation/guard;
// OBJECT_BYTES covers each copied reference and its bounded tenant/media/digest.
// Audit dispositions also fit in the page's per-reference allowance.
pub(super) struct InventoryMemory {
    inner: Arc<Inner>,
    bytes: usize,
}
impl InventoryMemory {
    pub(super) fn reserve(inner: &Arc<Inner>, bytes: usize, headroom: usize) -> Result<Self> {
        let state = inner.state()?;
        inner.room(
            &state,
            bytes.checked_add(headroom).ok_or(LocalBlobError::Capacity)?,
        )?;
        // All admissions share the state lock with object/stage/handle growth.
        // Drop only subtracts, so fetch_add also preserves concurrent refunds.
        inner.inventory_bytes.fetch_add(bytes, Ordering::AcqRel);
        Ok(Self {
            inner: Arc::clone(inner),
            bytes,
        })
    }
}
impl Drop for InventoryMemory {
    fn drop(&mut self) {
        self.inner
            .inventory_bytes
            .fetch_sub(self.bytes, Ordering::AcqRel);
    }
}

/// One page of references belonging to the requested tenant. `complete` says
/// only that this exact in-memory generation was traversed, not that any object
/// is intact, is an orphan or can be deleted.
pub struct LocalReferencePage {
    references: Vec<BlobReference>,
    pub complete: bool,
    // The copied page remains charged until its actual owner retires.
    _work: Work,
    // Declared last so the copied references retire before their reservation.
    _memory: InventoryMemory,
}

impl LocalReferencePage {
    #[must_use]
    pub fn references(&self) -> &[BlobReference] {
        &self.references
    }
}

/// A bounded physical inventory bound to its original local owner, tenant and
/// mutation generation. The trusted host must authorize the tenant separately.
/// Holding it consumes a native work slot and metadata; it grants no blob access.
/// Page boundaries can reflect other tenants' entries, so neither the cursor
/// nor its pagination observations may be exposed to an untrusted caller.
pub struct LocalReferenceInventory {
    work: Work,
    tenant: TenantId,
    generation: u64,
    after: Option<String>,
    complete: bool,
    // The tenant and continuation retire before this reservation.
    _memory: InventoryMemory,
}

impl LocalReferenceInventory {
    pub(super) fn ensure_current(&self, store: &LocalBlobStore) -> Result<()> {
        if !Arc::ptr_eq(&self.work.inner, &store.inner) {
            return Err(LocalBlobError::PermissionDenied);
        }
        store.check_owner()?;
        let state = store.inner.state()?;
        if store.inner.publishing.load(Ordering::Acquire)
            || state.inventory_generation != self.generation
        {
            return Err(LocalBlobError::Busy);
        }
        Ok(())
    }

    pub fn begin(
        store: &LocalBlobStore,
        scope: &TenantId,
        checkpoint: &dyn Fn() -> Result<()>,
    ) -> Result<Self> {
        tenant(scope)?;
        checkpoint()?;
        store.inner.check()?;
        // A cursor and its first retained page each require a work slot. Do
        // not admit a cursor that can never make progress under this limit.
        if store.inner.limits.maximum_work < 2 {
            return Err(LocalBlobError::Capacity);
        }
        let work = store.inner.work()?;
        // Do not admit a cursor that by itself makes even a one-entry page
        // unaffordable. Headroom is checked, not charged to the cursor.
        let memory = InventoryMemory::reserve(
            &store.inner,
            HANDLE_BYTES,
            HANDLE_BYTES + OBJECT_BYTES,
        )?;
        checkpoint()?;
        let generation = {
            let state = store.inner.state()?;
            if store.inner.publishing.load(Ordering::Acquire) {
                return Err(LocalBlobError::Busy);
            }
            state.inventory_generation
        };
        checkpoint()?;
        let inventory = Self {
            work,
            tenant: scope.clone(),
            generation,
            after: None,
            complete: false,
            _memory: memory,
        };
        inventory.ensure_current(store)?;
        Ok(inventory)
    }

    /// Visit at most 64 physical entries per call, including entries for other
    /// tenants and released records. A mutation invalidates the entire cursor.
    /// Reserve the requested page's metadata before copying, even if few or no
    /// references match. Capacity refusal leaves the cursor unadvanced; retry
    /// with a smaller page or after actually dropping another retained owner.
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
        let page_bytes = maximum_entries
            .checked_mul(OBJECT_BYTES)
            .and_then(|bytes| bytes.checked_add(HANDLE_BYTES))
            .ok_or(LocalBlobError::Capacity)?;
        let page_memory = InventoryMemory::reserve(&store.inner, page_bytes, 0)?;
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
        store.check_owner()?;
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
            _memory: page_memory,
        })
    }
}

#[cfg(test)]
mod tests;
