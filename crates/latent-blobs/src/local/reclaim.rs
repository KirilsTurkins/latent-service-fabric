use super::{
    fs, recovery, tenant, Arc, LocalBlobError, LocalBlobStore, Ordering, ReferenceRecord, Result,
    TenantId,
};
use crate::BlobReference;

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct LocalBlobReclamation {
    pub objects: usize,
    pub stages: usize,
    pub released_payload_reservations: u64,
}
impl LocalBlobStore {
    /// Privileged retention operation, not a guest handle destructor. Once the
    /// tombstone is durable no new read may open this reference; existing pins
    /// may finish and prevent physical reclamation until their actual Drop.
    pub fn release_reference(
        &self,
        scope: &TenantId,
        reference: &BlobReference,
        checkpoint: &dyn Fn() -> Result<()>,
    ) -> Result<bool> {
        tenant(scope)?;
        let _work = self.inner.work()?;
        let _publication = self.inner.publication()?;
        checkpoint()?;
        let record = ReferenceRecord::requested(
            &self.inner.namespace,
            scope,
            reference,
            self.inner.limits.maximum_object_bytes,
        )?;
        let key = record.key();
        {
            let mut state = self.inner.state()?;
            let object = state.objects.get(&key).ok_or(LocalBlobError::NotFound)?;
            if !object.referenced.swap(false, Ordering::AcqRel) {
                return Ok(false);
            }
            state.referenced -= 1;
        }
        let result = (|| {
            let directory = self.inner.objects.child(&key, false)?;
            directory.write_new("RELEASED", b"LSF blob reference released v1\n")?;
            directory.sync()
        })();
        result.map_err(|_| self.inner.uncertain())?;
        Ok(true)
    }
    /// At most 64 entries per explicit maintenance turn. No recursive deletion,
    /// active-stage removal, reader eviction, automatic retry or Drop-time I/O.
    pub fn reclaim(
        &self,
        maximum_entries: usize,
        checkpoint: &dyn Fn() -> Result<()>,
    ) -> Result<LocalBlobReclamation> {
        if maximum_entries == 0 || maximum_entries > 64 {
            return Err(LocalBlobError::Invalid);
        }
        let _work = self.inner.work()?;
        self.reclaim_selected(maximum_entries, true, checkpoint)
    }

    // The caller already owns a bounded physical work slot. Admission pressure
    // may retire one abandoned stage, never an object or an active writer.
    pub(super) fn reclaim_retired_stage(
        &self,
        checkpoint: &dyn Fn() -> Result<()>,
    ) -> Result<LocalBlobReclamation> {
        self.reclaim_selected(1, false, checkpoint)
    }

    fn reclaim_selected(
        &self,
        maximum_entries: usize,
        include_objects: bool,
        checkpoint: &dyn Fn() -> Result<()>,
    ) -> Result<LocalBlobReclamation> {
        let _publication = self.inner.publication()?;
        checkpoint()?;
        let (objects, stages) = {
            let state = self.inner.state()?;
            let objects = state
                .objects
                .iter()
                .filter(|(_, o)| {
                    include_objects
                        && !o.referenced.load(Ordering::Acquire)
                        && o.pins.load(Ordering::Acquire) == 0
                })
                .take(maximum_entries)
                .map(|(key, _)| key.clone())
                .collect::<Vec<_>>();
            let stages = state
                .stages
                .iter()
                .filter(|(_, s)| !s.active.load(Ordering::Acquire))
                .take(maximum_entries - objects.len())
                .map(|(id, _)| *id)
                .collect::<Vec<_>>();
            (objects, stages)
        };
        let mut result = LocalBlobReclamation::default();
        for key in objects {
            checkpoint()?;
            remove(
                &self.inner.objects,
                &key,
                true,
                self.inner.limits.maximum_object_bytes,
            )
            .map_err(|_| self.inner.uncertain())?;
            let mut state = self.inner.committed_state()?;
            let object = state
                .objects
                .remove(&key)
                .ok_or_else(|| self.inner.uncertain())?;
            state.resident -= object.bytes;
            result.objects += 1;
            result.released_payload_reservations += object.bytes;
        }
        for id in stages {
            checkpoint()?;
            remove(
                &self.inner.staging,
                &format!("{id:016x}"),
                false,
                self.inner.limits.maximum_object_bytes,
            )
            .map_err(|_| self.inner.uncertain())?;
            let mut state = self.inner.committed_state()?;
            let reservation = state
                .stages
                .remove(&id)
                .ok_or_else(|| self.inner.uncertain())?;
            state.reserved -= reservation.maximum;
            result.stages += 1;
            result.released_payload_reservations += reservation.maximum;
        }
        Ok(result)
    }
}
fn remove(parent: &Arc<fs::Directory>, name: &str, object: bool, maximum: u64) -> Result<()> {
    if !parent.present(name)? {
        return parent.sync();
    }
    let directory = parent.child(name, false)?;
    let names = recovery::inventory(&directory, object, maximum)?;
    if object && !names.is_empty() && !names.iter().any(|n| n == "RELEASED") {
        return Err(LocalBlobError::Corrupt);
    }
    // Retain the durable tombstone until every payload/record has gone. An empty
    // directory after the last unlink is still an unreferenced owned entry.
    for file in ["data", "REFERENCE.json", "STAGE.json", "RELEASED"] {
        if names.iter().any(|n| n == file) {
            if file == "RELEASED" {
                directory.sync()?;
            }
            directory.unlink(file, false)?;
        }
    }
    parent.unlink(name, true)?;
    drop(directory);
    parent.sync()
}
