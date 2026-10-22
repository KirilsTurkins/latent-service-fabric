//! Affine ownership for selected invocation-created engine backing buffers.
//!
//! These wrappers expose element mutation, never the allocating container.
//! Accounted replacement admits the exact new layout while the old allocation
//! remains owned. Legacy callers retain the original fallible containers.

use crate::prelude::*;
use crate::{NativeAllocation, NativeMemory};
use alloc::sync::Arc;
use core::alloc::Layout;
use core::fmt;
use core::ops::{Deref, DerefMut, Index, IndexMut};
use core::ptr::NonNull;
use wasmtime_environ::EntityRef;

pub(crate) type Memory = Option<Arc<dyn NativeMemory>>;
type Owner = Option<Box<dyn NativeAllocation>>;

pub(crate) enum MemorySource {
    None,
    External(Arc<dyn NativeMemory>),
    Owned(crate::NativeMemoryBinding),
}

impl MemorySource {
    pub(crate) fn memory(&self) -> Memory {
        match self {
            Self::None => None,
            Self::External(memory) => Some(memory.clone()),
            Self::Owned(binding) => Some(binding.memory()),
        }
    }
}

pub(crate) fn reserve(memory: &Memory, bytes: usize) -> Result<Owner> {
    match memory {
        Some(memory) if bytes != 0 => Ok(Some(memory.reserve(bytes)?)),
        _ => Ok(None),
    }
}

fn exact_vec<T>(capacity: usize, memory: &Memory) -> Result<(TryVec<T>, Owner)> {
    let layout = Layout::array::<T>(capacity).map_err(|_| OutOfMemory::new(usize::MAX))?;
    let mut allocation = reserve(memory, layout.size())?;
    let values = if layout.size() == 0 {
        // A ZST Vec has no backing allocation even when its logical capacity
        // is nonzero. Never call the global allocator with a zero-size Layout.
        Vec::new()
    } else {
        // SAFETY: the checked nonzero Layout describes exactly capacity Ts.
        let ptr = unsafe { alloc::alloc::alloc(layout) };
        let ptr = NonNull::new(ptr.cast::<T>()).ok_or_else(|| OutOfMemory::new(layout.size()))?;
        // SAFETY: no elements are initialized yet. Vec owns this allocation
        // with the identical global allocator, alignment and capacity.
        unsafe { Vec::from_raw_parts(ptr.as_ptr(), 0, capacity) }
    };
    if let Some(allocation) = allocation.as_mut() {
        allocation.allocated();
    }
    Ok((values.into(), allocation))
}

pub(crate) struct NativeVec<T> {
    // Drop the actual buffer (and its elements) before releasing its owner.
    values: TryVec<T>,
    allocation: Owner,
    memory: Memory,
}

impl<T> Default for NativeVec<T> {
    fn default() -> Self {
        Self {
            values: TryVec::new(),
            allocation: None,
            memory: None,
        }
    }
}

impl<T: fmt::Debug> fmt::Debug for NativeVec<T> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.values.fmt(f)
    }
}

impl<T> NativeVec<T> {
    pub(crate) fn with_capacity(capacity: usize, memory: Memory) -> Result<Self> {
        let (values, allocation) = if memory.is_some() {
            exact_vec(capacity, &memory)?
        } else {
            (TryVec::with_capacity(capacity)?, None)
        };
        Ok(Self {
            values,
            allocation,
            memory,
        })
    }

    pub(crate) fn reserve(&mut self, additional: usize) -> Result<()> {
        if self.memory.is_none() {
            return Ok(self.values.reserve(additional)?);
        }
        let required = self
            .values
            .len()
            .checked_add(additional)
            .ok_or_else(|| OutOfMemory::new(usize::MAX))?;
        if required <= self.values.capacity() {
            return Ok(());
        }
        let mut replacement = Self::with_capacity(required, self.memory.clone())?;
        let old = NativeVecIntoIter {
            values: core::mem::take(&mut self.values).into_iter(),
            _allocation: self.allocation.take(),
            _memory: self.memory.clone(),
        };
        for value in old {
            replacement
                .values
                .push(value)
                .expect("exact replacement capacity was admitted");
        }
        *self = replacement;
        Ok(())
    }

    pub(crate) fn push(&mut self, value: T) -> Result<()> {
        self.reserve(1)?;
        self.values
            .push(value)
            .expect("capacity was admitted above");
        Ok(())
    }

    /// Stage an empty replacement without changing any current element or owner.
    pub(crate) fn prepare_capacity(&self, required: usize) -> Result<Option<Self>> {
        if self.memory.is_none() || required <= self.values.capacity() {
            return Ok(None);
        }
        Self::with_capacity(required, self.memory.clone()).map(Some)
    }

    /// Commit a previously admitted empty replacement, without allocating.
    pub(crate) fn commit_capacity(&mut self, replacement: Option<Self>) {
        let Some(replacement) = replacement else {
            return;
        };
        assert!(replacement.is_empty() && replacement.values.capacity() >= self.len());
        assert!(match (&self.memory, &replacement.memory) {
            (Some(current), Some(prepared)) => Arc::ptr_eq(current, prepared),
            (None, None) => true,
            _ => false,
        });
        let old = core::mem::replace(self, replacement);
        // The old owning iterator retains its original backing charge until
        // the actual old allocation is destroyed after the final move.
        for value in old {
            self.values
                .push(value)
                .expect("replacement capacity was admitted");
        }
    }

    /// Insert into already admitted capacity. Exposes no allocating container.
    pub(crate) fn insert_reserved(&mut self, index: usize, value: T) {
        assert!(index <= self.len() && self.len() < self.values.capacity());
        self.values
            .push(value)
            .expect("insertion capacity was admitted");
        self.values[index..].rotate_right(1);
    }

    pub(crate) fn resize_with(&mut self, len: usize, mut value: impl FnMut() -> T) -> Result<()> {
        self.reserve(len.saturating_sub(self.values.len()))?;
        self.values.resize_with(len, &mut value)?;
        Ok(())
    }
}

impl<T> Deref for NativeVec<T> {
    type Target = [T];
    fn deref(&self) -> &[T] {
        &self.values
    }
}

impl<T> DerefMut for NativeVec<T> {
    fn deref_mut(&mut self) -> &mut [T] {
        &mut self.values
    }
}

pub(crate) struct NativeVecIntoIter<T> {
    values: <TryVec<T> as IntoIterator>::IntoIter,
    _allocation: Owner,
    _memory: Memory,
}

impl<T> Iterator for NativeVecIntoIter<T> {
    type Item = T;
    fn next(&mut self) -> Option<T> {
        self.values.next()
    }
    fn size_hint(&self) -> (usize, Option<usize>) {
        self.values.size_hint()
    }
}

impl<T> IntoIterator for NativeVec<T> {
    type Item = T;
    type IntoIter = NativeVecIntoIter<T>;
    fn into_iter(self) -> Self::IntoIter {
        NativeVecIntoIter {
            values: self.values.into_iter(),
            _allocation: self.allocation,
            _memory: self.memory,
        }
    }
}

pub(crate) struct NativeMap<K: EntityRef, V> {
    values: TryPrimaryMap<K, V>,
    allocation: Owner,
    memory: Memory,
    capacity: usize,
}

impl<K: EntityRef, V> Default for NativeMap<K, V> {
    fn default() -> Self {
        Self {
            values: TryPrimaryMap::new(),
            allocation: None,
            memory: None,
            capacity: 0,
        }
    }
}

impl<K: EntityRef + fmt::Debug, V: fmt::Debug> fmt::Debug for NativeMap<K, V> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.values.fmt(f)
    }
}

impl<K: EntityRef, V> NativeMap<K, V> {
    pub(crate) fn new(memory: Memory) -> Self {
        Self {
            values: TryPrimaryMap::new(),
            allocation: None,
            memory,
            capacity: 0,
        }
    }

    pub(crate) fn with_capacity(capacity: usize, memory: Memory) -> Result<Self> {
        let (values, allocation) = if memory.is_some() {
            let (values, allocation) = exact_vec(capacity, &memory)?;
            (TryPrimaryMap::from(values), allocation)
        } else {
            (TryPrimaryMap::with_capacity(capacity)?, None)
        };
        Ok(Self {
            values,
            allocation,
            memory,
            capacity,
        })
    }

    /// A private fixed-capacity wrapper may discard the factory only after it
    /// has prepaid all slots and prevents every subsequent capacity increase.
    /// The affine backing owner stays with this map independently of factory.
    pub(crate) fn detach_factory(&mut self) {
        self.memory = None;
    }

    pub(crate) fn reserve(&mut self, additional: usize) -> Result<()> {
        if self.memory.is_none() {
            return Ok(self.values.reserve(additional)?);
        }
        let required = self
            .values
            .len()
            .checked_add(additional)
            .ok_or_else(|| OutOfMemory::new(usize::MAX))?;
        if required <= self.capacity {
            return Ok(());
        }
        let mut replacement = Self::with_capacity(required, self.memory.clone())?;
        let old = NativeMapIntoIter {
            values: core::mem::take(&mut self.values).into_iter(),
            _allocation: self.allocation.take(),
            _memory: self.memory.clone(),
        };
        for (key, value) in old {
            assert_eq!(key.index(), replacement.values.next_key().index());
            replacement
                .values
                .push(value)
                .expect("exact replacement capacity was admitted");
        }
        *self = replacement;
        Ok(())
    }

    pub(crate) fn push(&mut self, value: V) -> Result<K> {
        self.reserve(1)?;
        Ok(self
            .values
            .push(value)
            .expect("capacity was admitted above"))
    }

    pub(crate) fn iter_mut(&mut self) -> impl ExactSizeIterator<Item = (K, &mut V)> {
        self.values.iter_mut()
    }

    pub(crate) fn get_disjoint_mut<const N: usize>(
        &mut self,
        indices: [K; N],
    ) -> core::result::Result<[&mut V; N], core::slice::GetDisjointMutError> {
        self.values.get_disjoint_mut(indices)
    }
}

impl<K: EntityRef, V> Deref for NativeMap<K, V> {
    type Target = TryPrimaryMap<K, V>;
    fn deref(&self) -> &Self::Target {
        &self.values
    }
}

impl<K: EntityRef, V> Index<K> for NativeMap<K, V> {
    type Output = V;
    fn index(&self, key: K) -> &V {
        &self.values[key]
    }
}

impl<K: EntityRef, V> IndexMut<K> for NativeMap<K, V> {
    fn index_mut(&mut self, key: K) -> &mut V {
        &mut self.values[key]
    }
}

impl<'a, K: EntityRef, V> IntoIterator for &'a mut NativeMap<K, V> {
    type Item = (K, &'a mut V);
    type IntoIter = <&'a mut TryPrimaryMap<K, V> as IntoIterator>::IntoIter;

    fn into_iter(self) -> Self::IntoIter {
        (&mut self.values).into_iter()
    }
}

pub(crate) struct NativeMapIntoIter<K: EntityRef, V> {
    values: <TryPrimaryMap<K, V> as IntoIterator>::IntoIter,
    _allocation: Owner,
    _memory: Memory,
}

impl<K: EntityRef, V> Iterator for NativeMapIntoIter<K, V> {
    type Item = (K, V);
    fn next(&mut self) -> Option<Self::Item> {
        self.values.next()
    }
    fn size_hint(&self) -> (usize, Option<usize>) {
        self.values.size_hint()
    }
}

impl<K: EntityRef, V> IntoIterator for NativeMap<K, V> {
    type Item = (K, V);
    type IntoIter = NativeMapIntoIter<K, V>;
    fn into_iter(self) -> Self::IntoIter {
        NativeMapIntoIter {
            values: self.values.into_iter(),
            _allocation: self.allocation,
            _memory: self.memory,
        }
    }
}
