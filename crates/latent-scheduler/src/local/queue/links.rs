use super::{Queue, TenantSlot};

impl Queue {
    pub(super) fn detach_tenant(&mut self, slot: TenantSlot) {
        let tenant = self.tenants.get_mut(slot.0).expect("linked tenant");
        let previous = tenant.previous.take();
        let next = tenant.next.take();
        if let Some(previous) = previous {
            self.tenants
                .get_mut(previous.0)
                .expect("previous tenant")
                .next = next;
        } else {
            self.first = next;
        }
        if let Some(next) = next {
            self.tenants.get_mut(next.0).expect("next tenant").previous = previous;
        } else {
            self.last = previous;
        }
    }

    pub(super) fn append_tenant(&mut self, slot: TenantSlot) {
        let tenant = self.tenants.get_mut(slot.0).expect("detached tenant");
        tenant.previous = self.last;
        tenant.next = None;
        if let Some(last) = self.last {
            self.tenants.get_mut(last.0).expect("last tenant").next = Some(slot);
        } else {
            self.first = Some(slot);
        }
        self.last = Some(slot);
    }

    pub(super) fn prepend_tenant(&mut self, slot: TenantSlot) {
        let tenant = self.tenants.get_mut(slot.0).expect("detached tenant");
        tenant.previous = None;
        tenant.next = self.first;
        if let Some(first) = self.first {
            self.tenants
                .get_mut(first.0)
                .expect("first tenant")
                .previous = Some(slot);
        } else {
            self.last = Some(slot);
        }
        self.first = Some(slot);
    }
}
