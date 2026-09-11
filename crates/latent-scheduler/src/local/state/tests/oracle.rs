//! Independent frozen `VecDeque`/`Vec` policy, with no candidate slot/index access.
use std::cmp::Ordering;
use std::collections::VecDeque;
use std::time::{Duration, Instant};

#[derive(Clone, Debug)]
pub(super) struct Key {
    pub sequence: u64,
    pub tenant: u32,
    pub priority: u8,
    pub enqueued: Instant,
    pub deadline: Option<Instant>,
}

#[derive(Default)]
pub(super) struct Oracle(VecDeque<(u32, Vec<Key>)>);
impl Oracle {
    pub fn push(&mut self, key: Key) {
        if let Some((_, rows)) = self.0.iter_mut().find(|(tenant, _)| *tenant == key.tenant) {
            rows.push(key);
        } else {
            self.0.push_back((key.tenant, vec![key]));
        }
    }
    pub fn select(&mut self, now: Instant, aging: Duration) -> Option<Key> {
        let (_, rows) = self.0.front_mut()?;
        let index = rows
            .iter()
            .enumerate()
            .min_by(|(_, a), (_, b)| compare(a, b, now, aging))
            .unwrap()
            .0;
        let selected = rows.remove(index);
        if rows.is_empty() {
            self.0.pop_front();
        }
        Some(selected)
    }
    pub fn rotate(&mut self, tenant: u32) {
        if let Some(index) = self.0.iter().position(|(id, _)| *id == tenant) {
            let row = self.0.remove(index).unwrap();
            self.0.push_back(row);
        }
    }
    pub fn restore(&mut self, key: Key) {
        let tenant = key.tenant;
        self.push(key);
        let index = self.0.iter().position(|(id, _)| *id == tenant).unwrap();
        let row = self.0.remove(index).unwrap();
        self.0.push_front(row);
    }
    pub fn remove(&mut self, sequence: u64) -> Option<Key> {
        let (tenant, index) = self.0.iter().enumerate().find_map(|(tenant, (_, rows))| {
            rows.iter()
                .position(|row| row.sequence == sequence)
                .map(|index| (tenant, index))
        })?;
        let row = self.0[tenant].1.remove(index);
        if self.0[tenant].1.is_empty() {
            self.0.remove(tenant);
        }
        Some(row)
    }
    pub fn len(&self) -> usize {
        self.0.iter().map(|(_, rows)| rows.len()).sum()
    }
    pub fn tenants(&self) -> usize {
        self.0.len()
    }
}

fn compare(a: &Key, b: &Key, now: Instant, aging: Duration) -> Ordering {
    match (
        now.saturating_duration_since(a.enqueued) >= aging,
        now.saturating_duration_since(b.enqueued) >= aging,
    ) {
        (true, true) => a.sequence.cmp(&b.sequence),
        (true, false) => Ordering::Less,
        (false, true) => Ordering::Greater,
        (false, false) => b
            .priority
            .cmp(&a.priority)
            .then_with(|| match (a.deadline, b.deadline) {
                (Some(a), Some(b)) => a.cmp(&b),
                (Some(_), None) => Ordering::Less,
                (None, Some(_)) => Ordering::Greater,
                (None, None) => Ordering::Equal,
            })
            .then_with(|| a.sequence.cmp(&b.sequence)),
    }
}
