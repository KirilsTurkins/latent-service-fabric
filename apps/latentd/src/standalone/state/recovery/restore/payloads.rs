//! Fresh provider custody for a private restore, before application adoption.
use super::super::codecs::Codecs;
use latent_blobs::local::{LocalBlobError, LocalBlobStore, LocalBlobWriter};
use latent_core::TenantId;
use latent_state::{
    embedded::{ReadView, StoreError},
    payload_references::PayloadReference,
    recovery::snapshot::{SnapshotPayloadSink, SnapshotReceipt},
};
use std::sync::{Arc, Mutex};

#[derive(Default)]
pub(in crate::standalone::state::recovery) struct RestoredPayloads(Mutex<Option<Destination>>);

struct Destination {
    store: Arc<LocalBlobStore>,
    snapshot: [u8; 32],
    bound: bool,
}

impl RestoredPayloads {
    pub(super) fn start<'a>(
        &self,
        codecs: &'a Codecs,
        snapshot: &SnapshotReceipt,
    ) -> Result<Box<dyn SnapshotPayloadSink + 'a>, StoreError> {
        let (source, _) = codecs
            .payloads
            .as_ref()
            .ok_or(StoreError::UnsupportedFormat)?;
        let root = codecs.payload_destination()?;
        let mut staged = self.0.lock().map_err(|_| StoreError::Unavailable)?;
        if staged.is_some() {
            return Err(StoreError::Conflict);
        }
        let store = LocalBlobStore::create_restore_destination(
            &root,
            source.namespace(),
            source.limits(),
            &|| checkpoint(codecs),
        )
        .map_err(storage)?;
        let sink = PayloadWriter {
            codecs,
            store: Arc::clone(&store),
            pending: None,
        };
        *staged = Some(Destination {
            store,
            snapshot: snapshot.snapshot_digest,
            bound: false,
        });
        Ok(Box::new(sink))
    }

    pub(in crate::standalone::state::recovery) fn for_view(
        &self,
        codecs: &Codecs,
        view: &ReadView,
    ) -> Result<Option<crate::standalone::state::store::InventoryPayloads>, StoreError> {
        let mut staged = self.0.lock().map_err(|_| StoreError::Unavailable)?;
        let Some(destination) = staged.as_mut() else {
            return Ok(None);
        };
        let (_, provider) = codecs
            .payloads
            .as_ref()
            .ok_or(StoreError::UnsupportedFormat)?;
        if !destination.bound {
            codecs.fence("namespace-restore", || Ok(()))?;
            LocalBlobStore::enable_durable_for_restored_view(
                &mut destination.store,
                view,
                destination.snapshot,
            )
            .map_err(storage)?;
            destination.bound = true;
        }
        Ok(Some((Arc::clone(&destination.store), provider.clone())))
    }
}

struct PayloadWriter<'a> {
    codecs: &'a Codecs,
    store: Arc<LocalBlobStore>,
    pending: Option<(PayloadReference, LocalBlobWriter)>,
}

impl SnapshotPayloadSink for PayloadWriter<'_> {
    fn start(&mut self, reference: &PayloadReference) -> Result<(), StoreError> {
        self.codecs.check()?;
        let (_, provider) = self
            .codecs
            .payloads
            .as_ref()
            .ok_or(StoreError::UnsupportedFormat)?;
        let payload = &reference.payload;
        if self.pending.is_some()
            || payload.tenant != provider.tenant
            || payload.provider != provider.id
            || payload.provider_epoch != provider.epoch
            || payload.blob_namespace != self.store.namespace()
            || reference.owner.namespace != self.codecs.namespace.id.0
            || reference.owner.incarnation != self.codecs.namespace.version.incarnation
        {
            return Err(StoreError::Conflict);
        }
        let writer = self
            .store
            .create(
                &TenantId(payload.tenant.clone()),
                &payload.media_type,
                Some(payload.size),
                &|| checkpoint(self.codecs),
            )
            .map_err(storage)?;
        self.pending = Some((reference.clone(), writer));
        Ok(())
    }

    fn write(&mut self, chunk: &[u8]) -> Result<(), StoreError> {
        let (_, writer) = self.pending.as_mut().ok_or(StoreError::Corrupt)?;
        for chunk in chunk.chunks(self.store.limits().maximum_chunk_bytes) {
            writer
                .write(writer.written(), chunk, &|| checkpoint(self.codecs))
                .map_err(storage)?;
        }
        Ok(())
    }

    fn seal(&mut self) -> Result<(), StoreError> {
        let (reference, writer) = self.pending.take().ok_or(StoreError::Corrupt)?;
        self.codecs.fence("namespace-restore", || Ok(()))?;
        let blob = writer.seal(&|| checkpoint(self.codecs)).map_err(storage)?;
        let digest = format!(
            "sha256:{:x}",
            latent_core::digest::HexDigest(reference.payload.digest)
        );
        if blob.digest.0 != digest
            || blob.size_bytes != reference.payload.size
            || blob.media_type != reference.payload.media_type
            || blob.tenant.0 != reference.payload.tenant
        {
            return Err(StoreError::Corrupt);
        }
        Ok(())
    }
}

fn checkpoint(codecs: &Codecs) -> Result<(), LocalBlobError> {
    codecs.check().map_err(|_| LocalBlobError::Cancelled)
}

fn storage(error: LocalBlobError) -> StoreError {
    match error {
        LocalBlobError::Corrupt | LocalBlobError::NotFound | LocalBlobError::Invalid => {
            StoreError::Corrupt
        }
        LocalBlobError::PermissionDenied | LocalBlobError::Busy => StoreError::Conflict,
        LocalBlobError::Capacity => StoreError::Capacity,
        LocalBlobError::Cancelled | LocalBlobError::DeadlineExceeded => StoreError::SnapshotExpired,
        _ => StoreError::Unavailable,
    }
}
