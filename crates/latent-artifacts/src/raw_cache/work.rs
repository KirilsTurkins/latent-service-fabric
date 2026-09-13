use super::{
    capacity, corrupt, error, io,
    ownership::{self, WorkPermit},
    Entry, Pending, RawArtifactCache, RawArtifactEviction, RawArtifactKey, RawArtifactPin,
    RawArtifactReclamation, Result, ENTRY_METADATA, HANDLE_METADATA,
};
use latent_core::PlatformErrorCode;
use std::ops::Bound::{Excluded, Unbounded};
use std::sync::Arc;

/// Affine fill reservation. Dropping an unstarted fill performs no I/O.
pub struct RawArtifactWrite {
    work: WorkPermit,
    key: RawArtifactKey,
    maximum: u64,
    incarnation: u64,
    active: bool,
}

impl RawArtifactWrite {
    /// Synchronous atomic publication of borrowed, externally owned input bytes.
    /// Move both this reservation and input ownership into the blocking job.
    pub fn publish(mut self, bytes: &[u8]) -> Result<RawArtifactPin> {
        if bytes.len() as u64 > self.maximum {
            return Err(capacity());
        }
        io::verify_bytes(&self.key, bytes)?;
        {
            let mut state = self
                .work
                .owner
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            let pending = state
                .pending
                .get_mut(&self.key)
                .ok_or_else(|| corrupt("raw-cache-reservation-missing"))?;
            if pending.incarnation != self.incarnation {
                return Err(corrupt("raw-cache-reservation-changed"));
            }
            pending.touched = true;
        }
        io::publish(&self.work.owner.root, &self.key, bytes)?;
        let mut state = self
            .work
            .owner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let pending = state
            .pending
            .remove(&self.key)
            .expect("reserved pending entry");
        state.reserved -= pending.maximum;
        let entry = Entry {
            size: bytes.len() as u64,
            incarnation: self.incarnation,
            recency: self.incarnation,
            pins: 1,
            valid: true,
            deleting: false,
        };
        let pin = ownership::pin(&self.work.owner, &self.key, &entry);
        state.resident += entry.size;
        state.pinned_bytes += entry.size;
        state.recency.insert((entry.recency, self.key.clone()));
        state.entries.insert(self.key.clone(), entry);
        self.active = false;
        Ok(pin)
    }
}
impl Drop for RawArtifactWrite {
    fn drop(&mut self) {
        if !self.active {
            return;
        }
        let mut state = self
            .work
            .owner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let touched = state
            .pending
            .get(&self.key)
            .is_some_and(|pending| pending.touched);
        if touched {
            if let Some(pending) = state.pending.get_mut(&self.key) {
                pending.active = false;
            }
            state.deletion_pending += self.maximum;
        } else if let Some(pending) = state.pending.remove(&self.key) {
            state.reserved -= pending.maximum;
        }
        state.pins -= 1;
    }
}

/// Reserved reclamation work. Admission is bookkeeping-only; `run` performs I/O.
pub struct RawArtifactReclaim {
    work: WorkPermit,
    maximum: usize,
}
impl RawArtifactReclaim {
    /// Reclaims at most the reserved number of examined entries, first orphaned
    /// owned staging, then deterministic LRU entries. Never deletes pinned files.
    pub fn run(self) -> Result<RawArtifactReclamation> {
        let mut result = RawArtifactReclamation::default();
        while result.examined < self.maximum {
            let pending = {
                let state = self.work.owner.state()?;
                state
                    .pending
                    .iter()
                    .find(|(_, value)| !value.active)
                    .map(|(key, value)| (key.clone(), value.maximum, value.incarnation))
            };
            let Some((key, maximum, incarnation)) = pending else {
                break;
            };
            result.examined += 1;
            self.pending(&key, maximum, incarnation)?;
            result.removed += 1;
            result.reclaimed_bytes += maximum;
        }
        let mut cursor = None;
        while result.examined < self.maximum {
            let next = {
                let state = self.work.owner.state()?;
                state
                    .recency
                    .range((cursor.as_ref().map_or(Unbounded, Excluded), Unbounded))
                    .next()
                    .map(|value| {
                        (
                            value.clone(),
                            state
                                .entries
                                .get(&value.1)
                                .expect("recency belongs to an entry")
                                .incarnation,
                        )
                    })
            };
            let Some(next) = next else {
                break;
            };
            cursor = Some(next.0.clone());
            result.examined += 1;
            match self.entry(&next.0 .1, Some((next.0 .0, next.1)))? {
                (RawArtifactEviction::Removed, size) => {
                    result.removed += 1;
                    result.reclaimed_bytes += size;
                }
                (RawArtifactEviction::Pinned, _) => result.pinned += 1,
                (RawArtifactEviction::Absent, _) => (),
            }
        }
        Ok(result)
    }

    fn pending(&self, key: &RawArtifactKey, maximum: u64, incarnation: u64) -> Result<()> {
        // Claim the pending incarnation; another reclaim never races its files.
        {
            let mut state = self.work.owner.state()?;
            let pending = state.pending.get_mut(key).ok_or_else(super::busy)?;
            if pending.active || pending.incarnation != incarnation {
                return Err(super::busy());
            }
            pending.active = true;
        }
        let outcome = io::remove(
            &self.work.owner.root.join("staging").join(key.name()),
            key,
            maximum,
        )
        .and_then(|()| {
            io::remove(
                &self.work.owner.root.join("objects").join(key.name()),
                key,
                maximum,
            )
        });
        let mut state = self
            .work
            .owner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if outcome.is_ok() {
            state.pending.remove(key);
            state.reserved -= maximum;
            state.deletion_pending -= maximum;
        } else if let Some(pending) = state.pending.get_mut(key) {
            pending.active = false;
        }
        outcome
    }

    pub(super) fn entry(
        &self,
        key: &RawArtifactKey,
        expected: Option<(u64, u64)>,
    ) -> Result<(RawArtifactEviction, u64)> {
        let (incarnation, size) = {
            let mut state = self.work.owner.state()?;
            let Some(entry) = state.entries.get_mut(key) else {
                return Ok((RawArtifactEviction::Absent, 0));
            };
            if expected.is_some_and(|value| value != (entry.recency, entry.incarnation)) {
                return Ok((RawArtifactEviction::Absent, 0));
            }
            if entry.pins != 0 || entry.deleting {
                return Ok((RawArtifactEviction::Pinned, 0));
            }
            let newly_invalid = entry.valid;
            entry.deleting = true;
            entry.valid = false;
            let selected = (entry.incarnation, entry.size);
            if newly_invalid {
                state.deletion_pending += selected.1;
            }
            selected
        };
        let outcome = io::remove(
            &self.work.owner.root.join("objects").join(key.name()),
            key,
            self.work.owner.limits.maximum_object_bytes,
        );
        let mut state = self
            .work
            .owner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let entry = state
            .entries
            .get(key)
            .expect("deletion retains index entry");
        if entry.incarnation != incarnation {
            return Err(corrupt("raw-cache-deletion-incarnation"));
        }
        if outcome.is_ok() {
            let entry = state.entries.remove(key).expect("checked entry");
            state.recency.remove(&(entry.recency, key.clone()));
            state.resident -= size;
            state.deletion_pending -= size;
            state.evictions = state.evictions.saturating_add(1);
        } else {
            state.entries.get_mut(key).expect("checked entry").deleting = false;
        }
        outcome.map(|()| (RawArtifactEviction::Removed, size))
    }
}

impl RawArtifactCache {
    /// Reserves before network or blocking work. Capacity pressure does not run
    /// implicit eviction; reserve a reclaim job, run it, then retry once.
    pub fn reserve_write(
        self: &Arc<Self>,
        key: RawArtifactKey,
        maximum_bytes: u64,
    ) -> Result<RawArtifactWrite> {
        let key = key.compact();
        if maximum_bytes > self.limits.maximum_object_bytes
            || maximum_bytes > self.limits.maximum_staging_bytes
            || maximum_bytes > self.limits.maximum_disk_bytes
        {
            return Err(capacity());
        }
        let work = WorkPermit::reserve(self)?;
        let mut state = self.state()?;
        if let Some(entry) = state.entries.get(&key) {
            return Err(if entry.valid && !entry.deleting {
                error(
                    PlatformErrorCode::AlreadyExists,
                    "raw-cache-already-present",
                )
            } else if !entry.deleting && entry.pins == 0 {
                error(
                    PlatformErrorCode::ResourceExhausted,
                    "raw-cache-reclaimable-pressure",
                )
            } else {
                super::busy()
            });
        }
        if state.pending.contains_key(&key) {
            return Err(super::busy());
        }
        if state.pending.len() == self.limits.maximum_staging_entries
            || state.pins == self.limits.maximum_pins
            || state
                .reserved
                .checked_add(maximum_bytes)
                .is_none_or(|bytes| bytes > self.limits.maximum_staging_bytes)
        {
            return Err(capacity());
        }
        let pressure = state.entries.len() + state.pending.len() >= self.limits.maximum_entries
            || state
                .resident
                .checked_add(state.reserved)
                .and_then(|bytes| bytes.checked_add(maximum_bytes))
                .is_none_or(|bytes| bytes > self.limits.maximum_disk_bytes)
            || self
                .metadata_room(&state, ENTRY_METADATA + HANDLE_METADATA)
                .is_err();
        if pressure {
            state.pressure = state.pressure.saturating_add(1);
            return Err(error(
                PlatformErrorCode::ResourceExhausted,
                "raw-cache-reclaimable-pressure",
            ));
        }
        let incarnation = state.next()?;
        state.reserved += maximum_bytes;
        state.pins += 1; // Reserve the future returned pin before filesystem work.
        state.pending.insert(
            key.clone(),
            Pending {
                maximum: maximum_bytes,
                incarnation,
                active: true,
                touched: false,
            },
        );
        drop(state);
        Ok(RawArtifactWrite {
            work,
            key,
            maximum: maximum_bytes,
            incarnation,
            active: true,
        })
    }

    /// Pure bookkeeping admission for one bounded reclamation job.
    pub fn reserve_reclaim(self: &Arc<Self>, maximum_entries: usize) -> Result<RawArtifactReclaim> {
        if maximum_entries == 0 || maximum_entries > self.limits.maximum_recovery_entries {
            return Err(super::invalid("raw-cache-reclaim-limit"));
        }
        Ok(RawArtifactReclaim {
            work: WorkPermit::reserve(self)?,
            maximum: maximum_entries,
        })
    }

    /// Convenience synchronous I/O operation; call only on a blocking owner.
    pub fn reclaim(self: &Arc<Self>, maximum_entries: usize) -> Result<RawArtifactReclamation> {
        self.reserve_reclaim(maximum_entries)?.run()
    }

    /// Convenience synchronous I/O operation; no filesystem work if pinned.
    pub fn evict(self: &Arc<Self>, key: &RawArtifactKey) -> Result<RawArtifactEviction> {
        self.reserve_reclaim(1)?
            .entry(key, None)
            .map(|value| value.0)
    }
}
