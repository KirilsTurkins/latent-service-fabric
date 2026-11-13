//! Original-owner, generation-fenced recovery with prepaid bounded scratch.
use super::{storage, LocalBlobError, LocalBlobStore, ReadView, Result, StoreIdentity};
use crate::local::{
    inventory::InventoryMemory, Arc, Ordering, Work, HANDLE_BYTES, OBJECT_BYTES, RECORD_BYTES,
};
use latent_state::payload_references::{self, MAX_REFERENCE_BYTES, MAX_REFERENCE_UPDATES};

// Covers the cursor, original-owner guards and its bounded primary-row key.
const CURSOR_BYTES: usize = HANDLE_BYTES;
// One-at-a-time decode/encode/reciprocal lookups and local verification scratch.
const SCRATCH_BYTES: usize = 4 * RECORD_BYTES;

fn page_bytes(rows: usize, bytes: usize) -> Result<usize> {
    if rows == 0
        || rows > MAX_REFERENCE_UPDATES
        || bytes == 0
        || bytes > MAX_REFERENCE_UPDATES * MAX_REFERENCE_BYTES
    {
        return Err(LocalBlobError::Capacity);
    }
    // Raw scan bytes and decoded references may coexist. The per-row bound
    // includes vector slots, owned strings, keys and allocator growth slack.
    bytes
        .checked_mul(2)
        .and_then(|n| n.checked_add(rows.checked_mul(2 * OBJECT_BYTES)?))
        .and_then(|n| n.checked_add(SCRATCH_BYTES))
        .ok_or(LocalBlobError::Capacity)
}

pub(super) fn validate_binding(store: &LocalBlobStore, view: &ReadView) -> Result<()> {
    store.check_owner()?;
    let mode = store
        .inner
        .durable
        .as_ref()
        .ok_or(LocalBlobError::Invalid)?;
    let binding = store
        .inner
        .durable_binding
        .as_ref()
        .ok_or(LocalBlobError::PermissionDenied)?;
    if !view.is_bound_to(binding) {
        return Err(LocalBlobError::PermissionDenied);
    }
    let identity = StoreIdentity::inspect(view)
        .map_err(storage)?
        .ok_or(LocalBlobError::Corrupt)?;
    if identity.as_str() != mode.store_identity
        || store.configuration_digest()? != mode.configuration_digest
    {
        return Err(LocalBlobError::PermissionDenied);
    }
    Ok(())
}

/// A single-view physical recovery walk on its original local generation.
/// The cursor retains a native work slot and metadata until actual destruction;
/// each synchronous page prepays its raw rows, decoded references and scratch.
/// A failed, panicking, rebound or locally mutated observation is terminal.
/// Restart with a fresh cursor and admission; completion grants no deletion
/// authority and does not replace the host's semantic-closure/startup fence.
pub struct RequiredBlobInventory {
    work: Work,
    view: usize,
    generation: u64,
    after: Option<Vec<u8>>,
    complete: bool,
    invalid: bool,
    // The continuation must retire before its original metadata reservation.
    _memory: InventoryMemory,
}
impl RequiredBlobInventory {
    pub fn begin(store: &LocalBlobStore, view: &ReadView) -> Result<Self> {
        Self::begin_with_checkpoint(store, view, &|| Ok(()))
    }

    /// Admit the cursor before inspecting state and honor the original caller's
    /// cancellation/deadline at both admission boundaries. No worker is spawned.
    pub fn begin_with_checkpoint(
        store: &LocalBlobStore,
        view: &ReadView,
        checkpoint: &dyn Fn() -> Result<()>,
    ) -> Result<Self> {
        checkpoint()?;
        // One slot belongs to the cursor; open_read uses another while it
        // verifies each actual file. A one-slot cursor could never progress.
        if store.inner.limits.maximum_work < 2 {
            return Err(LocalBlobError::Capacity);
        }
        let work = store.inner.work()?;
        let headroom = page_bytes(1, MAX_REFERENCE_BYTES)?
            .checked_add(HANDLE_BYTES)
            .ok_or(LocalBlobError::Capacity)?;
        let memory = InventoryMemory::reserve(&store.inner, CURSOR_BYTES, headroom)?;
        validate_binding(store, view)?;
        let generation = {
            let state = store.inner.state()?;
            if store.inner.publishing.load(Ordering::Acquire) {
                return Err(LocalBlobError::Busy);
            }
            state.inventory_generation
        };
        let inventory = Self {
            work,
            view: view.identity(),
            generation,
            after: None,
            complete: false,
            invalid: false,
            _memory: memory,
        };
        checkpoint()?;
        let _ = view.is_empty().map_err(storage)?;
        inventory.ensure_current(store, view)?;
        Ok(inventory)
    }

    fn ensure_current(&self, store: &LocalBlobStore, view: &ReadView) -> Result<()> {
        if self.view != view.identity() || !Arc::ptr_eq(&self.work.inner, &store.inner) {
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

    /// Inspect a bounded page on the original shared blocking owner. Transient
    /// allocations remain charged through verification and the final checkpoint.
    /// On any failure, including capacity refusal, this cursor cannot resume.
    pub fn next_page(
        &mut self,
        store: &LocalBlobStore,
        view: &ReadView,
        maximum_rows: usize,
        maximum_bytes: usize,
        checkpoint: &dyn Fn() -> Result<()>,
    ) -> Result<(usize, bool)> {
        if self.invalid || self.complete {
            return Err(LocalBlobError::PermissionDenied);
        }
        self.invalid = true;
        checkpoint()?;
        self.ensure_current(store, view)?;
        let bytes = page_bytes(maximum_rows, maximum_bytes)?;
        // The cursor already holds the orchestration slot. Only the native
        // reader takes another slot; do not require an artificial third one.
        // Headroom is checked, not charged; the reader has its own real charge.
        let _memory = InventoryMemory::reserve(&store.inner, bytes, HANDLE_BYTES)?;
        let page = payload_references::required_owner_page(
            view,
            self.after.as_deref(),
            maximum_rows,
            maximum_bytes,
        )
        .map_err(storage)?;
        for reference in &page.references {
            checkpoint()?;
            self.ensure_current(store, view)?;
            let key = reference.owner_key().map_err(storage)?;
            let encoded = reference.encode().map_err(storage)?;
            store.verify_required_reference(view, &key, &encoded, checkpoint)?;
        }
        checkpoint()?;
        let _ = view.is_empty().map_err(storage)?;
        self.ensure_current(store, view)?;
        let count = page.references.len();
        self.after = page.resume;
        self.complete = self.after.is_none();
        self.invalid = false;
        Ok((count, self.complete))
    }
}

#[cfg(test)]
mod tests;
