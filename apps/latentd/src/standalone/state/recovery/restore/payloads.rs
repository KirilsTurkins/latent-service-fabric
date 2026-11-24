//! Fresh provider custody for a private restore, before application adoption.
use super::super::codecs::Codecs;
use latent_blobs::{
    local::{LocalBlobError, LocalBlobReader, LocalBlobStore, LocalBlobWriter},
    BlobReference,
};
use latent_core::{BlobDigest, TenantId};
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
    pending: Option<PayloadFrame>,
}

enum PayloadFrame {
    Existing(LocalBlobReader),
    New(BlobReference, LocalBlobWriter),
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
        let expected = BlobReference {
            digest: BlobDigest(format!(
                "sha256:{:x}",
                latent_core::digest::HexDigest(payload.digest)
            )),
            tenant: TenantId(payload.tenant.clone()),
            size_bytes: payload.size,
            media_type: payload.media_type.clone(),
            metadata: Default::default(),
        };
        let current = || checkpoint(self.codecs);
        self.pending = Some(
            match self.store.open_read(&expected.tenant, &expected, &current) {
                Ok(reader) => PayloadFrame::Existing(reader),
                Err(LocalBlobError::NotFound) => {
                    let writer = self
                        .store
                        .create(
                            &expected.tenant,
                            &expected.media_type,
                            Some(expected.size_bytes),
                            &current,
                        )
                        .map_err(storage)?;
                    PayloadFrame::New(expected, writer)
                }
                Err(error) => return Err(storage(error)),
            },
        );
        Ok(())
    }

    fn write(&mut self, chunk: &[u8]) -> Result<(), StoreError> {
        // The archive reader hashes every frame, including repeated owners of
        // a previously sealed physical object.
        match self.pending.as_mut().ok_or(StoreError::Corrupt)? {
            PayloadFrame::Existing(_) => self.codecs.check()?,
            PayloadFrame::New(_, writer) => {
                for chunk in chunk.chunks(self.store.limits().maximum_chunk_bytes) {
                    writer
                        .write(writer.written(), chunk, &|| checkpoint(self.codecs))
                        .map_err(storage)?;
                }
            }
        }
        Ok(())
    }

    fn seal(&mut self) -> Result<(), StoreError> {
        let pending = self.pending.take().ok_or(StoreError::Corrupt)?;
        self.codecs.fence("namespace-restore", || Ok(()))?;
        match pending {
            PayloadFrame::Existing(reader) => drop(reader),
            PayloadFrame::New(expected, writer) => {
                let actual = writer.seal(&|| checkpoint(self.codecs)).map_err(storage)?;
                if actual != expected {
                    return Err(StoreError::Corrupt);
                }
            }
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
