//! Sized-only shared backing with an owned declared allocation layout.
//!
//! This is private to the locked unordered fork. No std Arc layout is used.
//! Weak tokens retain the header and its SAME original charge after T is gone.

use super::abort::abort;
use crate::runtime::native_memory::{self, Memory};
use crate::{NativeAllocation, OutOfMemory, Result};
use alloc::alloc::{alloc, dealloc};
use alloc::boxed::Box;
use core::alloc::Layout;
use core::marker::PhantomData;
use core::mem::{ManuallyDrop, offset_of};
use core::ops::Deref;
use core::ptr::{self, NonNull};
use core::sync::atomic::Ordering::{Acquire, Relaxed, Release};
use core::sync::atomic::{AtomicUsize, fence};

const MAX_REFS: usize = isize::MAX as usize;

#[repr(C)]
struct Header<T> {
    strong: AtomicUsize,
    // Includes one implicit weak while any strong token remains.
    weak: AtomicUsize,
    charge: ManuallyDrop<Box<dyn NativeAllocation>>,
    value: ManuallyDrop<T>,
}

pub(super) struct Arc<T> {
    ptr: NonNull<Header<T>>,
    _owned: PhantomData<Header<T>>,
}

pub(super) struct Weak<T> {
    ptr: Option<NonNull<Header<T>>>,
    _owned: PhantomData<Header<T>>,
}

unsafe impl<T: Send + Sync> Send for Arc<T> {}
unsafe impl<T: Send + Sync> Sync for Arc<T> {}
unsafe impl<T: Send + Sync> Send for Weak<T> {}
unsafe impl<T: Send + Sync> Sync for Weak<T> {}

// The pinned Rust1.97.1 sync.rs counter rules are used only as synchronization
// guidance: positive ref clone Relaxed, upgrade Acquire, final Release/Acquire.
// CAS bounds EVERY increment before publishing it; no overflowing fetch_add.
fn increment(counter: &AtomicUsize) {
    let mut count = counter.load(Relaxed);
    loop {
        if count == 0 || count >= MAX_REFS {
            abort("private paid reference count overflow");
        }
        match counter.compare_exchange_weak(count, count + 1, Relaxed, Relaxed) {
            Ok(_) => return,
            Err(actual) => count = actual,
        }
    }
}

impl<T> Arc<T> {
    pub(super) fn new(memory: &Memory, value: T) -> Result<Self> {
        let layout = Layout::new::<Header<T>>();
        let charge = native_memory::reserve(memory, layout.size())?
            .expect("paid header requires original selected memory");
        // Header always contains counters and a charge, including for ZST T.
        let ptr = NonNull::new(unsafe { alloc(layout) }.cast::<Header<T>>())
            .ok_or_else(|| OutOfMemory::new(layout.size()))?;
        unsafe {
            ptr.as_ptr().write(Header {
                strong: AtomicUsize::new(1),
                weak: AtomicUsize::new(1),
                charge: ManuallyDrop::new(charge),
                value: ManuallyDrop::new(value),
            });
        }
        let owner = Self {
            ptr,
            _owned: PhantomData,
        };
        // Arm physical cleanup before a foreign confirmation may unwind.
        unsafe { (*ptr.as_ptr()).charge.allocated() };
        Ok(owner)
    }

    pub(super) fn as_ptr(this: &Self) -> *const T {
        // No reference to the enclosing header is formed here.
        unsafe { ptr::addr_of!((*this.ptr.as_ptr()).value).cast::<T>() }
    }

    pub(super) fn into_raw(this: Self) -> *const T {
        let this = ManuallyDrop::new(this);
        Self::as_ptr(&this)
    }

    /// Recover exactly one existing strong token from this private type.
    /// The pointer must originate in into_raw, or be a borrowed as_ptr token
    /// whose destruction is suppressed by the locked RawWaker adapter.
    pub(super) unsafe fn from_raw(value: *const T) -> Self {
        let ptr = unsafe {
            value
                .cast::<u8>()
                .sub(offset_of!(Header<T>, value))
                .cast_mut()
                .cast::<Header<T>>()
        };
        Self {
            ptr: unsafe { NonNull::new_unchecked(ptr) },
            _owned: PhantomData,
        }
    }

    pub(super) fn downgrade(this: &Self) -> Weak<T> {
        // A live strong token keeps both counters and T alive.
        increment(unsafe { &*ptr::addr_of!((*this.ptr.as_ptr()).weak) });
        Weak {
            ptr: Some(this.ptr),
            _owned: PhantomData,
        }
    }

    #[cfg(test)]
    pub(super) fn layout() -> Layout {
        Layout::new::<Header<T>>()
    }
}

impl<T> Clone for Arc<T> {
    fn clone(&self) -> Self {
        increment(unsafe { &*ptr::addr_of!((*self.ptr.as_ptr()).strong) });
        Self {
            ptr: self.ptr,
            _owned: PhantomData,
        }
    }
}

impl<T> Deref for Arc<T> {
    type Target = T;
    fn deref(&self) -> &T {
        // Only a live strong token exposes the payload.
        unsafe { &*Self::as_ptr(self) }
    }
}

impl<T> Weak<T> {
    pub(super) fn new() -> Self {
        Self {
            ptr: None,
            _owned: PhantomData,
        }
    }

    pub(super) fn upgrade(&self) -> Option<Arc<T>> {
        let ptr = self.ptr?;
        // The value may already have been destroyed. Access only the counter
        // through its raw field address, never &Header<T> or &T.
        let strong = unsafe { &*ptr::addr_of!((*ptr.as_ptr()).strong) };
        let mut count = strong.load(Relaxed);
        loop {
            if count == 0 {
                return None;
            }
            if count >= MAX_REFS {
                abort("private paid reference count overflow");
            }
            match strong.compare_exchange_weak(count, count + 1, Acquire, Relaxed) {
                Ok(_) => {
                    return Some(Arc {
                        ptr,
                        _owned: PhantomData,
                    });
                }
                Err(actual) => count = actual,
            }
        }
    }
}

impl<T> Clone for Weak<T> {
    fn clone(&self) -> Self {
        if let Some(ptr) = self.ptr {
            increment(unsafe { &*ptr::addr_of!((*ptr.as_ptr()).weak) });
        }
        Self {
            ptr: self.ptr,
            _owned: PhantomData,
        }
    }
}

// Safety: caller consumes one real weak token (or the implicit weak after
// successful last-strong destruction). No reference covers destroyed T.
unsafe fn release_weak<T>(ptr: NonNull<Header<T>>) {
    let weak = unsafe { &*ptr::addr_of!((*ptr.as_ptr()).weak) };
    if weak.fetch_sub(1, Release) == 1 {
        fence(Acquire);
        let charge = unsafe { ManuallyDrop::take(&mut *ptr::addr_of_mut!((*ptr.as_ptr()).charge)) };
        // SAME allocator and OWN complete layout. No Box<T> is reconstructed
        // around a previously destroyed value and no payload is moved again.
        unsafe { dealloc(ptr.as_ptr().cast::<u8>(), Layout::new::<Header<T>>()) };
        #[cfg(test)]
        super::tests::physical_deallocation(Layout::new::<Header<T>>().size());
        drop(charge);
    }
}

impl<T> Drop for Arc<T> {
    fn drop(&mut self) {
        let strong = unsafe { &*ptr::addr_of!((*self.ptr.as_ptr()).strong) };
        if strong.fetch_sub(1, Release) != 1 {
            return;
        }
        fence(Acquire);
        // If T unwinds, deliberately keep the implicit weak/header and SAME
        // charge. Never refund live or uncertain backing or add another owner.
        unsafe {
            ManuallyDrop::drop(&mut *ptr::addr_of_mut!((*self.ptr.as_ptr()).value));
            release_weak(self.ptr);
        }
    }
}

impl<T> Drop for Weak<T> {
    fn drop(&mut self) {
        if let Some(ptr) = self.ptr {
            unsafe { release_weak(ptr) };
        }
    }
}
