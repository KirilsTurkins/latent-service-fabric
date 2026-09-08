use std::collections::HashMap;
use std::sync::Arc;

use latent_core::PlatformError;

use super::Entry;

/// Internal slot IDs never escape to prepared owners.
pub(super) struct Recency<T> {
    index: HashMap<Arc<str>, usize>,
    slots: Vec<Slot<T>>,
    free: Option<usize>,
    least: Option<usize>,
    most: Option<usize>,
}

enum Slot<T> {
    Vacant { next: Option<usize> },
    Occupied(Resident<T>),
}

struct Resident<T> {
    key: Arc<str>,
    entry: Entry<T>,
    previous: Option<usize>,
    next: Option<usize>,
}

impl<T> Default for Recency<T> {
    fn default() -> Self {
        Self {
            index: HashMap::new(),
            slots: Vec::new(),
            free: None,
            least: None,
            most: None,
        }
    }
}

impl<T> Recency<T> {
    pub(super) fn len(&self) -> usize {
        self.index.len()
    }

    #[cfg(test)]
    pub(super) fn allocated_slots(&self) -> usize {
        self.slots.len()
    }

    pub(super) fn get(&mut self, key: &str) -> Option<Arc<T>> {
        let slot = *self.index.get(key)?;
        let runtime = Arc::clone(&self.occupied(slot).entry.runtime);
        if self.most != Some(slot) {
            self.unlink(slot);
            self.append(slot);
        }
        Some(runtime)
    }

    pub(super) fn peek(&self, key: &str) -> Option<&Entry<T>> {
        self.index.get(key).map(|slot| &self.occupied(*slot).entry)
    }

    pub(super) fn values(&self) -> impl Iterator<Item = &Entry<T>> {
        self.slots.iter().filter_map(|slot| match slot {
            Slot::Occupied(resident) => Some(&resident.entry),
            Slot::Vacant { .. } => None,
        })
    }

    /// Perform every recoverable allocation before evicting existing entries.
    pub(super) fn reserve_publication(
        &mut self,
        maximum_entries: usize,
    ) -> Result<(), PlatformError> {
        let required = self.len().saturating_add(1).min(maximum_entries);
        if self.index.capacity() < required {
            self.index
                .try_reserve(required - self.len())
                .map_err(|_| super::capacity_error())?;
        }
        if self.free.is_none() && self.slots.len() < maximum_entries {
            self.slots
                .try_reserve(1)
                .map_err(|_| super::capacity_error())?;
        }
        Ok(())
    }

    pub(super) fn insert(&mut self, key: Arc<str>, entry: Entry<T>) {
        debug_assert!(!self.index.contains_key(key.as_ref()));
        let slot = if let Some(slot) = self.free {
            let Slot::Vacant { next } = self.slots[slot] else {
                unreachable!("free slot is vacant")
            };
            self.free = next;
            slot
        } else {
            self.slots.push(Slot::Vacant { next: None });
            self.slots.len() - 1
        };
        self.index.insert(Arc::clone(&key), slot);
        self.slots[slot] = Slot::Occupied(Resident {
            key,
            entry,
            previous: None,
            next: None,
        });
        self.append(slot);
    }

    pub(super) fn remove(&mut self, key: &str) -> Option<Entry<T>> {
        let slot = *self.index.get(key)?;
        Some(self.remove_slot(slot))
    }

    pub(super) fn remove_oldest(&mut self) -> Option<Entry<T>> {
        self.least.map(|slot| self.remove_slot(slot))
    }

    fn remove_slot(&mut self, slot: usize) -> Entry<T> {
        self.unlink(slot);
        let Slot::Occupied(resident) =
            std::mem::replace(&mut self.slots[slot], Slot::Vacant { next: self.free })
        else {
            unreachable!("only occupied slots can be removed")
        };
        self.free = Some(slot);
        self.index.remove(resident.key.as_ref());
        resident.entry
    }

    fn unlink(&mut self, slot: usize) {
        let resident = self.occupied(slot);
        let (previous, next) = (resident.previous, resident.next);
        if let Some(previous) = previous {
            self.occupied_mut(previous).next = next;
        } else {
            self.least = next;
        }
        if let Some(next) = next {
            self.occupied_mut(next).previous = previous;
        } else {
            self.most = previous;
        }
    }

    fn append(&mut self, slot: usize) {
        let previous = self.most;
        let resident = self.occupied_mut(slot);
        resident.previous = previous;
        resident.next = None;
        if let Some(previous) = previous {
            self.occupied_mut(previous).next = Some(slot);
        } else {
            self.least = Some(slot);
        }
        self.most = Some(slot);
    }

    fn occupied(&self, slot: usize) -> &Resident<T> {
        match &self.slots[slot] {
            Slot::Occupied(resident) => resident,
            Slot::Vacant { .. } => unreachable!("linked slot is occupied"),
        }
    }

    fn occupied_mut(&mut self, slot: usize) -> &mut Resident<T> {
        match &mut self.slots[slot] {
            Slot::Occupied(resident) => resident,
            Slot::Vacant { .. } => unreachable!("linked slot is occupied"),
        }
    }
}
