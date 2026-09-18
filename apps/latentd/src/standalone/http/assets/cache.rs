use latent_artifacts::{package::artifact_blob_digest, web::WebAsset};
use latent_core::ArtifactBlobDigest;
use std::{
    collections::VecDeque,
    sync::{
        atomic::{AtomicU64, AtomicUsize, Ordering},
        Arc, Mutex,
    },
};
use tokio::sync::{OwnedSemaphorePermit, Semaphore};

pub(super) const MAX_BYTES: usize = 32 * 1024 * 1024;
const MAX_ENTRIES: usize = 128;
const ENTRY_CHARGE: usize = 512;

pub(super) struct Buffer {
    pub bytes: Vec<u8>,
    // Drop data before returning its reservation. Cache eviction cannot release
    // bytes still pinned by an output owner, including a canceled socket writer.
    _charge: OwnedSemaphorePermit,
}
pub(super) struct Cache {
    entries: Mutex<VecDeque<(ArtifactBlobDigest, Arc<Buffer>)>>,
    memory: Arc<Semaphore>,
    maximum_bytes: usize,
    pub entries_count: AtomicUsize,
    pub hits: AtomicU64,
    pub misses: AtomicU64,
    pub corruptions: AtomicU64,
}
impl Cache {
    pub(super) fn new(maximum_bytes: usize) -> Self {
        Self {
            entries: Mutex::new(VecDeque::new()),
            memory: Arc::new(Semaphore::new(maximum_bytes)),
            maximum_bytes,
            entries_count: AtomicUsize::new(0),
            hits: AtomicU64::new(0),
            misses: AtomicU64::new(0),
            corruptions: AtomicU64::new(0),
        }
    }
    pub(super) fn retained_bytes(&self) -> usize {
        self.maximum_bytes - self.memory.available_permits()
    }
    pub(super) fn clear(&self) {
        self.entries
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clear();
        self.entries_count.store(0, Ordering::Release);
    }
    pub(super) fn read(
        &self,
        asset: &WebAsset,
        read: impl FnOnce(&ArtifactBlobDigest, &mut [u8]) -> Result<(), u16>,
    ) -> Result<Arc<Buffer>, u16> {
        let digest: ArtifactBlobDigest = asset.digest.parse().map_err(|_| 502u16)?;
        let size = usize::try_from(asset.size).map_err(|_| 502u16)?;
        if asset.size > latent_artifacts::web::MAX_WEB_ASSET_BYTES {
            return Err(502);
        }
        let cached = {
            let mut entries = self.entries.try_lock().map_err(|_| 503u16)?;
            entries
                .iter()
                .position(|(key, _)| key == &digest)
                .map(|index| {
                    let entry = entries.remove(index).expect("located cache entry");
                    let buffer = Arc::clone(&entry.1);
                    entries.push_back(entry);
                    buffer
                })
        };
        if let Some(buffer) = cached {
            if valid(&buffer.bytes, &digest, size) {
                self.hits.fetch_add(1, Ordering::Relaxed);
                return Ok(buffer);
            }
            self.corruptions.fetch_add(1, Ordering::Relaxed);
            let mut entries = self.entries.try_lock().map_err(|_| 503u16)?;
            entries.retain(|(_, value)| !Arc::ptr_eq(value, &buffer));
            self.entries_count.store(entries.len(), Ordering::Release);
            // The old bytes, including any concurrent reader pins, stay charged.
        }
        self.misses.fetch_add(1, Ordering::Relaxed);
        let charge = size.checked_add(ENTRY_CHARGE).ok_or(503u16)?;
        let permit = self.reserve(charge)?;
        let mut bytes = Vec::new();
        bytes.try_reserve_exact(size).map_err(|_| 503u16)?;
        bytes.resize(size, 0);
        read(&digest, &mut bytes)?;
        if !valid(&bytes, &digest, size) {
            self.corruptions.fetch_add(1, Ordering::Relaxed);
            return Err(502);
        }
        let buffer = Arc::new(Buffer {
            bytes,
            _charge: permit,
        });
        // A miss remains usable if another request currently owns bookkeeping.
        // Cache residency is optional and never changes publication permission.
        if let Ok(mut entries) = self.entries.try_lock() {
            if !entries.iter().any(|(key, _)| key == &digest) {
                if entries.len() == MAX_ENTRIES {
                    entries.pop_front();
                }
                entries.push_back((digest, Arc::clone(&buffer)));
                self.entries_count.store(entries.len(), Ordering::Release);
            }
        }
        Ok(buffer)
    }
    fn reserve(&self, bytes: usize) -> Result<OwnedSemaphorePermit, u16> {
        if bytes > self.maximum_bytes {
            return Err(503);
        }
        let bytes = u32::try_from(bytes).map_err(|_| 503u16)?;
        if let Ok(permit) = Arc::clone(&self.memory).try_acquire_many_owned(bytes) {
            return Ok(permit);
        }
        // Bounded LRU eviction: never pretend pinned buffers have been freed.
        let mut entries = self.entries.try_lock().map_err(|_| 503u16)?;
        for _ in 0..MAX_ENTRIES {
            if let Some(index) = entries
                .iter()
                .position(|(_, value)| Arc::strong_count(value) == 1)
            {
                entries.remove(index);
                self.entries_count.store(entries.len(), Ordering::Release);
            } else {
                break;
            }
            if let Ok(permit) = Arc::clone(&self.memory).try_acquire_many_owned(bytes) {
                return Ok(permit);
            }
        }
        Err(503)
    }
}
fn valid(bytes: &[u8], digest: &ArtifactBlobDigest, size: usize) -> bool {
    bytes.len() == size && &artifact_blob_digest(bytes) == digest
}

#[cfg(test)]
mod tests {
    use super::*;
    fn asset(bytes: &[u8]) -> WebAsset {
        WebAsset {
            path: "/a.js".into(),
            layer: "public/a.js".into(),
            digest: artifact_blob_digest(bytes).to_string(),
            size: bytes.len() as u64,
            media_type: "text/javascript".into(),
        }
    }
    #[test]
    fn eviction_and_clear_do_not_release_pinned_output_bytes() {
        let cache = Cache::new(ENTRY_CHARGE + 3);
        let first = cache
            .read(&asset(b"one"), |_, out| {
                out.copy_from_slice(b"one");
                Ok(())
            })
            .unwrap();
        assert_eq!(cache.retained_bytes(), ENTRY_CHARGE + 3);
        assert!(cache
            .read(&asset(b"two"), |_, _| panic!("must reserve before read"))
            .is_err());
        cache.clear();
        assert_eq!(cache.retained_bytes(), ENTRY_CHARGE + 3);
        drop(first);
        assert_eq!(cache.retained_bytes(), 0);
        let next = cache
            .read(&asset(b"two"), |_, out| {
                out.copy_from_slice(b"two");
                Ok(())
            })
            .unwrap();
        assert_eq!(next.bytes, b"two");
    }
    #[test]
    fn corruption_refetches_once_and_bad_source_never_becomes_a_cache_hit() {
        let cache = Cache::new(4096);
        let descriptor = asset(b"abc");
        drop(
            cache
                .read(&descriptor, |_, out| {
                    out.copy_from_slice(b"abc");
                    Ok(())
                })
                .unwrap(),
        );
        assert!(cache
            .read(&descriptor, |_, _| panic!("verified hit"))
            .is_ok());
        {
            let mut entries = cache.entries.lock().unwrap();
            Arc::get_mut(&mut entries[0].1).unwrap().bytes[0] = b'x';
        }
        let repaired = cache
            .read(&descriptor, |_, out| {
                out.copy_from_slice(b"abc");
                Ok(())
            })
            .unwrap();
        assert_eq!(repaired.bytes, b"abc");
        assert_eq!(cache.corruptions.load(Ordering::Relaxed), 1);
        drop(repaired);
        cache.clear();
        assert!(cache
            .read(&descriptor, |_, out| {
                out.copy_from_slice(b"bad");
                Ok(())
            })
            .is_err());
        assert_eq!(cache.entries_count.load(Ordering::Relaxed), 0);
        assert_eq!(cache.retained_bytes(), 0);
    }
    #[test]
    fn zero_length_assets_are_verified_and_oversized_declarations_do_not_read() {
        let cache = Cache::new(4096);
        assert!(cache
            .read(&asset(b""), |_, out| {
                assert!(out.is_empty());
                Ok(())
            })
            .is_ok());
        let mut huge = asset(b"a");
        huge.size = latent_artifacts::web::MAX_WEB_ASSET_BYTES + 1;
        assert!(cache.read(&huge, |_, _| panic!("oversized read")).is_err());
    }
}
