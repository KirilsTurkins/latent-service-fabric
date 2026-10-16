//! Actual native stack allocation owns its original activation reservation.
//!
//! The first profile admits one root stack before Store fuel initialization.
//! It deliberately rejects any additional allocation: explicit canonical thread
//! creation stays closed until pre-start metadata and continuation admission exist.
#![allow(unsafe_code)]

use std::cell::RefCell;
use std::future::Future;
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll};

use latent_core::activation_runtime::{ActivationRuntime, OwnerKind, RuntimeOwner};
use latent_core::{ActivationBudget, HostMemoryReservation, PlatformError, PlatformErrorCode};

mod children;
pub(crate) use children::Child;

thread_local! {
    // Only an internal Future poll installs this allocation context. It carries
    // the original ledger, not a process-global quota or an application grant.
    static CURRENT: RefCell<Option<Arc<StackContext>>> = const { RefCell::new(None) };
}

struct Permit {
    _owner: RuntimeOwner,
    #[cfg_attr(
        not(all(target_os = "linux", target_arch = "x86_64")),
        allow(dead_code)
    )]
    memory: HostMemoryReservation,
    #[cfg_attr(
        not(all(target_os = "linux", target_arch = "x86_64")),
        allow(dead_code)
    )]
    child: Option<Arc<Child>>,
}

pub(crate) struct StackContext {
    budget: ActivationBudget,
    runtime: ActivationRuntime,
    root: Mutex<Option<Permit>>,
    children: Mutex<children::Children>,
    size: usize,
    #[cfg_attr(
        not(all(target_os = "linux", target_arch = "x86_64")),
        allow(dead_code)
    )]
    mapped: usize,
    active: AtomicU32,
    finalization_requested: AtomicBool,
    retirement_failed: AtomicBool,
    _metadata: HostMemoryReservation,
}

impl StackContext {
    pub(crate) fn new(
        budget: ActivationBudget,
        runtime: ActivationRuntime,
        size: usize,
    ) -> Result<Arc<Self>, PlatformError> {
        Self::with_children(budget, runtime, size, 0)
    }

    pub(crate) fn with_children(
        budget: ActivationBudget,
        runtime: ActivationRuntime,
        size: usize,
        maximum_children: usize,
    ) -> Result<Arc<Self>, PlatformError> {
        if maximum_children > 8191 {
            return Err(failure("native-child-table-bound"));
        }
        let mapped = mapping_size(size)?;
        // These are the existing authoritative Native ceiling and memory ledger.
        // Admission occurs before allocating the context or native mapping.
        let owner = runtime.register(OwnerKind::Native, None)?;
        let memory = budget
            .reserve_host_memory(mapped as u64)
            .map_err(|e| e.to_platform_error())?;
        let mut metadata = budget
            .reserve_host_memory(
                (std::mem::size_of::<Self>()
                    + 64
                    + maximum_children * std::mem::size_of::<Arc<Child>>()) as u64,
            )
            .map_err(|e| e.to_platform_error())?;
        let children = children::Children::new(maximum_children)?;
        metadata.confirm();
        Ok(Arc::new(Self {
            budget,
            runtime,
            root: Mutex::new(Some(Permit {
                _owner: owner,
                memory,
                child: None,
            })),
            children: Mutex::new(children),
            size,
            mapped,
            active: AtomicU32::new(0),
            finalization_requested: AtomicBool::new(false),
            retirement_failed: AtomicBool::new(false),
            _metadata: metadata,
        }))
    }

    pub(crate) fn finish_logical(&self) -> Result<(), PlatformError> {
        // A permit which never allocated a stack has no physical work to await.
        drop(
            self.root
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .take(),
        );
        let owners = self.runtime.snapshot().owners;
        if owners[..6].iter().any(|n| *n != 0) || owners[6] != self.active.load(Ordering::Acquire) {
            return Err(failure("native-stack-logical-owners-unretired"));
        }
        self.finalization_requested.store(true, Ordering::Release);
        self.try_retire();
        Ok(())
    }

    pub(crate) fn cancel_unstarted(&self) {
        drop(
            self.root
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .take(),
        );
        drop(
            self.children
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .pending
                .take(),
        );
    }

    fn try_retire(&self) {
        if self.finalization_requested.load(Ordering::Acquire)
            && self.active.load(Ordering::Acquire) == 0
            && self.runtime.retire().is_err()
        {
            self.retirement_failed.store(true, Ordering::Release);
        }
    }

    pub(crate) fn physically_retired(&self) -> bool {
        self.active.load(Ordering::Acquire) == 0
            && self
                .root
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .is_none()
            && !self.retirement_failed.load(Ordering::Acquire)
    }
}

fn failure(reason: &'static str) -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::Internal,
        message: reason.into(),
        retryable: false,
        details: vec![],
    }
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn mapping_size(size: usize) -> Result<usize, PlatformError> {
    let page = rustix::param::page_size();
    size.checked_add(page - 1)
        .map(|n| n / page * page)
        .and_then(|n| n.checked_add(page))
        .filter(|n| size != 0 && *n <= 128 * 1024 * 1024 + page)
        .ok_or_else(|| failure("native-stack-size"))
}

#[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
fn mapping_size(_size: usize) -> Result<usize, PlatformError> {
    Err(failure("native-stack-platform"))
}

pub(crate) struct Creator;

// SAFETY: the sole implementation below owns a private page-aligned anonymous
// mapping with an inaccessible guard page. Only Wasmtime receives its addresses.
unsafe impl wasmtime::StackCreator for Creator {
    fn new_stack(
        &self,
        size: usize,
        _zeroed: bool,
    ) -> wasmtime::Result<Box<dyn wasmtime::StackMemory>> {
        let context = CURRENT
            .with(|slot| slot.borrow().clone())
            .ok_or_else(|| wasmtime::Error::msg("native-stack-owner-required"))?;
        if size != context.size {
            return Err(wasmtime::Error::msg("native-stack-size-mismatch"));
        }
        let permit = context
            .root
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .take()
            .or_else(|| {
                context
                    .children
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .pending
                    .take()
            })
            .ok_or_else(|| wasmtime::Error::msg("native-stack-prestart-admission-required"))?;
        #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
        {
            Ok(Box::new(Mapping::new(context, permit)?))
        }
        #[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
        {
            drop(permit);
            Err(wasmtime::Error::msg("native-stack-platform"))
        }
    }
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
struct Mapping {
    base: usize,
    context: Arc<StackContext>,
    permit: Option<Permit>,
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
impl Mapping {
    fn new(context: Arc<StackContext>, mut permit: Permit) -> wasmtime::Result<Self> {
        use rustix::mm::{MapFlags, MprotectFlags, ProtFlags};
        let page = rustix::param::page_size();
        // SAFETY: nonzero bounded length, anonymous private mapping, no requested
        // fixed address. Kernel anonymous pages are initially zero filled.
        let base = unsafe {
            rustix::mm::mmap_anonymous(
                std::ptr::null_mut(),
                context.mapped,
                ProtFlags::empty(),
                MapFlags::PRIVATE,
            )
        }?;
        // Establish ownership before protection can fail, so Drop unmaps on error.
        let mut stack = Self {
            base: base as usize,
            context,
            permit: None,
        };
        permit.memory.confirm();
        if let Some(child) = &permit.child {
            child.mapped();
        }
        // SAFETY: this page-aligned subrange belongs to the new mapping. Its first
        // page remains inaccessible and its remaining pages are private stack data.
        if let Err(error) = unsafe {
            rustix::mm::mprotect(
                base.cast::<u8>().add(page).cast(),
                stack.context.mapped - page,
                MprotectFlags::READ | MprotectFlags::WRITE,
            )
        } {
            // Drop must retain the original permit if unmapping cannot be proved.
            stack.permit = Some(permit);
            stack.context.active.fetch_add(1, Ordering::AcqRel);
            return Err(error.into());
        }
        stack.permit = Some(permit);
        stack.context.active.fetch_add(1, Ordering::AcqRel);
        Ok(stack)
    }
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
// SAFETY: range/top describe only the usable page-aligned stack. The first page
// remains PROT_NONE throughout its lifetime. No other owner reads/writes it.
unsafe impl wasmtime::StackMemory for Mapping {
    fn top(&self) -> *mut u8 {
        (self.base + self.context.mapped) as *mut u8
    }
    fn range(&self) -> std::ops::Range<usize> {
        self.base + rustix::param::page_size()..self.base + self.context.mapped
    }
    fn guard_range(&self) -> std::ops::Range<*mut u8> {
        self.base as *mut u8..(self.base + rustix::param::page_size()) as *mut u8
    }
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
impl Drop for Mapping {
    fn drop(&mut self) {
        // SAFETY: exactly the original mapping, owned solely by this value.
        if unsafe { rustix::mm::munmap(self.base as *mut _, self.context.mapped) }.is_err() {
            self.context
                .retirement_failed
                .store(true, Ordering::Release);
            if let Some(permit) = self.permit.take() {
                if let Some(child) = &permit.child {
                    child.uncertain();
                }
                // Keep actual uncertain native capacity charged and quarantine.
                std::mem::forget(permit);
            }
            return;
        }
        let child = self.permit.as_ref().and_then(|permit| permit.child.clone());
        drop(self.permit.take());
        if let Some(child) = child {
            child.unmapped();
        }
        self.context.active.fetch_sub(1, Ordering::AcqRel);
        self.context.try_retire();
    }
}

struct PollGuard(Option<Arc<StackContext>>);
impl PollGuard {
    fn enter(context: &Arc<StackContext>) -> Self {
        Self(CURRENT.with(|slot| slot.replace(Some(Arc::clone(context)))))
    }
}
impl Drop for PollGuard {
    fn drop(&mut self) {
        CURRENT.with(|slot| slot.replace(self.0.take()));
    }
}

pub(crate) struct Scoped<F> {
    future: Pin<Box<F>>,
    context: Arc<StackContext>,
    _allocation: HostMemoryReservation,
}
pub(crate) fn scoped<F: Future>(
    context: Arc<StackContext>,
    future: F,
) -> Result<Scoped<F>, PlatformError> {
    let mut allocation = context
        .budget
        .reserve_host_memory((std::mem::size_of::<F>() + 64) as u64)
        .map_err(|e| e.to_platform_error())?;
    let future = Box::pin(future);
    allocation.confirm();
    Ok(Scoped {
        future,
        context,
        _allocation: allocation,
    })
}
impl<F: Future> Future for Scoped<F> {
    type Output = F::Output;
    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.get_mut();
        let _guard = PollGuard::enter(&this.context);
        this.future.as_mut().poll(cx)
    }
}

#[cfg(test)]
mod tests;
