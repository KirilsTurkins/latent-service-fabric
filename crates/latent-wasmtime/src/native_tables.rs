//! Original activation ownership follows actual Wasmtime table allocations.
use latent_core::{ActivationBudget, HostMemoryReservation};

// No guest callbacks, Weak handles, custom destructor or returned self-Arc.
// Every allocation guard captures the original ledger directly, not this
// factory; the paid binding's private clones are confined to engine containers.
struct Factory {
    budget: ActivationBudget,
    #[cfg(feature = "rust-thread-trap-diagnostic")]
    observer: Option<fn(&wasmtime::AsyncDeadlockSnapshot)>,
    #[cfg(feature = "rust-thread-trap-diagnostic")]
    observed: core::sync::atomic::AtomicBool,
    #[cfg(feature = "rust-thread-trap-diagnostic")]
    root: RootRecord,
}

impl wasmtime::NativeMemory for Factory {
    fn reserve(&self, bytes: usize) -> wasmtime::Result<Box<dyn wasmtime::NativeAllocation>> {
        Ok(reserve(&self.budget, bytes)?.expect("native factory requests nonzero backing"))
    }

    #[cfg(feature = "rust-thread-trap-diagnostic")]
    fn root_suspension_enabled(&self) -> bool {
        self.observer.is_some() && !self.observed.load(core::sync::atomic::Ordering::Relaxed)
    }

    #[cfg(feature = "rust-thread-trap-diagnostic")]
    fn save_root_suspension(&self, snapshot: &wasmtime::RootSuspensionSnapshot) {
        if !self.root_suspension_enabled() {
            return;
        }
        self.root.save(snapshot);
    }

    #[cfg(feature = "rust-thread-trap-diagnostic")]
    fn async_deadlock_observer(&self) -> Option<fn(&wasmtime::AsyncDeadlockSnapshot)> {
        self.observer.filter(|_| {
            if self
                .observed
                .swap(true, core::sync::atomic::Ordering::Relaxed)
            {
                return false;
            }
            crate::rust_thread_fault::record_root_suspension(&self.root.snapshot());
            true
        })
    }
}

#[cfg(feature = "rust-thread-trap-diagnostic")]
#[derive(Default)]
struct RootRecord {
    value: std::sync::Mutex<Option<wasmtime::RootSuspensionSnapshot>>,
    failed: core::sync::atomic::AtomicBool,
}

#[cfg(feature = "rust-thread-trap-diagnostic")]
const _: () = assert!(size_of::<RootRecord>() <= 256);

#[cfg(feature = "rust-thread-trap-diagnostic")]
impl RootRecord {
    fn save(&self, snapshot: &wasmtime::RootSuspensionSnapshot) {
        match self.value.try_lock() {
            Ok(mut value) => {
                *value = Some(*snapshot);
                self.failed
                    .store(false, core::sync::atomic::Ordering::Relaxed);
            }
            Err(_) => self
                .failed
                .store(true, core::sync::atomic::Ordering::Relaxed),
        }
    }

    fn snapshot(&self) -> wasmtime::RootSuspensionSnapshot {
        let unavailable = |flags| wasmtime::RootSuspensionSnapshot {
            flags,
            ..wasmtime::RootSuspensionSnapshot::default()
        };
        if self.failed.load(core::sync::atomic::Ordering::Relaxed) {
            // An older successful record cannot stand in for a failed LAST write.
            return unavailable(32);
        }
        match self.value.try_lock() {
            Ok(value) => value.unwrap_or_else(|| unavailable(64)),
            Err(_) => unavailable(32),
        }
    }
}

#[cfg(all(test, feature = "rust-thread-trap-diagnostic"))]
pub(crate) fn assert_root_suspension_transfer_controls() {
    let record = RootRecord::default();
    assert_eq!(record.snapshot().flags, 64);
    let mut first = wasmtime::RootSuspensionSnapshot::default();
    first.steps = 1;
    record.save(&first);
    assert_eq!(record.snapshot(), first);
    let held = record.value.try_lock().unwrap();
    // A contended read and a failed LAST write return, never block or reuse old.
    assert_eq!(record.snapshot().flags, 32);
    let second = wasmtime::RootSuspensionSnapshot { steps: 2, ..first };
    record.save(&second);
    drop(held);
    let missing = record.snapshot();
    assert_eq!((missing.flags, missing.count, missing.visited), (32, 0, 0));
    record.save(&second);
    assert_eq!(record.snapshot(), second);
}

pub(crate) fn binding(
    budget: &ActivationBudget,
) -> wasmtime::Result<wasmtime::NativeMemoryBinding> {
    #[cfg(feature = "rust-thread-trap-diagnostic")]
    return binding_with_observer(budget, None);
    #[cfg(not(feature = "rust-thread-trap-diagnostic"))]
    binding_inner(budget)
}

#[cfg(feature = "rust-thread-trap-diagnostic")]
pub(crate) fn binding_with_observer(
    budget: &ActivationBudget,
    observer: Option<fn(&wasmtime::AsyncDeadlockSnapshot)>,
) -> wasmtime::Result<wasmtime::NativeMemoryBinding> {
    binding_inner(budget, observer)
}

fn binding_inner(
    budget: &ActivationBudget,
    #[cfg(feature = "rust-thread-trap-diagnostic")] observer: Option<
        fn(&wasmtime::AsyncDeadlockSnapshot),
    >,
) -> wasmtime::Result<wasmtime::NativeMemoryBinding> {
    // Exact diagnostic Factory layout, including its optional function pointer,
    // is admitted before Arc::new; no extra native owner or ledger is created.
    let size = wasmtime::NativeMemoryBinding::allocation_size::<Factory>();
    let owner = reserve(budget, size)?.expect("factory Arc has a nonzero allocation layout");
    Ok(wasmtime::NativeMemoryBinding::new(
        Factory {
            budget: budget.clone(),
            #[cfg(feature = "rust-thread-trap-diagnostic")]
            observer,
            #[cfg(feature = "rust-thread-trap-diagnostic")]
            observed: core::sync::atomic::AtomicBool::new(false),
            #[cfg(feature = "rust-thread-trap-diagnostic")]
            root: RootRecord::default(),
        },
        owner,
    ))
}

struct Allocation {
    memory: HostMemoryReservation,
}

// Includes original backing allocation bookkeeping and the finite boxed owner.
// It is a conservative bound, not a renderer/allocator retained-byte sensor.
pub(crate) const OWNER_ESCROW: usize = 256;
const ALLOCATOR_BOOKKEEPING: usize = 64;
const _: () = assert!(size_of::<Allocation>() + 2 * ALLOCATOR_BOOKKEEPING <= OWNER_ESCROW);

impl wasmtime::TableAllocation for Allocation {
    fn allocated(&mut self) {
        self.memory.confirm();
    }
}

pub(crate) fn reserve(
    budget: &ActivationBudget,
    bytes: usize,
) -> wasmtime::Result<Option<Box<dyn wasmtime::TableAllocation>>> {
    if bytes == 0 {
        return Ok(None);
    }
    let total = bytes
        .checked_add(OWNER_ESCROW)
        .and_then(|n| u64::try_from(n).ok())
        .ok_or_else(|| wasmtime::Error::msg("native-table-allocation-overflow"))?;
    let memory = budget
        .reserve_host_memory(total)
        .map_err(wasmtime::Error::new)?;
    let mut owner = Box::new(Allocation { memory });
    // Only the fixed owner has been created. Backing is confirmed by Wasmtime
    // after successful allocation, while the original full reservation is live.
    owner.memory.confirm_bytes(OWNER_ESCROW as u64);
    Ok(Some(owner))
}
