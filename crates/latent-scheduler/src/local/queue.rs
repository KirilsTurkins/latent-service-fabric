//! Bounded intrusive tenant queues; selection policy remains in `ClassState`.

mod arena;
mod links;

use std::collections::BTreeMap;

use latent_core::TenantId;

use super::state::Entry;
#[cfg(test)]
use super::work::Work;
use arena::Arena;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) struct EntrySlot(usize);

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct TenantSlot(usize);

struct QueuedEntry {
    entry: Entry,
    tenant: TenantSlot,
    previous: Option<EntrySlot>,
    next: Option<EntrySlot>,
}

struct TenantQueue {
    first: Option<EntrySlot>,
    last: Option<EntrySlot>,
    count: usize,
    previous: Option<TenantSlot>,
    next: Option<TenantSlot>,
}

pub(super) struct Queue {
    entries: Arena<QueuedEntry>,
    tenants: Arena<TenantQueue>,
    tenant_index: BTreeMap<TenantId, TenantSlot>,
    first: Option<TenantSlot>,
    last: Option<TenantSlot>,
}

impl Queue {
    pub fn new(capacity: u32) -> Self {
        let capacity = usize::try_from(capacity).expect("queue capacity fits address space");
        Self {
            entries: Arena::new(capacity),
            tenants: Arena::new(capacity),
            tenant_index: BTreeMap::new(),
            first: None,
            last: None,
        }
    }

    pub fn tenant_count(&self) -> usize {
        self.tenant_index.len()
    }

    #[cfg(test)]
    pub fn retained_capacity(&self) -> (usize, usize) {
        (
            self.entries.retained_capacity(),
            self.tenants.retained_capacity(),
        )
    }

    pub fn push(&mut self, entry: Entry, #[cfg(test)] work: &mut Work) -> EntrySlot {
        let tenant_id = entry.request.permit.tenant();
        #[cfg(test)]
        work.lookup_tenant();
        let tenant_slot = if let Some(slot) = self.tenant_index.get(tenant_id) {
            *slot
        } else {
            let slot = TenantSlot(self.tenants.insert(TenantQueue {
                first: None,
                last: None,
                count: 0,
                previous: None,
                next: None,
            }));
            #[cfg(test)]
            work.lookup_tenant();
            self.tenant_index.insert(tenant_id.clone(), slot);
            self.append_tenant(slot);
            slot
        };
        let tenant = self.tenants.get_mut(tenant_slot.0).expect("located tenant");
        let previous = tenant.last;
        let slot = EntrySlot(self.entries.insert(QueuedEntry {
            entry,
            tenant: tenant_slot,
            previous,
            next: None,
        }));
        if let Some(previous) = previous {
            self.entries.get_mut(previous.0).expect("tenant tail").next = Some(slot);
        } else {
            tenant.first = Some(slot);
        }
        tenant.last = Some(slot);
        tenant.count += 1;
        slot
    }

    pub fn restore(&mut self, entry: Entry, #[cfg(test)] work: &mut Work) -> EntrySlot {
        let slot = self.push(
            entry,
            #[cfg(test)]
            work,
        );
        let tenant = self.entries.get(slot.0).expect("restored entry").tenant;
        self.detach_tenant(tenant);
        self.prepend_tenant(tenant);
        slot
    }

    pub fn rotate_after_grant(&mut self, tenant: &TenantId, #[cfg(test)] work: &mut Work) {
        #[cfg(test)]
        work.lookup_tenant();
        if let Some(slot) = self.tenant_index.get(tenant).copied() {
            self.detach_tenant(slot);
            self.append_tenant(slot);
        }
    }

    pub fn front_entries(&self) -> Entries<'_> {
        let tenant = self.first.and_then(|slot| self.tenants.get(slot.0));
        Entries {
            storage: &self.entries,
            next: tenant.and_then(|tenant| tenant.first),
            remaining: tenant.map_or(0, |tenant| tenant.count),
        }
    }

    pub fn remove(
        &mut self,
        slot: EntrySlot,
        sequence: u64,
        #[cfg(test)] work: &mut Work,
    ) -> Option<Entry> {
        if self.entries.get(slot.0)?.entry.sequence != sequence {
            return None;
        }
        Some(self.unlink(
            slot,
            #[cfg(test)]
            work,
        ))
    }

    pub fn unlink(&mut self, slot: EntrySlot, #[cfg(test)] work: &mut Work) -> Entry {
        let node = self.entries.remove(slot.0).expect("located queued entry");
        let tenant = self.tenants.get_mut(node.tenant.0).expect("entry tenant");
        if let Some(previous) = node.previous {
            self.entries
                .get_mut(previous.0)
                .expect("previous entry")
                .next = node.next;
        } else {
            tenant.first = node.next;
        }
        if let Some(next) = node.next {
            self.entries.get_mut(next.0).expect("next entry").previous = node.previous;
        } else {
            tenant.last = node.previous;
        }
        tenant.count -= 1;
        if tenant.count == 0 {
            self.detach_tenant(node.tenant);
            self.tenants.remove(node.tenant.0).expect("empty tenant");
            #[cfg(test)]
            work.lookup_tenant();
            let removed = self.tenant_index.remove(node.entry.request.permit.tenant());
            debug_assert_eq!(removed, Some(node.tenant));
        }
        #[cfg(test)]
        work.unlink_entries(1, 0);
        node.entry
    }

    pub fn drain_into(&mut self, output: &mut Vec<Entry>, #[cfg(test)] work: &mut Work) {
        while let Some(tenant) = self.first {
            let slot = self.tenants.get(tenant.0).expect("front tenant").first;
            output.push(self.unlink(
                slot.expect("nonempty tenant"),
                #[cfg(test)]
                work,
            ));
        }
    }
}

pub(super) struct Entries<'a> {
    storage: &'a Arena<QueuedEntry>,
    next: Option<EntrySlot>,
    remaining: usize,
}

impl<'a> Iterator for Entries<'a> {
    type Item = (EntrySlot, &'a Entry);

    fn next(&mut self) -> Option<Self::Item> {
        let slot = self.next?;
        let entry = self.storage.get(slot.0).expect("linked queued entry");
        self.next = entry.next;
        self.remaining -= 1;
        Some((slot, &entry.entry))
    }

    fn size_hint(&self) -> (usize, Option<usize>) {
        (self.remaining, Some(self.remaining))
    }
}

impl ExactSizeIterator for Entries<'_> {}
