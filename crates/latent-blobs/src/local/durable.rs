//! Physical retention is installed before any state envelope may name bytes.
//! GC acquires the original publication guard before a fresh same-engine view;
//! each verified provisional pin stays alive through actual commit retirement.
use super::{
    model, record, Arc, LocalBlobError, LocalBlobLimits, LocalBlobReader, LocalBlobStore, Ordering,
    Path, Result, TenantId, RECORD_BYTES,
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

/// A single-view physical recovery walk. The held original local-store owner
/// and opaque cursor cannot be rebound to another root or engine snapshot.
pub struct RequiredBlobInventory {
    owner: Arc<super::Inner>,
    view: usize,
    after: Option<Vec<u8>>,
    complete: bool,
}
impl RequiredBlobInventory {
    pub fn begin(store: &LocalBlobStore, view: &ReadView) -> Result<Self> {
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
        Ok(Self {
            owner: Arc::clone(&store.inner),
            view: view.identity(),
            after: None,
            complete: false,
        })
    }
    /// Inspect at most `maximum_rows` owners on the original bounded worker.
    /// The host must hold its startup fence and validate semantic closure.
    pub fn next_page(
        &mut self,
        store: &LocalBlobStore,
        view: &ReadView,
        maximum_rows: usize,
        maximum_bytes: usize,
        checkpoint: &dyn Fn() -> Result<()>,
    ) -> Result<(usize, bool)> {
        if self.complete || self.view != view.identity() || !Arc::ptr_eq(&self.owner, &store.inner)
        {
            return Err(LocalBlobError::PermissionDenied);
        }
        let page = payload_references::required_owner_page(
            view,
            self.after.as_deref(),
            maximum_rows,
            maximum_bytes,
        )
        .map_err(storage)?;
        for reference in &page.references {
            checkpoint()?;
            let key = reference.owner_key().map_err(storage)?;
            let bytes = reference.encode().map_err(storage)?;
            store.verify_required_reference(view, &key, &bytes, checkpoint)?;
        }
        let count = page.references.len();
        self.after = page.resume;
        self.complete = self.after.is_none();
        Ok((count, self.complete))
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
        checkpoint()
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
        let identity = StoreIdentity::inspect(&store.snapshot().map_err(storage)?)
            .map_err(storage)?
            .ok_or(LocalBlobError::Invalid)?;
        let mut owner = Self::open(root, namespace, limits)?;
        let mode = ModeRecord {
            version: 1,
            store_identity: identity.as_str().into(),
            configuration_digest: owner.configuration_digest()?,
        };
        mode.validate()?;
        if let Some(existing) = &owner.inner.durable {
            if existing != &mode {
                return Err(LocalBlobError::PermissionDenied);
            }
        } else {
            {
                let mut state = owner.inner.state()?;
                state.durable_mode = true;
                owner.inner.disk_room(&state, 0, 0)?;
            }
            owner
                .inner
                .root
                .write_new("DURABLE.json", &record(&mode)?)?;
            owner
                .inner
                .root
                .sync()
                .map_err(|_| owner.inner.uncertain())?;
        }
        let inner = Arc::get_mut(&mut Arc::get_mut(&mut owner).ok_or(LocalBlobError::Busy)?.inner)
            .ok_or(LocalBlobError::Busy)?;
        inner.durable = Some(mode);
        inner.durable_binding = Some(store.binding());
        Ok(owner)
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
        self.release_reference_checked(scope, reference, checkpoint)
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
