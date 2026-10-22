//! Store-local ordered indices whose selected backing uses the original owner.
//!
//! The legacy path keeps the upstream B-tree. Accounted stores use a sorted
//! vector: every exact replacement can be admitted before any registry edge is
//! inserted. Queries retain ordered/range semantics without allocating.

use super::registry::RegisteredModuleId;
use crate::prelude::*;
use crate::runtime::native_memory::{Memory, NativeVec};
use core::ops::{Bound, Range, RangeBounds};
use wasmtime_environ::collections::btree_map::Entry;
use wasmtime_environ::{EntityRef, StaticModuleIndex};

// Amortize registry insertion work. Spare capacity is part of the admitted
// physical allocation and remains charged until replacement or destruction.
fn growth_capacity(required: usize) -> usize {
    required.checked_next_power_of_two().unwrap_or(required)
}

pub(super) enum RegistryMap<K: Copy, V> {
    Legacy(TryBTreeMap<K, V>),
    Accounted(NativeVec<(K, V)>),
}

pub(super) enum RegistryIndices {
    Legacy(TrySecondaryMap<StaticModuleIndex, Option<RegisteredModuleId>>),
    Accounted(NativeVec<Option<RegisteredModuleId>>),
}

impl Default for RegistryIndices {
    fn default() -> Self {
        Self::Legacy(TrySecondaryMap::new())
    }
}

impl RegistryIndices {
    pub(super) fn new(memory: Memory) -> Result<Self> {
        Ok(match memory {
            None => Self::default(),
            Some(memory) => Self::Accounted(NativeVec::with_capacity(0, Some(memory))?),
        })
    }

    pub(super) fn get(&self, key: StaticModuleIndex) -> Option<&Option<RegisteredModuleId>> {
        match self {
            Self::Legacy(values) => values.get(key),
            Self::Accounted(values) => values.get(key.index()),
        }
    }

    pub(super) fn prepare_index(
        &self,
        key: StaticModuleIndex,
    ) -> Result<Option<NativeVec<Option<RegisteredModuleId>>>> {
        match self {
            Self::Legacy(_) => Ok(None),
            Self::Accounted(values) => {
                let required = key
                    .index()
                    .checked_add(1)
                    .ok_or_else(|| OutOfMemory::new(usize::MAX))?;
                values.prepare_capacity(growth_capacity(required))
            }
        }
    }

    pub(super) fn commit_capacity(
        &mut self,
        replacement: Option<NativeVec<Option<RegisteredModuleId>>>,
    ) {
        match self {
            Self::Legacy(_) => assert!(replacement.is_none()),
            Self::Accounted(values) => values.commit_capacity(replacement),
        }
    }

    pub(super) fn insert_prepared(
        &mut self,
        key: StaticModuleIndex,
        value: Option<RegisteredModuleId>,
    ) -> Result<Option<Option<RegisteredModuleId>>> {
        match self {
            Self::Legacy(values) => Ok(values.insert(key, value)?),
            Self::Accounted(values) => {
                let index = key.index();
                if let Some(previous) = values.get_mut(index) {
                    return Ok(Some(core::mem::replace(previous, value)));
                }
                // Only Option<RegisteredModuleId> is used: filling holes
                // cannot allocate or invoke tenant/user code.
                while values.len() <= index {
                    values.insert_reserved(values.len(), None);
                }
                values[index] = value;
                Ok(None)
            }
        }
    }
}

impl<K: Copy, V> Default for RegistryMap<K, V> {
    fn default() -> Self {
        Self::Legacy(TryBTreeMap::new())
    }
}

fn bounds<K: Copy + Ord, V>(values: &[(K, V)], range: &impl RangeBounds<K>) -> Range<usize> {
    let start = match range.start_bound() {
        Bound::Included(key) => values.partition_point(|(current, _)| current < key),
        Bound::Excluded(key) => values.partition_point(|(current, _)| current <= key),
        Bound::Unbounded => 0,
    };
    let end = match range.end_bound() {
        Bound::Included(key) => values.partition_point(|(current, _)| current <= key),
        Bound::Excluded(key) => values.partition_point(|(current, _)| current < key),
        Bound::Unbounded => values.len(),
    };
    start..end
}

fn pair<K: Copy, V>((key, value): &(K, V)) -> (K, &V) {
    (*key, value)
}

fn pair_mut<K: Copy, V>((key, value): &mut (K, V)) -> (K, &mut V) {
    (*key, value)
}

impl<K: Copy + Ord, V> RegistryMap<K, V> {
    pub(super) fn new(memory: Memory) -> Result<Self> {
        Ok(match memory {
            None => Self::default(),
            Some(memory) => Self::Accounted(NativeVec::with_capacity(0, Some(memory))?),
        })
    }

    pub(super) fn get(&self, key: K) -> Option<&V> {
        match self {
            Self::Legacy(values) => values.get(key),
            Self::Accounted(values) => values
                .binary_search_by_key(&key, |(key, _)| *key)
                .ok()
                .map(|index| &values[index].1),
        }
    }

    pub(super) fn get_mut(&mut self, key: K) -> Option<&mut V> {
        match self {
            Self::Legacy(values) => values.get_mut(key),
            Self::Accounted(values) => values
                .binary_search_by_key(&key, |(key, _)| *key)
                .ok()
                .map(|index| &mut values[index].1),
        }
    }

    pub(super) fn contains_key(&self, key: K) -> bool {
        self.get(key).is_some()
    }

    pub(super) fn prepare_insert(&self, key: K) -> Result<Option<NativeVec<(K, V)>>> {
        match self {
            Self::Accounted(values) if !self.contains_key(key) => {
                let required = values
                    .len()
                    .checked_add(1)
                    .ok_or_else(|| OutOfMemory::new(usize::MAX))?;
                values.prepare_capacity(growth_capacity(required))
            }
            _ => Ok(None),
        }
    }

    pub(super) fn commit_capacity(&mut self, replacement: Option<NativeVec<(K, V)>>) {
        match self {
            Self::Legacy(_) => assert!(replacement.is_none()),
            Self::Accounted(values) => values.commit_capacity(replacement),
        }
    }

    pub(super) fn insert_prepared(&mut self, key: K, value: V) -> Result<Option<V>> {
        match self {
            Self::Legacy(values) => Ok(values.insert(key, value)?),
            Self::Accounted(values) => match values.binary_search_by_key(&key, |(key, _)| *key) {
                Ok(index) => Ok(Some(core::mem::replace(&mut values[index].1, value))),
                Err(index) => {
                    values.insert_reserved(index, (key, value));
                    Ok(None)
                }
            },
        }
    }

    // The unchanged registration path may use the upstream Entry only when
    // no original-memory factory is installed. Accounted callers cannot
    // obtain an allocating container or a fallible insertion after staging.
    pub(super) fn legacy_entry(&mut self, key: K) -> Entry<'_, K, V> {
        match self {
            Self::Legacy(values) => values.entry(key),
            Self::Accounted(_) => panic!("accounted registry requires prepared insertion"),
        }
    }

    pub(super) fn range(
        &self,
        range: impl RangeBounds<K>,
    ) -> impl DoubleEndedIterator<Item = (K, &V)> {
        let (legacy, accounted) = match self {
            Self::Legacy(values) => (Some(values.range(range)), None),
            Self::Accounted(values) => (None, Some(values[bounds(values, &range)].iter())),
        };
        legacy
            .into_iter()
            .flatten()
            .chain(accounted.into_iter().flatten().map(pair))
    }

    pub(super) fn range_mut(
        &mut self,
        range: impl RangeBounds<K>,
    ) -> impl Iterator<Item = (K, &mut V)> {
        let (legacy, accounted) = match self {
            Self::Legacy(values) => (Some(values.range_mut(range)), None),
            Self::Accounted(values) => {
                let selected = bounds(values, &range);
                (None, Some(values[selected].iter_mut()))
            }
        };
        legacy
            .into_iter()
            .flatten()
            .chain(accounted.into_iter().flatten().map(pair_mut))
    }

    pub(super) fn iter(&self) -> impl Iterator<Item = (K, &V)> {
        self.range(..)
    }

    pub(super) fn values(&self) -> impl Iterator<Item = &V> {
        self.iter().map(|(_, value)| value)
    }
}
