//! Paid Store-local function-reference containers. Shared host closure backing
//! and direct host-function construction are separate ownership domains.
use crate::prelude::*;
use crate::runtime::native_memory::{Memory, NativeVec, reserve};
use crate::runtime::vm::{SendSyncPtr, StoreBox, VMFuncRef};
use crate::{NativeAllocation, NativeMemory};
use alloc::sync::Arc;
use core::alloc::Layout;
use core::ptr::NonNull;

struct OwnedFuncRef {
    // StoreBox is an affine raw-pointer owner: moving this directory entry
    // cannot invalidate derived VM pointers. Free actual bytes before refund.
    value: StoreBox<VMFuncRef>,
    _allocation: Option<Box<dyn NativeAllocation>>,
}

impl OwnedFuncRef {
    fn new(value: VMFuncRef, memory: &Memory) -> Result<Self> {
        let mut allocation = reserve(memory, Layout::new::<VMFuncRef>().size())?;
        let value = StoreBox::new(value)?;
        if let Some(allocation) = allocation.as_mut() {
            allocation.allocated();
        }
        Ok(Self {
            value,
            _allocation: allocation,
        })
    }
}

pub(super) struct NativeFuncRefs<T> {
    arena: NativeVec<OwnedFuncRef>,
    holes: NativeVec<SendSyncPtr<VMFuncRef>>,
    roots: NativeVec<T>,
    memory: Memory,
}

fn capacity(required: usize) -> usize {
    required.checked_next_power_of_two().unwrap_or(required)
}

fn additional(len: usize, count: usize) -> Result<usize> {
    Ok(capacity(
        len.checked_add(count)
            .ok_or_else(|| OutOfMemory::new(usize::MAX))?,
    ))
}

impl<T> NativeFuncRefs<T> {
    pub(super) fn new(memory: Arc<dyn NativeMemory>) -> Result<Self> {
        let memory = Some(memory);
        Ok(Self {
            arena: NativeVec::with_capacity(0, memory.clone())?,
            holes: NativeVec::with_capacity(0, memory.clone())?,
            roots: NativeVec::with_capacity(0, memory.clone())?,
            memory,
        })
    }

    pub(super) fn push(
        &mut self,
        value: VMFuncRef,
        has_hole: bool,
        root: T,
    ) -> Result<NonNull<VMFuncRef>> {
        // Stage every fallible allocation before changing a live root or hole.
        // This also retains old+replacement buffer charges during overlap.
        let arena = self
            .arena
            .prepare_capacity(additional(self.arena.len(), 1)?)?;
        let holes = if has_hole {
            self.holes
                .prepare_capacity(additional(self.holes.len(), 1)?)?
        } else {
            None
        };
        let roots = self
            .roots
            .prepare_capacity(additional(self.roots.len(), 1)?)?;
        let value = OwnedFuncRef::new(value, &self.memory)?;
        let pointer = value.value.get();

        self.arena.commit_capacity(arena);
        self.holes.commit_capacity(holes);
        self.roots.commit_capacity(roots);
        // No allocation follows publication. Root the vmctx before its copied
        // raw reference can become visible to fill or to the caller.
        self.roots.insert_reserved(self.roots.len(), root);
        self.arena.insert_reserved(self.arena.len(), value);
        if has_hole {
            self.holes.insert_reserved(self.holes.len(), pointer.into());
        }
        Ok(pointer)
    }

    pub(super) fn push_roots(&mut self, first: T, second: T) -> Result<()> {
        let roots = self
            .roots
            .prepare_capacity(additional(self.roots.len(), 2)?)?;
        self.roots.commit_capacity(roots);
        self.roots.insert_reserved(self.roots.len(), first);
        self.roots.insert_reserved(self.roots.len(), second);
        Ok(())
    }

    pub(super) fn fill(&mut self, mut still_has_hole: impl FnMut(&mut VMFuncRef) -> bool) {
        // Logical removal never refunds capacity retained by the actual Vec.
        self.holes
            .retain_mut(|pointer| unsafe { still_has_hole(pointer.as_mut()) });
    }
}
