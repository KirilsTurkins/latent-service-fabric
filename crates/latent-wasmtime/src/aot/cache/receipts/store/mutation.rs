use super::{key, name, Pending, ReceiptCache, Work};
use crate::aot::cache::receipts::{
    capacity, corrupt, invalid, io, pressure, uncertain, ReceiptReclamation, Result, BASE_METADATA,
    ENTRY_METADATA,
};
use latent_core::ArtifactBlobDigest;

impl ReceiptCache {
    pub(crate) fn publish(&self, digest: &ArtifactBlobDigest, receipt: &[u8]) -> Result<()> {
        if receipt.is_empty() {
            return Err(invalid());
        }
        if receipt.len() > self.limits.maximum_receipt_bytes
            || self.limits.maximum_metadata_bytes < BASE_METADATA + ENTRY_METADATA
            || self.limits.maximum_recovery_entries < 3
            || receipt.len() as u64
                > self
                    .limits
                    .maximum_disk_bytes
                    .saturating_sub(io::MARKER.len() as u64)
        {
            return Err(capacity());
        }
        let mut work = self.work()?;
        let key = key(digest);
        let additional = usize::from(!work.state.entries.contains_key(&key));
        let entries = work.state.entries.len() + additional;
        if work.state.pending.is_some()
            || entries > self.limits.maximum_entries
            || work.state.entries.len() + 3 > self.limits.maximum_recovery_entries
            || BASE_METADATA + entries * ENTRY_METADATA > self.limits.maximum_metadata_bytes
            || receipt.len() as u64
                > self
                    .limits
                    .maximum_disk_bytes
                    .saturating_sub(work.state.resident)
        {
            let mut statistics = self.statistics();
            statistics.pressure_rejections = statistics.pressure_rejections.saturating_add(1);
            return Err(pressure());
        }
        if io::size(&self.root, io::STAGE)?.is_some() {
            return Err(corrupt());
        }
        let final_name = name(&key);
        let present = io::size(&self.root, &final_name)?;
        let old = work.state.entries.get(&key);
        if present.is_some() && old.is_none() {
            return Err(corrupt());
        }
        work.state.pending = Some(Pending {
            key,
            size: receipt.len() as u64,
            renamed: false,
        });
        work.synchronize();
        io::write(&self.root, io::STAGE, receipt)?;
        io::rename(&self.root, io::STAGE, &final_name)?;
        work.state.pending.as_mut().expect("reserved stage").renamed = true;
        work.synchronize();
        io::sync(&self.root).map_err(|_| uncertain())?;
        work.state.insert(key, receipt.len() as u64);
        work.state.pending = None;
        let mut statistics = self.statistics();
        statistics.publications = statistics.publications.saturating_add(1);
        Ok(())
    }

    pub(crate) fn invalidate(&self, digest: &ArtifactBlobDigest) -> Result<bool> {
        let mut work = self.work()?;
        let key = key(digest);
        if work.state.pending.is_some_and(|pending| pending.key == key) {
            return Err(uncertain());
        }
        work.remove(&key)
    }

    pub(crate) fn reclaim(&self, maximum_entries: usize) -> Result<ReceiptReclamation> {
        if !(1..=16).contains(&maximum_entries) {
            return Err(invalid());
        }
        let mut work = self.work()?;
        let mut result = ReceiptReclamation::default();
        let pending_key = work.state.pending.map(|pending| pending.key);
        if work.state.pending.is_some() {
            work.settle()?;
            result.staging_reclaimed = true;
        }
        // Keep the just-confirmed publication. Bound selection by the existing
        // ordered recency index, without walking the entire receipt collection.
        for _ in 0..maximum_entries {
            let next = work
                .state
                .recency
                .iter()
                .take(2)
                .find(|(_, _, key)| Some(*key) != pending_key)
                .copied();
            let Some((_, _, key)) = next else { break };
            let size = work.state.entries.get(&key).expect("recency row").size;
            if work.remove(&key)? {
                result.removed_entries += 1;
                result.reclaimed_bytes += size;
            }
        }
        Ok(result)
    }
}

impl Work<'_> {
    fn remove(&mut self, key: &super::Key) -> Result<bool> {
        if !self.state.entries.contains_key(key) {
            return Ok(false);
        }
        self.state.invalidate(key);
        self.synchronize();
        io::remove(&self.cache.root, &name(key))?;
        io::sync(&self.cache.root).map_err(|_| uncertain())?;
        self.state.remove(key);
        let mut statistics = self.cache.statistics();
        statistics.evictions = statistics.evictions.saturating_add(1);
        Ok(true)
    }

    fn settle(&mut self) -> Result<()> {
        let pending = self.state.pending.expect("known reconciliation");
        if pending.renamed {
            let size = io::size(&self.cache.root, &name(&pending.key))?;
            if size.is_some_and(|size| size != pending.size) {
                return Err(corrupt());
            }
            io::sync(&self.cache.root).map_err(|_| uncertain())?;
            if size.is_some() {
                self.state.insert(pending.key, pending.size);
            } else {
                self.state.remove(&pending.key);
            }
        } else {
            // Even absence is synced before refunding a failed create/write.
            let size = io::size(&self.cache.root, io::STAGE)?;
            if size.is_some_and(|size| size > pending.size) {
                return Err(corrupt());
            }
            io::remove(&self.cache.root, io::STAGE)?;
            io::sync(&self.cache.root).map_err(|_| uncertain())?;
        }
        self.state.pending = None;
        self.synchronize();
        Ok(())
    }
}
