//! A queue for batching decommits together.
//!
//! We don't immediately decommit a Wasm table/memory/stack/etc... eagerly, but
//! instead batch them up to be decommitted together. This module implements
//! that queuing and batching.
//!
//! Even when batching is "disabled" we still use this queue. Batching is
//! disabled by specifying a batch size of one, in which case, this queue will
//! immediately get flushed every time we push onto it.

use super::PoolingInstanceAllocator;
use crate::vm::sys::vm::{decommit_pages, iovec};
use crate::vm::{MemoryAllocationIndex, MemoryImageSlot, Table, TableAllocationIndex};
use smallvec::SmallVec;
use std::io;

#[cfg(feature = "async")]
use wasmtime_fiber::FiberStack;

#[repr(transparent)]
struct IoVec(iovec);

unsafe impl Send for IoVec {}
unsafe impl Sync for IoVec {}

impl std::fmt::Debug for IoVec {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        f.debug_struct("IoVec")
            .field("base", &self.0.iov_base)
            .field("len", &self.0.iov_len)
            .finish()
    }
}

#[cfg(feature = "async")]
struct SendSyncStack(FiberStack);
#[cfg(feature = "async")]
unsafe impl Send for SendSyncStack {}
#[cfg(feature = "async")]
unsafe impl Sync for SendSyncStack {}

#[derive(Default)]
pub struct DecommitQueue {
    raw: SmallVec<[IoVec; 2]>,
    memories: SmallVec<[(MemoryAllocationIndex, MemoryImageSlot, usize); 1]>,
    tables: SmallVec<[(TableAllocationIndex, Table, usize); 1]>,
    #[cfg(feature = "async")]
    stacks: SmallVec<[(SendSyncStack, usize); 1]>,
    //
    // TODO: GC heaps are not well-integrated with the pooling allocator
    // yet. Once we better integrate them, we should start (optionally) zeroing
    // them, and batching that up here.
    //
    // #[cfg(feature = "gc")]
    // pub gc_heaps: SmallVec<[(GcHeapAllocationIndex, Box<dyn GcHeap>); 1]>,
}

impl std::fmt::Debug for DecommitQueue {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("DecommitQueue")
            .field("raw", &self.raw)
            .finish_non_exhaustive()
    }
}

impl DecommitQueue {
    /// Append another queue to this queue.
    pub fn append(
        &mut self,
        Self {
            raw,
            memories,
            tables,
            #[cfg(feature = "async")]
            stacks,
        }: &mut Self,
    ) {
        self.raw.append(raw);
        self.memories.append(memories);
        self.tables.append(tables);
        #[cfg(feature = "async")]
        self.stacks.append(stacks);
    }

    /// How many raw memory regions are enqueued for decommit?
    pub fn raw_len(&self) -> usize {
        self.raw.len()
    }

    /// Enqueue a region of memory for decommit.
    ///
    /// It is the caller's responsibility to push the associated data via
    /// `self.push_{memory,table,stack}` as appropriate.
    ///
    /// # Safety
    ///
    /// The enqueued memory regions must be safe to decommit when `flush` is
    /// called (no other references, not in use, won't be otherwise unmapped,
    /// etc...).
    pub unsafe fn push_raw(&mut self, ptr: *mut u8, len: usize) {
        self.raw.push(IoVec(iovec {
            iov_base: ptr.cast(),
            iov_len: len,
        }));
    }

    /// Push a memory into the queue.
    ///
    /// # Safety
    ///
    /// This memory should not be in use, and its decommit regions must have
    /// already been enqueued via `self.enqueue_raw`.
    pub unsafe fn push_memory(
        &mut self,
        allocation_index: MemoryAllocationIndex,
        image: MemoryImageSlot,
        bytes_resident: usize,
    ) {
        self.memories
            .push((allocation_index, image, bytes_resident));
    }

    /// Push a table into the queue.
    ///
    /// # Safety
    ///
    /// This table should not be in use, and its decommit regions must have
    /// already been enqueued via `self.enqueue_raw`.
    pub unsafe fn push_table(
        &mut self,
        allocation_index: TableAllocationIndex,
        table: Table,
        bytes_resident: usize,
    ) {
        self.tables.push((allocation_index, table, bytes_resident));
    }

    /// Push a stack into the queue.
    ///
    /// # Safety
    ///
    /// This stack should not be in use, and its decommit regions must have
    /// already been enqueued via `self.enqueue_raw`.
    #[cfg(feature = "async")]
    pub unsafe fn push_stack(&mut self, stack: FiberStack, bytes_resident: usize) {
        self.stacks.push((SendSyncStack(stack), bytes_resident));
    }

    /// Whether every region and its original allocation owner has retired.
    pub fn is_empty(&self) -> bool {
        self.raw.is_empty() && self.memories.is_empty() && self.tables.is_empty() && {
            #[cfg(feature = "async")]
            {
                self.stacks.is_empty()
            }
            #[cfg(not(feature = "async"))]
            {
                true
            }
        }
    }

    /// Flush this queue, retaining the whole batch on any decommit failure.
    ///
    /// A failed syscall may already have decommitted a prefix. Retrying the
    /// original ranges is idempotent; returning any slot or dropping its owner
    /// before the entire batch succeeds is not. In particular, memset is not
    /// a physical decommit acknowledgement.
    ///
    /// Returns true only if at least one entity was returned to a free list.
    pub fn flush(&mut self, pool: &PoolingInstanceAllocator) -> bool {
        if !self.decommit_all_raw() {
            return false;
        }
        self.release(pool)
    }

    pub(super) fn decommit_all_raw(&mut self) -> bool {
        self.decommit_with(|iov| {
            #[cfg(all(test, target_os = "linux", feature = "cranelift", feature = "wat"))]
            if tests::refuse() {
                return Err(io::Error::other("test-only decommit refusal"));
            }
            // SAFETY: push_raw requires every range to remain allocated and
            // unused until successful decommit. Failure retains that custody.
            unsafe { decommit_pages(iov) }
        })
    }

    // The injection seam is private and monomorphized. Production always uses
    // the actual syscall above; tests can refuse or decommit only a prefix.
    fn decommit_with(&mut self, decommit: impl FnOnce(&[iovec]) -> io::Result<()>) -> bool {
        if !self.raw.is_empty() {
            let iov: &[IoVec] = self.raw.as_slice();
            // SAFETY: IoVec is repr(transparent) over iovec.
            let iov = unsafe { &*(iov as *const [IoVec] as *const [iovec]) };
            if let Err(error) = decommit(iov) {
                log::warn!("retaining pooled allocations after decommit failure: {error}");
                return false;
            }
            self.raw.clear();
        }

        true
    }

    #[cfg(test)]
    fn flush_with(
        &mut self,
        pool: &PoolingInstanceAllocator,
        decommit: impl FnOnce(&[iovec]) -> io::Result<()>,
    ) -> bool {
        self.decommit_with(decommit) && self.release(pool)
    }

    /// Called only after physical acknowledgement, outside queue locks. Owner
    /// destructors may run host code; do not hold a shard lock across them.
    pub(super) fn release(&mut self, pool: &PoolingInstanceAllocator) -> bool {
        assert!(self.raw.is_empty());
        let mut deallocated_any = false;
        if !self.memories.is_empty() {
            deallocated_any = true;
            // SAFETY: all queued regions have been successfully decommitted.
            unsafe {
                pool.memories.deallocate_many(self.memories.drain(..).map(
                    |(allocation_index, image, bytes_resident)| {
                        (allocation_index, Some(image), bytes_resident)
                    },
                ));
            }
        }
        if !self.tables.is_empty() {
            deallocated_any = true;
            // SAFETY: all queued regions have been successfully decommitted.
            unsafe {
                pool.tables.deallocate_many(self.tables.drain(..));
            }
        }
        #[cfg(feature = "async")]
        if !self.stacks.is_empty() {
            deallocated_any = true;
            // SAFETY: all queued stack pages have been successfully decommitted.
            unsafe {
                pool.stacks.deallocate_many(
                    self.stacks
                        .drain(..)
                        .map(|(stack, resident)| (stack.0, resident)),
                );
            }
        }
        deallocated_any
    }
}

#[cfg(all(test, target_os = "linux", feature = "cranelift", feature = "wat"))]
mod tests {
    //! Real pooled backing and allocation guards; only syscall failure is injected.
    //! These are not signed guest or whole-Store custody qualification.
    use super::*;
    use crate::prelude::*;
    use crate::{Config, Engine, Instance, Module, Ref, ResourceLimiter, Store};
    use std::sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    };

    struct Allocation(Arc<AtomicUsize>);
    impl crate::TableAllocation for Allocation {
        fn allocated(&mut self) {}
    }
    impl Drop for Allocation {
        fn drop(&mut self) {
            self.0.fetch_add(1, Ordering::SeqCst);
        }
    }
    struct Data(Arc<AtomicUsize>);
    impl ResourceLimiter for Data {
        fn memory_growing(&mut self, _: usize, _: usize, _: Option<usize>) -> crate::Result<bool> {
            Ok(true)
        }
        fn table_growing(&mut self, _: usize, _: usize, _: Option<usize>) -> crate::Result<bool> {
            Ok(true)
        }
        fn table_allocating(
            &mut self,
            _: usize,
        ) -> crate::Result<Option<Box<dyn crate::TableAllocation>>> {
            Ok(Some(Box::new(Allocation(self.0.clone()))))
        }
    }
    fn fixture() -> (Engine, Module, Store<Data>, Arc<AtomicUsize>) {
        fixture_with_batch(64)
    }
    fn fixture_with_batch(batch: usize) -> (Engine, Module, Store<Data>, Arc<AtomicUsize>) {
        let mut allocation = crate::PoolingAllocationConfig::new();
        allocation
            .total_core_instances(1)
            .total_component_instances(0)
            .total_memories(1)
            .max_memory_size(65536)
            .linear_memory_keep_resident(0)
            .total_tables(1)
            .table_elements(16)
            .table_keep_resident(0)
            .decommit_batch_size(batch)
            .max_unused_warm_slots(0);
        #[cfg(feature = "async")]
        allocation.total_stacks(1).async_stack_keep_resident(0);
        let mut config = Config::new();
        #[cfg(feature = "async")]
        config.async_stack_zeroing(true);
        config.allocation_strategy(allocation);
        let engine = Engine::new(&config).unwrap();
        let module = Module::new(
            &engine,
            r#"(module
        (memory (export "memory") 1)
        (table (export "table") 16 funcref)
        (func (export "f")))"#,
        )
        .unwrap();
        let drops = Arc::new(AtomicUsize::new(0));
        let mut store = Store::new(&engine, Data(drops.clone()));
        store.limiter(|data| data);
        let instance = Instance::new(&mut store, &module, &[]).unwrap();
        let function = instance.get_func(&mut store, "f").unwrap();
        instance
            .get_table(&mut store, "table")
            .unwrap()
            .set(&mut store, 0, Ref::Func(Some(function)))
            .unwrap();
        instance
            .get_memory(&mut store, "memory")
            .unwrap()
            .write(&mut store, 0, &[0x5a; 65536])
            .unwrap();
        (engine, module, store, drops)
    }
    fn shard_with_table(pool: &PoolingInstanceAllocator) -> super::super::ShardId {
        pool.decommit_shard_ids()
            .find(|&shard| !pool.decommit_queue(shard).lock().unwrap().tables.is_empty())
            .unwrap()
    }

    #[test]
    fn refused_batch_preserves_ranges_images_table_owners_and_pool_slots_until_retry() {
        let (engine, module, store, drops) = fixture();
        drop(store);
        let pool = engine.allocator().as_pooling().unwrap();
        let mut queue = pool.decommit_queue(shard_with_table(pool)).lock().unwrap();
        let ranges: Vec<_> = queue
            .raw
            .iter()
            .map(|i| (i.0.iov_base, i.0.iov_len))
            .collect();
        assert!(ranges.len() >= 2);
        assert_eq!(queue.memories.len(), 1);
        assert_eq!(queue.tables.len(), 1);
        for _ in 0..3 {
            assert!(
                !queue.flush_with(pool, |_| Err(io::Error::other("injected decommit refusal")))
            );
            assert_eq!(
                queue
                    .raw
                    .iter()
                    .map(|i| (i.0.iov_base, i.0.iov_len))
                    .collect::<Vec<_>>(),
                ranges
            );
            assert_eq!(drops.load(Ordering::SeqCst), 0);
            assert!(!pool.tables.is_empty());
            assert!(!pool.memories.is_empty());
        }
        assert!(queue.flush(pool));
        assert!(queue.is_empty());
        assert_eq!(drops.load(Ordering::SeqCst), 1);
        assert!(pool.tables.is_empty());
        assert!(pool.memories.is_empty());
        assert!(!queue.flush(pool));
        assert_eq!(drops.load(Ordering::SeqCst), 1);
        drop(queue);

        // A fresh Store reuses the same finite slots only after physical retirement.
        let mut fresh = Store::new(&engine, Data(drops.clone()));
        fresh.limiter(|data| data);
        let instance = Instance::new(&mut fresh, &module, &[]).unwrap();
        assert!(
            instance
                .get_memory(&mut fresh, "memory")
                .unwrap()
                .data(&fresh)
                .iter()
                .all(|byte| *byte == 0)
        );
        assert!(matches!(
            instance
                .get_table(&mut fresh, "table")
                .unwrap()
                .get(&mut fresh, 0),
            Some(Ref::Func(None))
        ));
        drop(fresh);
        assert!(pool.flush_all_decommit_queues());
        assert_eq!(drops.load(Ordering::SeqCst), 2);
    }

    #[test]
    fn partial_syscall_failure_retries_original_batch_without_early_owner_refund() {
        let (engine, _, store, drops) = fixture();
        drop(store);
        let pool = engine.allocator().as_pooling().unwrap();
        let mut queue = pool.decommit_queue(shard_with_table(pool)).lock().unwrap();
        let count = queue.raw_len();
        assert!(count >= 2);
        assert!(!queue.flush_with(pool, |iov| {
            // SAFETY: these are the actual unused, retained pool mappings.
            unsafe {
                decommit_pages(&iov[..1])?;
            }
            Err(io::Error::other(
                "injected failure after a successful prefix",
            ))
        }));
        assert_eq!(queue.raw_len(), count);
        assert_eq!(drops.load(Ordering::SeqCst), 0);
        assert!(queue.flush(pool));
        assert!(queue.is_empty());
        assert_eq!(drops.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn failed_batch_stays_in_its_shard_and_allocation_pressure_retries_it() {
        let (engine, module, store, drops) = fixture();
        drop(store);
        let pool = engine.allocator().as_pooling().unwrap();
        {
            let mut queue = pool.decommit_queue(shard_with_table(pool)).lock().unwrap();
            assert!(!queue.flush_with(pool, |_| Err(io::Error::other("refused"))));
            assert_eq!(drops.load(Ordering::SeqCst), 0);
        }
        // Neither slot is free. The production exhaustion path must flush the
        // retained shard successfully before it can admit this new instance.
        let mut fresh = Store::new(&engine, Data(drops.clone()));
        fresh.limiter(|data| data);
        let instance = Instance::new(&mut fresh, &module, &[]).unwrap();
        assert_eq!(drops.load(Ordering::SeqCst), 1);
        assert!(
            instance
                .get_memory(&mut fresh, "memory")
                .unwrap()
                .data(&fresh)
                .iter()
                .all(|byte| *byte == 0)
        );
        drop(fresh);
        pool.flush_all_decommit_queues();
        assert_eq!(drops.load(Ordering::SeqCst), 2);
    }

    #[test]
    fn empty_queue_never_invents_a_syscall_or_release() {
        let (engine, _, store, drops) = fixture();
        let pool = engine.allocator().as_pooling().unwrap();
        let mut queue = DecommitQueue::default();
        assert!(!queue.flush_with(pool, |_| panic!("empty batch must not issue decommit")));
        assert!(queue.is_empty());
        assert_eq!(drops.load(Ordering::SeqCst), 0);
        drop(store);
        pool.flush_all_decommit_queues();
    }

    std::thread_local! {
        static REFUSALS: std::cell::Cell<usize> = const { std::cell::Cell::new(0) };
    }
    pub(super) fn refuse() -> bool {
        REFUSALS.with(|left| {
            let remaining = left.get();
            left.set(remaining.saturating_sub(1));
            remaining != 0
        })
    }
    struct Refuse(usize);
    impl Refuse {
        fn all() -> Self {
            Self(REFUSALS.with(|left| left.replace(usize::MAX)))
        }
    }
    impl Drop for Refuse {
        fn drop(&mut self) {
            REFUSALS.with(|left| left.set(self.0));
        }
    }

    #[test]
    fn immediate_flush_failure_transfers_original_entities_to_existing_shard() {
        let (engine, _, store, drops) = fixture_with_batch(1);
        {
            let _refusal = Refuse::all();
            drop(store);
            let pool = engine.allocator().as_pooling().unwrap();
            assert!(!pool.flush_all_decommit_queues());
            assert_eq!(drops.load(Ordering::SeqCst), 0);
            let queue = pool.decommit_queue(shard_with_table(pool)).lock().unwrap();
            assert_eq!(queue.tables.len(), 1);
            assert_eq!(queue.memories.len(), 1);
            assert!(queue.raw_len() >= 2);
        }
        let pool = engine.allocator().as_pooling().unwrap();
        assert!(pool.flush_all_decommit_queues());
        assert_eq!(drops.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn pool_shutdown_retries_queued_backing_before_releasing_original_owner() {
        let (engine, module, store, drops) = fixture();
        drop(store);
        assert_eq!(drops.load(Ordering::SeqCst), 0);
        drop(module);
        drop(engine);
        assert_eq!(drops.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn terminal_pool_shutdown_refusal_retains_backing_and_original_owner() {
        let (engine, module, store, drops) = fixture();
        drop(store);
        drop(module);
        let _refusal = Refuse::all();
        drop(engine);
        assert_eq!(drops.load(Ordering::SeqCst), 0);
        // This one bounded pool is intentionally retained until process exit: the
        // production terminal path cannot fabricate a physical acknowledgement.
    }

    #[cfg(all(feature = "async", unix, not(miri), not(asan)))]
    #[test]
    fn native_stack_slot_is_unavailable_through_refusal_and_clean_on_retry() {
        use crate::vm::InstanceAllocator;
        let (engine, _, store, _) = fixture();
        let pool = engine.allocator().as_pooling().unwrap();
        let stack = pool.allocate_fiber_stack().unwrap();
        let top = stack.top().unwrap();
        // SAFETY: this is a privately owned, never-running stack's accessible top.
        unsafe {
            std::ptr::write_bytes(top.sub(4096), 0x6b, 4096);
        }
        unsafe {
            pool.deallocate_fiber_stack(stack);
        }
        {
            let _refusal = Refuse::all();
            assert!(pool.allocate_fiber_stack().is_err());
            assert!(!pool.stacks.is_empty());
        }
        let stack = pool.allocate_fiber_stack().unwrap();
        assert_eq!(stack.top().unwrap(), top);
        // SAFETY: successful production retry exclusively re-admitted this slot.
        assert!(
            unsafe { std::slice::from_raw_parts(top.sub(4096), 4096) }
                .iter()
                .all(|byte| *byte == 0)
        );
        unsafe {
            pool.deallocate_fiber_stack(stack);
        }
        drop(store);
        assert!(pool.flush_all_decommit_queues());
    }
}
