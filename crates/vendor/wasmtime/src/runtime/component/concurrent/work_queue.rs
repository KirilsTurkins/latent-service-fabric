//! Exact, pre-admitted backing for scheduler queue entries.
//!
//! A slot is prepared before polling or transferring state. Publication only
//! links that same allocation; removal retains it until reuse or physical
//! deallocation before refund. Stores
//! without a native-memory owner retain their original VecDeque backing.

use crate::runtime::native_memory::{self, Memory};
use crate::{NativeAllocation, Result};
use alloc::boxed::Box;
use alloc::collections::VecDeque;
use core::alloc::Layout;
use core::marker::PhantomData;
use core::mem::ManuallyDrop;
use core::ops::{Deref, DerefMut};
use core::ptr::NonNull;

struct Entry<T> {
    value: Option<T>,
    next: Option<Node<T>>,
    previous: Option<NonNull<Entry<T>>>,
}

struct Node<T> {
    pointer: NonNull<Entry<T>>,
    allocation: ManuallyDrop<Box<dyn NativeAllocation>>,
    _owned: PhantomData<Box<Entry<T>>>,
}

impl<T> Deref for Node<T> {
    type Target = Entry<T>;
    fn deref(&self) -> &Entry<T> {
        // SAFETY: a private affine node owns this allocation until Drop. Shared
        // traversal does not mutate links or values.
        unsafe { self.pointer.as_ref() }
    }
}

impl<T> DerefMut for Node<T> {
    fn deref_mut(&mut self) -> &mut Entry<T> {
        // SAFETY: all mutation requires the unique node/queue borrow. No Box
        // is reconstructed, moved or retagged while linked raw pointers exist.
        unsafe { self.pointer.as_mut() }
    }
}

// SAFETY: pointer owns one private Entry allocation; predecessor/tail pointers
// only refer into that same exclusively owned chain. Moving an affine node
// never dereferences it. All unlinking requires &mut Queue; isolated slots have
// no predecessor. Box::from_raw occurs once, only when the node is destroyed.
unsafe impl<T: Send> Send for Node<T> {}
// SAFETY: shared access only exposes &T or follows immutable owned links.
unsafe impl<T: Sync> Sync for Node<T> {}

impl<T> Drop for Node<T> {
    fn drop(&mut self) {
        // SAFETY: affine private fields are destroyed once, in physical order.
        // If a queued value's destructor unwinds, retain the SAME charge; do
        // not certify deallocation or refund before the Box drop completes.
        unsafe {
            drop(Box::from_raw(self.pointer.as_ptr()));
            ManuallyDrop::drop(&mut self.allocation);
        }
    }
}

pub(super) struct Slot<T>(Option<Node<T>>);

impl<T> core::fmt::Debug for Slot<T> {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        f.debug_struct("QueueSlot")
            .field("accounted", &self.0.is_some())
            .finish()
    }
}

impl<T> Slot<T> {
    pub(super) fn prepare(memory: &Memory) -> Result<Self> {
        let Some(allocation) = native_memory::reserve(memory, Layout::new::<Entry<T>>().size())?
        else {
            return Ok(Self(None));
        };
        let entry = Box::new(Entry {
            value: None,
            next: None,
            previous: None,
        });
        let mut node = Node {
            pointer: NonNull::new(Box::into_raw(entry)).expect("Box is nonnull"),
            allocation: ManuallyDrop::new(allocation),
            _owned: PhantomData,
        };
        // Install the outside owner before this possibly panicking hook.
        node.allocation.allocated();
        Ok(Self(Some(node)))
    }
}

struct Linked<T> {
    // Suppress automatic recursive drop on value-destructor unwind. The normal
    // destructor drains iteratively; an unwind retains the remaining chain and
    // its SAME charges rather than refunding unfreed backing.
    head: ManuallyDrop<Option<Node<T>>>,
    tail: Option<NonNull<Entry<T>>>,
    len: usize,
}

// SAFETY: tail and predecessor pointers refer only into the exclusively owned
// head chain. Owned heap allocations stay stable as nodes move; T must be Send.
unsafe impl<T: Send> Send for Linked<T> {}
// SAFETY: immutable traversal exposes shared T references only.
unsafe impl<T: Sync> Sync for Linked<T> {}

impl<T> Default for Linked<T> {
    fn default() -> Self {
        Self {
            head: ManuallyDrop::new(None),
            tail: None,
            len: 0,
        }
    }
}

impl<T> Linked<T> {
    fn push_front(&mut self, mut node: Node<T>) {
        assert!(node.next.is_none() && node.previous.is_none());
        let pointer = node.pointer;
        node.next = self.head.take();
        if let Some(next) = node.next.as_mut() {
            next.previous = Some(pointer);
        } else {
            self.tail = Some(pointer);
        }
        *self.head = Some(node);
        self.len += 1;
    }

    fn remove(&mut self, index: usize) -> Option<Node<T>> {
        if index >= self.len {
            return None;
        }
        let mut link = &mut *self.head;
        for _ in 0..index {
            link = &mut link.as_mut().unwrap().next;
        }
        let mut node = link.take().unwrap();
        let previous = node.previous.take();
        *link = node.next.take();
        if let Some(next) = link.as_mut() {
            next.previous = previous;
        } else {
            self.tail = previous;
        }
        self.len -= 1;
        Some(node)
    }

    fn pop_back(&mut self) -> Option<Node<T>> {
        let mut tail = self.tail?;
        // SAFETY: tail is maintained by push/remove, refers to the live last
        // entry, and exclusive &mut self prevents any other access.
        let previous = unsafe { tail.as_mut().previous.take() };
        let node = if let Some(mut previous) = previous {
            // SAFETY: the predecessor belongs to this same live chain. Taking
            // its next disconnects exactly the tail, never an aliased owner.
            unsafe { previous.as_mut().next.take().unwrap() }
        } else {
            self.head.take().unwrap()
        };
        self.tail = previous;
        self.len -= 1;
        Some(node)
    }

    fn retain(&mut self, mut keep: impl FnMut(&T) -> bool) {
        let mut previous = None;
        let mut link = &mut *self.head;
        while link.is_some() {
            if keep(link.as_ref().unwrap().value.as_ref().unwrap()) {
                let node = link.as_mut().unwrap();
                previous = Some(node.pointer);
                link = &mut node.next;
            } else {
                let mut node = link.take().unwrap();
                *link = node.next.take();
                node.previous = None;
                if let Some(next) = link.as_mut() {
                    next.previous = previous;
                } else {
                    self.tail = previous;
                }
                self.len -= 1;
                drop(node);
            }
        }
    }
}

impl<T> Drop for Linked<T> {
    fn drop(&mut self) {
        while let Some(mut node) = self.head.take() {
            *self.head = node.next.take();
            node.previous = None;
            drop(node);
        }
    }
}

pub(super) struct Queue<T> {
    accounted: bool,
    legacy: VecDeque<T>,
    linked: Linked<T>,
}

impl<T> Default for Queue<T> {
    fn default() -> Self {
        Self::new(false)
    }
}

impl<T> Queue<T> {
    pub(super) fn new(accounted: bool) -> Self {
        Self {
            accounted,
            legacy: VecDeque::new(),
            linked: Linked::default(),
        }
    }

    pub(super) fn push_front(&mut self, slot: Slot<T>, value: T) {
        match slot.0 {
            Some(mut node) => {
                assert!(self.accounted);
                assert!(node.value.is_none());
                node.value = Some(value);
                self.linked.push_front(node);
            }
            None => {
                assert!(!self.accounted);
                self.legacy.push_front(value);
            }
        }
    }

    pub(super) fn len(&self) -> usize {
        if self.accounted {
            self.linked.len
        } else {
            self.legacy.len()
        }
    }

    pub(super) fn is_empty(&self) -> bool {
        self.len() == 0
    }

    pub(super) fn pop_back(&mut self) -> Option<(Slot<T>, T)> {
        if self.accounted {
            let mut node = self.linked.pop_back()?;
            let value = node.value.take().unwrap();
            Some((Slot(Some(node)), value))
        } else {
            self.legacy.pop_back().map(|value| (Slot(None), value))
        }
    }

    pub(super) fn remove(&mut self, index: usize) -> Option<(Slot<T>, T)> {
        if self.accounted {
            let mut node = self.linked.remove(index)?;
            let value = node.value.take().unwrap();
            Some((Slot(Some(node)), value))
        } else {
            self.legacy.remove(index).map(|value| (Slot(None), value))
        }
    }

    pub(super) fn iter(&self) -> impl Iterator<Item = &T> {
        let mut next = self.linked.head.as_ref();
        let linked = core::iter::from_fn(move || {
            let node = next?;
            next = node.next.as_ref();
            node.value.as_ref()
        });
        self.legacy.iter().chain(linked)
    }

    pub(super) fn retain(&mut self, mut keep: impl FnMut(&T) -> bool) {
        if !self.accounted {
            self.legacy.retain(keep);
            return;
        }
        self.linked.retain(&mut keep);
    }

    #[cfg(feature = "gc")]
    pub(super) fn for_each_mut(&mut self, mut visit: impl FnMut(&mut T)) {
        for value in &mut self.legacy {
            visit(value);
        }
        let mut next = self.linked.head.as_mut();
        while let Some(node) = next {
            let entry = &mut **node;
            visit(entry.value.as_mut().unwrap());
            next = entry.next.as_mut();
        }
    }
}

pub(super) struct IntoIter<T>(Queue<T>);

impl<T> Iterator for IntoIter<T> {
    type Item = T;
    fn next(&mut self) -> Option<T> {
        self.0.remove(0).map(|(_slot, value)| value)
    }
}

impl<T> IntoIterator for Queue<T> {
    type Item = T;
    type IntoIter = IntoIter<T>;
    fn into_iter(self) -> IntoIter<T> {
        IntoIter(self)
    }
}

#[cfg(test)]
pub(super) fn allocation_layout_witness<T>() -> core::alloc::Layout {
    core::alloc::Layout::new::<Entry<T>>()
}

#[cfg(test)]
mod tests {
    use super::*;
    use alloc::sync::Arc;
    use alloc::vec::Vec;
    use core::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
    use std::panic::{AssertUnwindSafe, catch_unwind};

    #[derive(Default)]
    struct Probe {
        requests: AtomicUsize,
        live: AtomicUsize,
        confirmed: AtomicUsize,
        values_dropped: AtomicUsize,
        require_value_drop: AtomicBool,
    }
    struct Allocation {
        probe: Arc<Probe>,
        panic_confirmation: bool,
    }
    impl NativeAllocation for Allocation {
        fn allocated(&mut self) {
            self.probe.confirmed.fetch_add(1, Ordering::SeqCst);
            assert!(!self.panic_confirmation, "queue-confirmation-control");
        }
    }
    impl Drop for Allocation {
        fn drop(&mut self) {
            if self.probe.require_value_drop.load(Ordering::SeqCst) {
                assert_ne!(self.probe.values_dropped.load(Ordering::SeqCst), 0);
            }
            assert_ne!(self.probe.live.fetch_sub(1, Ordering::SeqCst), 0);
        }
    }
    struct Memory {
        probe: Arc<Probe>,
        expected: usize,
        refuse: bool,
        panic_confirmation: bool,
    }
    impl crate::NativeMemory for Memory {
        fn reserve(&self, bytes: usize) -> Result<Box<dyn NativeAllocation>> {
            assert_eq!(bytes, self.expected);
            self.probe.requests.fetch_add(1, Ordering::SeqCst);
            if self.refuse {
                crate::bail!("original-queue-refusal-control");
            }
            self.probe.live.fetch_add(1, Ordering::SeqCst);
            Ok(Box::new(Allocation {
                probe: self.probe.clone(),
                panic_confirmation: self.panic_confirmation,
            }))
        }
    }
    fn memory<T>(
        probe: &Arc<Probe>,
        refuse: bool,
        panic_confirmation: bool,
    ) -> native_memory::Memory {
        Some(Arc::new(Memory {
            probe: probe.clone(),
            expected: Layout::new::<Entry<T>>().size(),
            refuse,
            panic_confirmation,
        }))
    }
    struct Value {
        probe: Arc<Probe>,
        panic_drop: bool,
    }
    impl Drop for Value {
        fn drop(&mut self) {
            assert_ne!(self.probe.live.load(Ordering::SeqCst), 0);
            self.probe.values_dropped.fetch_add(1, Ordering::SeqCst);
            assert!(!self.panic_drop, "queue-value-destructor-control");
        }
    }

    #[test]
    fn queue_exact_layout_refusal_and_unused_slot_refund_before_effects() {
        // This is the compiled layout of the REAL scheduler entry, not a
        // guessed VecDeque capacity or a synthetic WorkItem substitute.
        let probe = Arc::new(Probe::default());
        assert!(
            Slot::<super::super::WorkItem>::prepare(&memory::<super::super::WorkItem>(
                &probe, true, false
            ))
            .is_err()
        );
        assert_eq!(probe.requests.load(Ordering::SeqCst), 1);
        assert_eq!(probe.confirmed.load(Ordering::SeqCst), 0);
        assert_eq!(probe.live.load(Ordering::SeqCst), 0);
        let slot = Slot::<super::super::WorkItem>::prepare(&memory::<super::super::WorkItem>(
            &probe, false, false,
        ))
        .unwrap();
        assert_eq!(probe.live.load(Ordering::SeqCst), 1);
        drop(slot); // Ready/unused: same actual empty Box dies before refund.
        assert_eq!(probe.live.load(Ordering::SeqCst), 0);
        assert_eq!(probe.confirmed.load(Ordering::SeqCst), 1);
        assert!(
            Slot::<super::super::WorkItem>::prepare(&None)
                .unwrap()
                .0
                .is_none()
        );
        println!(
            "LSF_WORK_QUEUE_LAYOUT_V1 bytes={} align={}",
            Layout::new::<Entry<super::super::WorkItem>>().size(),
            Layout::new::<Entry<super::super::WorkItem>>().align()
        );
        // Same pinned Arc implementation/source; compile a fresh layout
        // witness without replaying the old private JoinState programme.
        println!(
            "LSF_JOIN_STATE_LAYOUT_V1 bytes={}",
            super::super::abort::accounted_layout_witness()
        );
    }

    #[test]
    fn queue_fifo_promotion_retention_and_none_keep_original_order() {
        for accounted in [false, true] {
            let probe = Arc::new(Probe::default());
            let memory = if accounted {
                memory::<u32>(&probe, false, false)
            } else {
                None
            };
            let mut high = Queue::new(accounted);
            let mut low = Queue::new(accounted);
            for value in 0..8 {
                let slot = Slot::prepare(&memory).unwrap();
                low.push_front(slot, value);
            }
            assert_eq!(
                low.iter().copied().collect::<Vec<_>>(),
                (0..8).rev().collect::<Vec<_>>()
            );
            let (slot, value) = low.remove(3).unwrap();
            assert_eq!(value, 4);
            high.push_front(slot, value); // SAME node, no new admission.
            low.retain(|value| value % 2 == 0);
            assert_eq!(low.iter().copied().collect::<Vec<_>>(), vec![6, 2, 0]);
            let (slot, value) = high.pop_back().unwrap();
            assert_eq!(value, 4);
            assert_eq!(
                probe.requests.load(Ordering::SeqCst),
                if accounted { 8 } else { 0 }
            );
            assert_eq!(
                probe.live.load(Ordering::SeqCst),
                if accounted { 4 } else { 0 }
            );
            drop(slot);
            assert_eq!(low.pop_back().unwrap().1, 0);
            assert_eq!(low.pop_back().unwrap().1, 2);
            assert_eq!(low.pop_back().unwrap().1, 6);
            assert!(low.is_empty() && high.is_empty());
            drop((low, high));
            assert_eq!(probe.live.load(Ordering::SeqCst), 0);
        }
    }

    #[test]
    fn queue_confirmation_unwind_and_value_drop_precede_original_refund() {
        let probe = Arc::new(Probe::default());
        assert!(
            catch_unwind(AssertUnwindSafe(|| {
                let _slot = Slot::<Value>::prepare(&memory::<Value>(&probe, false, true));
            }))
            .is_err()
        );
        assert_eq!(probe.live.load(Ordering::SeqCst), 0);
        assert_eq!(probe.confirmed.load(Ordering::SeqCst), 1);
        let slot = Slot::prepare(&memory::<Value>(&probe, false, false)).unwrap();
        let mut queue = Queue::new(true);
        queue.push_front(
            slot,
            Value {
                probe: probe.clone(),
                panic_drop: false,
            },
        );
        probe.require_value_drop.store(true, Ordering::SeqCst);
        drop(queue);
        assert_eq!(probe.values_dropped.load(Ordering::SeqCst), 1);
        assert_eq!(probe.live.load(Ordering::SeqCst), 0);
    }

    #[test]
    fn queue_value_unwind_retains_same_node_and_remaining_chain_charges() {
        let probe = Arc::new(Probe::default());
        let memory = memory::<Value>(&probe, false, false);
        let mut queue = Queue::new(true);
        for panic_drop in [false, false, true] {
            let slot = Slot::prepare(&memory).unwrap();
            queue.push_front(
                slot,
                Value {
                    probe: probe.clone(),
                    panic_drop,
                },
            );
        }
        assert!(catch_unwind(AssertUnwindSafe(|| drop(queue))).is_err());
        assert_eq!(probe.requests.load(Ordering::SeqCst), 3);
        assert_eq!(probe.confirmed.load(Ordering::SeqCst), 3);
        assert_eq!(probe.values_dropped.load(Ordering::SeqCst), 1);
        assert_eq!(probe.live.load(Ordering::SeqCst), 3);
    }
}
