//! Instance resource substitutions can escape their Store in type/InstancePre
//! handles. Keep the allocation owner with every private strong handle, without
//! carrying the Store's native factory past Store destruction.

use crate::component::ResourceType;
use crate::native_memory::{Memory, NativeMap};
use crate::{NativeAllocation, prelude::*};
use alloc::sync::Arc;
use core::alloc::Layout;
use core::mem::ManuallyDrop;
use core::ops::Deref;
use core::sync::atomic::AtomicUsize;
use wasmtime_environ::component::ResourceIndex;

/// Private implementation type also used by the hidden instance-type view.
/// No Arc or Weak handle is exposed: every strong clone uses the drop below.
pub struct ResourceTypes {
    inner: Inner,
}

enum Inner {
    Legacy(Arc<TryPrimaryMap<ResourceIndex, ResourceType>>),
    Accounted(ManuallyDrop<Arc<Accounted>>),
}

struct Accounted {
    values: ManuallyDrop<NativeMap<ResourceIndex, ResourceType>>,
    allocation: ManuallyDrop<Box<dyn NativeAllocation>>,
    capacity: usize,
}

impl Drop for Accounted {
    fn drop(&mut self) {
        // The Arc allocation is already freed by into_inner. If a backing
        // destructor unwinds, retain the outer owner conservatively.
        unsafe {
            ManuallyDrop::drop(&mut self.values);
            ManuallyDrop::drop(&mut self.allocation);
        }
    }
}

impl ResourceTypes {
    pub(crate) fn new() -> Result<Self> {
        Self::with_capacity(0, None)
    }

    pub(crate) fn with_capacity(capacity: usize, memory: Memory) -> Result<Self> {
        let Some(memory) = memory else {
            return Ok(Self {
                inner: Inner::Legacy(try_new::<Arc<_>>(TryPrimaryMap::with_capacity(capacity)?)?),
            });
        };

        // num_resources is the exact finite total of imported and defined
        // resources. All later pushes use these prepaid slots; none can grow.
        let mut values = NativeMap::with_capacity(capacity, Some(memory.clone()))?;
        values.detach_factory();
        // The pinned alloc::sync::ArcInner has two AtomicUsize counters then T.
        // Include alignment/padding, without depending on Arc raw-pointer ABI.
        let bytes = Layout::new::<[AtomicUsize; 2]>()
            .extend(Layout::new::<Accounted>())
            .map_err(|_| OutOfMemory::new(usize::MAX))?
            .0
            .pad_to_align()
            .size();
        let allocation = memory.reserve(bytes)?;
        let shared = try_new::<Arc<_>>(Accounted {
            values: ManuallyDrop::new(values),
            allocation: ManuallyDrop::new(allocation),
            capacity,
        })?;
        let mut result = Self {
            inner: Inner::Accounted(ManuallyDrop::new(shared)),
        };
        // Install the last-strong drop path before invoking the confirmation
        // callback, so its unwind cannot refund an allocated Arc prematurely.
        if let Inner::Accounted(shared) = &mut result.inner {
            Arc::get_mut(shared).unwrap().allocation.allocated();
        }
        Ok(result)
    }

    pub(crate) fn push(&mut self, value: ResourceType) -> Result<ResourceIndex> {
        match &mut self.inner {
            Inner::Legacy(shared) => Ok(Arc::get_mut(shared).unwrap().push(value)?),
            Inner::Accounted(shared) => {
                let inner = Arc::get_mut(shared).unwrap();
                ensure!(
                    inner.values.len() < inner.capacity,
                    "resource-type-map-capacity"
                );
                inner.values.push(value)
            }
        }
    }

    pub(crate) fn ptr_eq(a: &Self, b: &Self) -> bool {
        match (&a.inner, &b.inner) {
            (Inner::Legacy(a), Inner::Legacy(b)) => Arc::ptr_eq(a, b),
            (Inner::Accounted(a), Inner::Accounted(b)) => Arc::ptr_eq(a, b),
            _ => false,
        }
    }
}

impl Clone for ResourceTypes {
    fn clone(&self) -> Self {
        Self {
            inner: match &self.inner {
                Inner::Legacy(shared) => Inner::Legacy(shared.clone()),
                Inner::Accounted(shared) => Inner::Accounted(ManuallyDrop::new(Arc::clone(shared))),
            },
        }
    }
}

impl Deref for ResourceTypes {
    type Target = TryPrimaryMap<ResourceIndex, ResourceType>;

    fn deref(&self) -> &Self::Target {
        match &self.inner {
            Inner::Legacy(shared) => shared,
            Inner::Accounted(shared) => &shared.values,
        }
    }
}

impl Drop for ResourceTypes {
    fn drop(&mut self) {
        if let Inner::Accounted(shared) = &mut self.inner {
            // All strong clones take this path and no Weak can escape. The
            // standard into_inner guarantee selects exactly one last payload,
            // even when several handles are destroyed concurrently. Its Arc
            // allocation is freed before Accounted drops backing and owners.
            let shared = unsafe { ManuallyDrop::take(shared) };
            drop(Arc::into_inner(shared));
        }
    }
}
