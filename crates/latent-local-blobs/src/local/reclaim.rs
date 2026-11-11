use super::{
    fs, recovery, tenant, Arc, LocalBlobError, LocalBlobStore, Ordering, ReferenceRecord, Result,
    TenantId,
};
use crate::BlobReference;
use std::{
    collections::BTreeMap,
    ops::Bound::{Excluded, Unbounded},
};

// A turn visits a fixed number of physical records, including records which
// are still live. A cursor is only a scheduling hint, never deletion proof.
fn select<K: Ord + Clone, V>(
    entries: &BTreeMap<K, V>,
    after: Option<&K>,
    visits: usize,
    maximum: usize,
    eligible: impl Fn(&V) -> bool,
) -> (Vec<K>, Option<K>) {
    let mut selected = Vec::new();
    let mut last = after.cloned();
    let mut visited = 0;
    for (key, value) in entries
        .range((after.map_or(Unbounded, Excluded), Unbounded))
        .take(visits)
    {
        visited += 1;
        last = Some(key.clone());
        if eligible(value) {
            selected.push(key.clone());
            if selected.len() == maximum {
                break;
            }
        }
    }
    if visited < visits && selected.len() < maximum {
        last = None;
    }
    (selected, last)
}

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
        if self.inner.durable.is_some() {
            return Err(LocalBlobError::Busy);
        }
        self.release_reference_checked(scope, reference, checkpoint)
    }
    pub(super) fn release_reference_checked(
        &self,
        scope: &TenantId,
        reference: &BlobReference,
        checkpoint: &dyn Fn() -> Result<()>,
    ) -> Result<bool> {
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
            let object = state
                .objects
                .get(&key)
                .cloned()
                .ok_or(LocalBlobError::NotFound)?;
            if !object.referenced.load(Ordering::Acquire) {
                return Ok(false);
            }
            state.advance_inventory()?;
            object.referenced.store(false, Ordering::Release);
            state.referenced -= 1;
        }
        let result = (|| {
            let directory = self.inner.objects.child(&key, false)?;
            directory.write_new("RELEASED", recovery::RELEASE_MARKER)?;
            directory.sync()
        })();
        result.map_err(|_| self.inner.uncertain())?;
        Ok(true)
    }
    /// Visit at most 64 physical entries per explicit maintenance turn. A turn
    /// may reclaim nothing even when later entries are eligible; repeated turns
    /// resume and eventually wrap. No recursive deletion, active-stage removal,
    /// reader eviction, automatic retry or Drop-time I/O.
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
            let mut state = self.inner.state()?;
            let mut objects = Vec::new();
            let mut stages = Vec::new();
            let stages_first = !include_objects || state.reclaim_stages_first;
            if include_objects {
                state.reclaim_stages_first = !state.reclaim_stages_first;
            }
            for scan_stages in [stages_first, !stages_first] {
                let remaining = maximum_entries - objects.len() - stages.len();
                if remaining == 0 {
                    break;
                }
                if scan_stages {
                    let (found, after) = select(
                        &state.stages,
                        state.reclaim_stage_after.as_ref(),
                        if include_objects { 32 } else { 64 },
                        remaining,
                        |stage| !stage.active.load(Ordering::Acquire),
                    );
                    state.reclaim_stage_after = after;
                    stages = found;
                } else if include_objects {
                    let (found, after) = select(
                        &state.objects,
                        state.reclaim_object_after.as_ref(),
                        32,
                        remaining,
                        |object| {
                            !object.referenced.load(Ordering::Acquire)
                                && object.pins.load(Ordering::Acquire) == 0
                        },
                    );
                    state.reclaim_object_after = after;
                    objects = found;
                }
            }
            (objects, stages)
        };
        let mut result = LocalBlobReclamation::default();
        for key in objects {
            checkpoint()?;
            // A failed physical retirement still invalidates an observation.
            self.inner.state()?.advance_inventory()?;
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

#[cfg(test)]
mod tests {
    use super::select;
    use std::{cell::Cell, collections::BTreeMap};

    #[test]
    fn selection_counts_live_entries_and_resumes_without_starvation() {
        let entries: BTreeMap<_, _> = (0..100).map(|n| (n, n == 95)).collect();
        let mut after = None;
        for turn in 0..4 {
            let seen = Cell::new(0);
            let (selected, next) = select(&entries, after.as_ref(), 32, 1, |eligible| {
                seen.set(seen.get() + 1);
                *eligible
            });
            assert!(seen.get() <= 32);
            if turn < 2 {
                assert!(selected.is_empty());
            } else if turn == 2 {
                assert_eq!(selected, vec![95]);
            } else {
                assert!(selected.is_empty());
                assert_eq!(next, None);
            }
            after = next;
        }
    }
}
