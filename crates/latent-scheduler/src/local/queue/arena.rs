//! Lazy bounded slots: vacant nodes contain only a free-list link.

enum Slot<T> {
    Occupied(T),
    Vacant { next: Option<usize> },
}

pub(super) struct Arena<T> {
    slots: Vec<Slot<T>>,
    free: Option<usize>,
    live: usize,
    bound: usize,
}

impl<T> Arena<T> {
    pub fn new(bound: usize) -> Self {
        Self {
            slots: Vec::new(),
            free: None,
            live: 0,
            bound,
        }
    }

    pub fn insert(&mut self, value: T) -> usize {
        assert!(self.live < self.bound, "bounded queue slot reservation");
        let index = if let Some(index) = self.free {
            let Slot::Vacant { next } = &self.slots[index] else {
                unreachable!("free-list node is vacant");
            };
            self.free = *next;
            self.slots[index] = Slot::Occupied(value);
            index
        } else {
            if self.slots.len() == self.slots.capacity() {
                let target = self.slots.len().saturating_mul(2).max(1).min(self.bound);
                self.slots.reserve_exact(target - self.slots.len());
            }
            let index = self.slots.len();
            self.slots.push(Slot::Occupied(value));
            index
        };
        self.live += 1;
        index
    }

    pub fn get(&self, index: usize) -> Option<&T> {
        match self.slots.get(index)? {
            Slot::Occupied(value) => Some(value),
            Slot::Vacant { .. } => None,
        }
    }

    #[cfg(test)]
    pub fn retained_capacity(&self) -> usize {
        self.slots.capacity()
    }

    pub fn get_mut(&mut self, index: usize) -> Option<&mut T> {
        match self.slots.get_mut(index)? {
            Slot::Occupied(value) => Some(value),
            Slot::Vacant { .. } => None,
        }
    }

    pub fn remove(&mut self, index: usize) -> Option<T> {
        let slot = self.slots.get_mut(index)?;
        if matches!(slot, Slot::Vacant { .. }) {
            return None;
        }
        let Slot::Occupied(value) = std::mem::replace(slot, Slot::Vacant { next: self.free })
        else {
            unreachable!("checked occupied slot");
        };
        self.free = Some(index);
        self.live -= 1;
        Some(value)
    }
}

#[cfg(test)]
mod tests {
    use super::Arena;

    #[test]
    fn non_power_of_two_bound_reuses_vacant_slots_without_churn_growth() {
        let mut arena = Arena::new(7);
        assert_eq!(arena.slots.capacity(), 0);
        let slots: Vec<_> = (0..7).map(|value| arena.insert(value)).collect();
        assert_eq!(arena.slots.len(), 7);
        assert!(arena.slots.capacity() <= 7);
        for expected in 0..100 {
            for index in [3, 0, 6, 1, 5, 2, 4] {
                assert!(arena.remove(slots[index]).is_some());
                assert_eq!(arena.remove(slots[index]), None);
            }
            assert_eq!(arena.live, 0);
            for _ in 0..7 {
                let slot = arena.insert(expected);
                assert_eq!(arena.get(slot), Some(&expected));
            }
            assert_eq!(arena.slots.len(), 7);
            assert!(arena.slots.capacity() <= 7);
        }
    }
}
