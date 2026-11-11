//! Physical retention is installed before any state envelope may name bytes.
//! GC acquires the original publication guard before a fresh same-engine view;
//! each verified provisional pin stays alive through actual commit retirement.
use super::{
    model, record, Arc, LocalBlobError, LocalBlobLimits, LocalBlobReader, LocalBlobStore,
    LocalReferenceInventory, LocalReferencePage, Ordering, Path, Result, TenantId, RECORD_BYTES,
};
use crate::BlobReference;
use latent_state::{
    embedded::{EmbeddedStore, ReadView, RowKey, StoreBinding, StoreError},
    payload_references::{
        self, physical_owner_count, required_physical_page, LocalPayloadIdentity,
    },
    store_identity::StoreIdentity,
};
use serde::{Deserialize, Serialize};

mod required;
pub use required::RequiredBlobInventory;

#[derive(Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct ModeRecord {
    version: u8,
    store_identity: String,
    configuration_digest: String,
}
impl ModeRecord {
    pub(super) fn validate(&self) -> Result<()> {
        if self.version != 1
            || StoreIdentity::new(self.store_identity.clone()).is_err()
            || !self.configuration_digest.starts_with("sha256:")
            || !model::hex(&self.configuration_digest[7..], 64)
        {
            return Err(LocalBlobError::Corrupt);
        }
        Ok(())
    }
}

/// The actual verified native reader and its provisional publication pin.
/// This is affine; a digest, path, counter or encoded reference cannot mint it.
pub struct LocalDurablePin {
    reader: LocalBlobReader,
    configuration: [u8; 32],
    namespace: String,
    store_identity: String,
    store_binding: StoreBinding,
}

/// A descriptive observation on one retained state view. None of these values
/// proves current ownership, byte integrity, or authority to reclaim.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LocalReferenceDisposition {
    /// The retained view has neither a head nor a physical-owner index.
    Unreviewed,
    /// A zero-owner head exists and no physical-owner index was observed.
    ZeroOwners,
    /// A positive head and at least one reciprocal physical-owner row exist.
    HasOwners,
}

/// Retains the original charged reference page while its observations are used.
pub struct LocalReferenceAuditPage {
    // Retire observations before the page refunds their shared reservation.
    dispositions: Vec<LocalReferenceDisposition>,
    page: LocalReferencePage,
}
impl LocalReferenceAuditPage {
    #[must_use]
    pub fn complete(&self) -> bool {
        self.page.complete
    }
    pub fn entries(&self) -> impl Iterator<Item = (&BlobReference, LocalReferenceDisposition)> {
        self.page
            .references()
            .iter()
            .zip(self.dispositions.iter().copied())
    }
}

/// Host-internal comparison of local references to one retained state view.
/// The view can be historical even while valid; results never establish current
/// ownership. An expired view, changed local generation, error or panic
/// invalidates progress; restart with fresh owners. Pagination can reveal
/// aggregate tenant activity. The caller retains and funds the original view.
pub struct LocalReferenceAudit {
    inventory: LocalReferenceInventory,
    view: usize,
    invalid: bool,
}
impl LocalReferenceAudit {
    pub fn begin(
        store: &LocalBlobStore,
        view: &ReadView,
        scope: &TenantId,
        checkpoint: &dyn Fn() -> Result<()>,
    ) -> Result<Self> {
        // Reserve the cursor before inspecting any durable state, then reuse
        // the actual root, configuration and live-engine checks.
        let inventory = LocalReferenceInventory::begin(store, scope, checkpoint)?;
        // Reuse the binding check, not a second independently charged cursor.
        required::validate_binding(store, view)?;
        checkpoint()?;
        let _ = view.is_empty().map_err(storage)?;
        inventory.ensure_current(store)?;
        Ok(Self {
            inventory,
            view: view.identity(),
            invalid: false,
        })
    }

    pub fn next_page(
        &mut self,
        store: &LocalBlobStore,
        view: &ReadView,
        maximum_entries: usize,
        checkpoint: &dyn Fn() -> Result<()>,
    ) -> Result<LocalReferenceAuditPage> {
        if self.invalid {
            return Err(LocalBlobError::Invalid);
        }
        if self.view != view.identity() {
            self.invalid = true;
            return Err(LocalBlobError::Invalid);
        }
        // Any early return or panic makes the advanced cursor unusable.
        self.invalid = true;
        self.inventory.ensure_current(store)?;
        let _ = view.is_empty().map_err(storage)?;
        // State-index decoding/reciprocal checks are transient work, not part
        // of the retained reference page. Reserve before either allocation.
        let _scratch = super::inventory::InventoryMemory::reserve(
            &store.inner,
            4 * RECORD_BYTES,
            0,
        )?;
        let page = self
            .inventory
            .next_page(store, maximum_entries, checkpoint)?;
        let mode = store
            .inner
            .durable
            .as_ref()
            .ok_or(LocalBlobError::Invalid)?;
        let mut dispositions = Vec::with_capacity(page.references().len());
        for reference in page.references() {
            checkpoint()?;
            let physical = LocalPayloadIdentity {
                tenant: reference.tenant.0.clone(),
                provider: "local-retention-inventory".into(),
                provider_epoch: 1,
                provider_configuration: decode_digest(&mode.configuration_digest)?,
                blob_namespace: store.namespace().into(),
                digest: decode_digest(&reference.digest.0)?,
                size: reference.size_bytes,
                media_type: reference.media_type.clone(),
            };
            let required =
                required_physical_page(view, &physical, None, 1, RECORD_BYTES).map_err(storage)?;
            let count = physical_owner_count(view, &physical).map_err(storage)?;
            let disposition = match (count, required.references.is_empty()) {
                (None, true) => LocalReferenceDisposition::Unreviewed,
                (Some(0), true) => LocalReferenceDisposition::ZeroOwners,
                (Some(n), false) if n > 0 => LocalReferenceDisposition::HasOwners,
                _ => return Err(LocalBlobError::Corrupt),
            };
            dispositions.push(disposition);
        }
        checkpoint()?;
        let _ = view.is_empty().map_err(storage)?;
        self.inventory.ensure_current(store)?;
        self.invalid = false;
        Ok(LocalReferenceAuditPage { dispositions, page })
    }
}
impl LocalDurablePin {
    #[must_use]
    pub fn reference(&self) -> &BlobReference {
        self.reader.reference()
    }
    #[must_use]
    pub fn reader(&self) -> &LocalBlobReader {
        &self.reader
    }
    #[must_use]
    pub fn store_identity(&self) -> &str {
        &self.store_identity
    }
    #[must_use]
    pub fn uses_store_view(&self, view: &ReadView) -> bool {
        view.is_bound_to(&self.store_binding)
    }
    #[must_use]
    pub fn uses_store(&self, store: &EmbeddedStore) -> bool {
        store.is_bound_to(&self.store_binding)
    }
    pub(crate) fn identity(&self, provider: &str, epoch: u64) -> Result<LocalPayloadIdentity> {
        model::text(provider)?;
        if epoch == 0 {
            return Err(LocalBlobError::Invalid);
        }
        let reference = self.reference();
        Ok(LocalPayloadIdentity {
            tenant: reference.tenant.0.clone(),
            provider: provider.into(),
            provider_epoch: epoch,
            provider_configuration: self.configuration,
            blob_namespace: self.namespace.clone(),
            digest: decode_digest(&reference.digest.0)?,
            size: reference.size_bytes,
            media_type: reference.media_type.clone(),
        })
    }
}
impl LocalBlobStore {
    /// Bind an already-open, uniquely held owner to the initializing engine,
    /// but only when that root already contains the matching durable mode.
    /// An ordinary root returns `false` without creating or changing a mode.
    /// Startup must still verify all required bytes and semantic closure before
    /// publishing the owner or exposing any store consumer.
    pub fn bind_existing_durable_for_view(owner: &mut Arc<Self>, view: &ReadView) -> Result<bool> {
        let Some(mode) = owner.inner.durable.as_ref() else {
            return Ok(false);
        };
        if owner.inner.durable_binding.is_some() {
            return Err(LocalBlobError::Busy);
        }
        let identity = StoreIdentity::inspect(view)
            .map_err(storage)?
            .ok_or(LocalBlobError::Corrupt)?;
        if identity.as_str() != mode.store_identity
            || owner.configuration_digest()? != mode.configuration_digest
        {
            return Err(LocalBlobError::PermissionDenied);
        }
        let inner = Arc::get_mut(&mut Arc::get_mut(owner).ok_or(LocalBlobError::Busy)?.inner)
            .ok_or(LocalBlobError::Busy)?;
        inner.durable_binding = Some(view.binding());
        Ok(true)
    }

    /// Check one required catalogue row and its actual local immutable bytes.
    /// The caller separately validates the owner's semantic closure and scans all
    /// required rows. This observation grants no blob-read or deletion right.
    pub fn verify_required_reference(
        &self,
        view: &ReadView,
        key: &RowKey,
        bytes: &[u8],
        checkpoint: &dyn Fn() -> Result<()>,
    ) -> Result<()> {
        let mode = self.inner.durable.as_ref().ok_or(LocalBlobError::Invalid)?;
        let binding = self
            .inner
            .durable_binding
            .as_ref()
            .ok_or(LocalBlobError::PermissionDenied)?;
        if !view.is_bound_to(binding) {
            return Err(LocalBlobError::PermissionDenied);
        }
        if view
            .get_bounded(key, payload_references::MAX_REFERENCE_BYTES)
            .map_err(storage)?
            .as_deref()
            != Some(bytes)
        {
            return Err(LocalBlobError::Corrupt);
        }
        payload_references::validate_row(view, key, bytes).map_err(storage)?;
        let reference = payload_references::owner_reference(key, bytes)
            .map_err(storage)?
            .ok_or(LocalBlobError::Invalid)?;
        let identity = StoreIdentity::inspect(view)
            .map_err(storage)?
            .ok_or(LocalBlobError::Corrupt)?;
        if identity.as_str() != mode.store_identity
            || reference.payload.provider_configuration
                != decode_digest(&mode.configuration_digest)?
            || reference.payload.blob_namespace != self.namespace()
            || self.configuration_digest()? != mode.configuration_digest
        {
            return Err(LocalBlobError::PermissionDenied);
        }
        let scope = TenantId(reference.payload.tenant.clone());
        let blob = BlobReference {
            digest: latent_core::BlobDigest(format!(
                "sha256:{:x}",
                latent_core::digest::HexDigest(reference.payload.digest)
            )),
            size_bytes: reference.payload.size,
            media_type: reference.payload.media_type,
            tenant: scope.clone(),
            metadata: latent_core::Metadata::new(),
        };
        let reader = self
            .open_read(&scope, &blob, checkpoint)
            .map_err(|error| match error {
                LocalBlobError::NotFound => LocalBlobError::Corrupt,
                other => other,
            })?;
        drop(reader);
        checkpoint()?;
        let _ = view.is_empty().map_err(storage)?;
        self.check_owner()
    }

    /// Trusted setup on the fixed native storage owner. The actual selected
    /// store must already have its immutable identity. Ordinary opening later
    /// still recognizes this durable mode and cannot release without review.
    pub fn open_durable(
        root: &Path,
        namespace: &str,
        limits: LocalBlobLimits,
        store: &EmbeddedStore,
    ) -> Result<Arc<Self>> {
        let view = store.snapshot().map_err(storage)?;
        Self::open_durable_for_view(root, namespace, limits, &view)
    }
    /// Trusted startup can bind the actual initializing engine from its
    /// worker-owned view before publishing readiness.
    pub fn open_durable_for_view(
        root: &Path,
        namespace: &str,
        limits: LocalBlobLimits,
        view: &ReadView,
    ) -> Result<Arc<Self>> {
        StoreIdentity::inspect(view)
            .map_err(storage)?
            .ok_or(LocalBlobError::Invalid)?;
        let mut owner = Self::open(root, namespace, limits)?;
        Self::enable_durable_for_view(&mut owner, view)?;
        Ok(owner)
    }

    /// Opt an exclusively held local owner into durable retention for this
    /// actual engine. The trusted host must authorize this irreversible mode
    /// transition and finish semantic startup validation before publication.
    /// Existing readers, handles or another owner prevent the transition.
    pub fn enable_durable_for_view(owner: &mut Arc<Self>, view: &ReadView) -> Result<()> {
        Self::enable_durable_for_view_inner(owner, view, || {})
    }

    #[cfg(test)]
    pub(super) fn enable_durable_for_view_after_publish(
        owner: &mut Arc<Self>,
        view: &ReadView,
        after_publish: impl FnOnce(),
    ) -> Result<()> {
        Self::enable_durable_for_view_inner(owner, view, after_publish)
    }

    fn enable_durable_for_view_inner(
        owner: &mut Arc<Self>,
        view: &ReadView,
        after_publish: impl FnOnce(),
    ) -> Result<()> {
        owner.inner.check()?;
        if Arc::get_mut(owner)
            .and_then(|owner| Arc::get_mut(&mut owner.inner))
            .is_none()
            || owner.inner.durable_binding.is_some()
        {
            return Err(LocalBlobError::Busy);
        }
        let identity = StoreIdentity::inspect(view)
            .map_err(storage)?
            .ok_or(LocalBlobError::Invalid)?;
        let mode = ModeRecord {
            version: 1,
            store_identity: identity.as_str().into(),
            configuration_digest: owner.configuration_digest()?,
        };
        mode.validate()?;
        let encoded = record(&mode)?;
        let created = if let Some(existing) = &owner.inner.durable {
            if existing != &mode {
                return Err(LocalBlobError::PermissionDenied);
            }
            false
        } else {
            let _ = view.is_empty().map_err(storage)?;
            {
                let mut state = owner.inner.state()?;
                state.durable_mode = true;
                if let Err(error) = owner.inner.disk_room(&state, 0, 0) {
                    state.durable_mode = false;
                    return Err(error);
                }
            }
            owner
                .inner
                .root
                .write_new("DURABLE.json", &encoded)
                .map_err(|_| owner.inner.uncertain())?;
            owner
                .inner
                .root
                .sync()
                .map_err(|_| owner.inner.uncertain())?;
            true
        };
        let inner = Arc::get_mut(&mut Arc::get_mut(owner).ok_or(LocalBlobError::Busy)?.inner)
            .ok_or(LocalBlobError::Busy)?;
        inner.durable = Some(mode);
        inner.durable_binding = Some(view.binding());
        if created {
            after_publish();
        }
        if let Err(error) = view.is_empty() {
            return Err(if created {
                owner.inner.uncertain()
            } else {
                storage(error)
            });
        }
        Ok(())
    }
    /// Native provider work verifies length/media/digest and acquires its real
    /// reader handle before the envelope can receive a provisional pin.
    pub fn capture_durable_reference(
        &self,
        scope: &TenantId,
        reference: &BlobReference,
        checkpoint: &dyn Fn() -> Result<()>,
    ) -> Result<LocalDurablePin> {
        let mode = self.inner.durable.as_ref().ok_or(LocalBlobError::Invalid)?;
        let store_binding = self
            .inner
            .durable_binding
            .as_ref()
            .ok_or(LocalBlobError::PermissionDenied)?;
        if mode.configuration_digest != self.configuration_digest()? {
            return Err(LocalBlobError::PermissionDenied);
        }
        let mut reader = self.open_read(scope, reference, checkpoint)?;
        reader.make_durable()?;
        // The real reader and provisional pin are already owned here. Refuse
        // to hand them off if the original admission or local owner retired
        // while that pin was being acquired; dropping the reader retires both.
        checkpoint()?;
        self.inner.check()?;
        Ok(LocalDurablePin {
            reader,
            configuration: decode_digest(&self.configuration_digest()?)?,
            namespace: self.namespace().into(),
            store_identity: mode.store_identity.clone(),
            store_binding: store_binding.clone(),
        })
    }
    /// Release the physical base reference only after every independent durable
    /// owner and provisional publication retires. Existing ordinary readers may
    /// finish; their original native pins still block later physical reclaim.
    pub fn release_durable_reference(
        &self,
        scope: &TenantId,
        reference: &BlobReference,
        store: &EmbeddedStore,
        checkpoint: &dyn Fn() -> Result<()>,
    ) -> Result<bool> {
        let mode = self.inner.durable.as_ref().ok_or(LocalBlobError::Invalid)?;
        let binding = self
            .inner
            .durable_binding
            .as_ref()
            .ok_or(LocalBlobError::PermissionDenied)?;
        if !store.is_bound_to(binding) {
            return Err(LocalBlobError::PermissionDenied);
        }
        model::text(&scope.0)?;
        let _work = self.inner.work()?;
        let _publication = self.inner.publication()?;
        checkpoint()?;
        let record = super::ReferenceRecord::requested(
            self.namespace(),
            scope,
            reference,
            self.limits().maximum_object_bytes,
        )?;
        {
            let state = self.inner.state()?;
            let object = state
                .objects
                .get(&record.key())
                .ok_or(LocalBlobError::NotFound)?;
            if object.durable_pins.load(Ordering::Acquire) != 0 {
                return Err(LocalBlobError::Busy);
            }
        }
        // MUST acquire this view after the publication guard and real pending
        // count. A precomputed view could omit a just-committed durable owner.
        let view = store.snapshot().map_err(storage)?;
        let identity = StoreIdentity::inspect(&view)
            .map_err(storage)?
            .ok_or(LocalBlobError::Corrupt)?;
        if identity.as_str() != mode.store_identity
            || self.configuration_digest()? != mode.configuration_digest
        {
            return Err(LocalBlobError::PermissionDenied);
        }
        let physical = LocalPayloadIdentity {
            tenant: scope.0.clone(),
            provider: "local-retention-inventory".into(),
            provider_epoch: 1,
            provider_configuration: decode_digest(&mode.configuration_digest)?,
            blob_namespace: self.namespace().into(),
            digest: decode_digest(&reference.digest.0)?,
            size: reference.size_bytes,
            media_type: reference.media_type.clone(),
        };
        let required =
            required_physical_page(&view, &physical, None, 1, RECORD_BYTES).map_err(storage)?;
        let owners = physical_owner_count(&view, &physical)
            .map_err(storage)?
            .ok_or(LocalBlobError::Corrupt)?;
        if (owners == 0) != required.references.is_empty() {
            return Err(LocalBlobError::Corrupt);
        }
        if owners != 0 || !required.references.is_empty() {
            return Err(LocalBlobError::Busy);
        }
        // The zero-owner observation must still be live at the release fence.
        // In particular, a delayed caller cannot use an expired read view to
        // retire the physical reference after its bounded observation ended.
        self.release_reference_checked(scope, reference, &|| {
            checkpoint()?;
            let _ = view.is_empty().map_err(storage)?;
            self.inner.check()
        })
    }
}
fn decode_digest(value: &str) -> Result<[u8; 32]> {
    if !value.starts_with("sha256:") || !model::hex(&value[7..], 64) {
        return Err(LocalBlobError::Invalid);
    }
    let mut digest = [0; 32];
    for (index, byte) in digest.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&value[7 + index * 2..9 + index * 2], 16)
            .map_err(|_| LocalBlobError::Invalid)?;
    }
    Ok(digest)
}
fn storage(error: StoreError) -> LocalBlobError {
    match error {
        StoreError::Capacity => LocalBlobError::Capacity,
        StoreError::Invalid => LocalBlobError::Invalid,
        StoreError::Unavailable | StoreError::SnapshotExpired => LocalBlobError::Unavailable,
        StoreError::CommitUncertain => LocalBlobError::Uncertain,
        StoreError::Conflict => LocalBlobError::Busy,
        StoreError::Corrupt | StoreError::UnsupportedFormat => LocalBlobError::Corrupt,
    }
}
