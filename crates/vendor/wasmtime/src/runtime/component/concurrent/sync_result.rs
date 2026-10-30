//! Same-budget ownership of only the sync-lowered host result Box.
//!
//! The reservation precedes the user poll. Its original owner then moves into
//! CalleeFinished, independently of the completed outer future's lifetime.
use super::LiftedResult;
use crate::runtime::native_memory::{self, Memory};
use crate::{NativeAllocation, Result};
use alloc::alloc::dealloc;
use alloc::boxed::Box;
use core::alloc::Layout;
use core::marker::PhantomData;
use core::mem::ManuallyDrop;
use core::ptr;

pub(super) struct PreparedSyncResult<R> {
    allocation: Option<Box<dyn NativeAllocation>>,
    _result: PhantomData<fn() -> R>,
}
impl<R: Send + Sync + 'static> PreparedSyncResult<R> {
    pub(super) fn new(memory: &Memory) -> Result<Self> {
        Ok(Self {
            allocation: native_memory::reserve(memory, Layout::new::<R>().size())?,
            _result: PhantomData,
        })
    }

    pub(super) fn finish(self, value: R) -> SyncResult {
        // Coercion erases this SAME Box; it creates no other allocation.
        let value: LiftedResult = Box::new(value);
        let Some(allocation) = self.allocation else {
            return SyncResult::legacy(value);
        };
        let mut owned = AccountedResult {
            value: ManuallyDrop::new(value),
            allocation: ManuallyDrop::new(allocation),
        };
        // Install actual Box cleanup before confirmation can unwind.
        owned.allocation.allocated();
        SyncResult(Kind::Accounted(owned))
    }
}

pub(super) struct SyncResult(Kind);
enum Kind {
    Legacy(LiftedResult),
    Accounted(AccountedResult),
}
struct AccountedResult {
    value: ManuallyDrop<LiftedResult>,
    allocation: ManuallyDrop<Box<dyn NativeAllocation>>,
}
impl SyncResult {
    pub(super) fn legacy(value: LiftedResult) -> Self {
        Self(Kind::Legacy(value))
    }

    pub(super) fn into_value<R: Send + Sync + 'static>(self) -> core::result::Result<R, Self> {
        match self.0 {
            Kind::Legacy(value) => match value.downcast::<R>() {
                Ok(value) => Ok(*value),
                Err(value) => Err(Self::legacy(value)),
            },
            Kind::Accounted(owned) => owned
                .into_value::<R>()
                .map_err(|owned| Self(Kind::Accounted(owned))),
        }
    }
}
impl AccountedResult {
    fn into_value<R: Send + Sync + 'static>(self) -> core::result::Result<R, Self> {
        // A wrong type retains the complete original erased Box/guard pair.
        if !self.value.is::<R>() {
            return Err(self);
        }
        let mut owned = ManuallyDrop::new(self);
        // SAFETY: the only private owner is consumed; take this field once and
        // suppress AccountedResult::drop until either rebuilding or deallocation.
        let value = unsafe { ManuallyDrop::take(&mut owned.value) };
        let value = match value.downcast::<R>() {
            Ok(value) => value,
            Err(value) => {
                // Keep even this unexpected safe-downcast failure conservative.
                // SAFETY: its unchanged guard has not been taken or dropped.
                let allocation = unsafe { ManuallyDrop::take(&mut owned.allocation) };
                return Err(Self {
                    value: ManuallyDrop::new(value),
                    allocation: ManuallyDrop::new(allocation),
                });
            }
        };
        let raw = Box::into_raw(value);
        let layout = Layout::new::<R>();
        // SAFETY: exact successful downcast of our sole fresh default-global
        // Box<R>. into_raw returns its initialized, nonnull, aligned pointer.
        // read moves R without running its destructor or retaining old ownership.
        // The matching nonzero global allocation is then destroyed exactly once;
        // no raw pointer escapes, and no access to old storage follows dealloc.
        let value = unsafe {
            let value = ptr::read(raw);
            if layout.size() != 0 {
                dealloc(raw.cast::<u8>(), layout);
            }
            value
        };
        // SAFETY: the SAME original guard remains initialized and alive through
        // the explicit deallocation above. Drop once, before returning live R.
        unsafe { ManuallyDrop::drop(&mut owned.allocation) };
        Ok(value)
    }
}
impl Drop for AccountedResult {
    fn drop(&mut self) {
        // SAFETY: each private field is destroyed once. Erased Box destruction
        // drops actual R and deallocates its backing BEFORE guard refund. If R
        // destruction unwinds, ManuallyDrop deliberately retains the guard.
        unsafe {
            ManuallyDrop::drop(&mut self.value);
            ManuallyDrop::drop(&mut self.allocation);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use alloc::format;
    use alloc::sync::Arc;
    use core::sync::atomic::{AtomicUsize, Ordering};
    use std::panic::{AssertUnwindSafe, catch_unwind};

    struct Probe {
        expected: usize,
        requests: AtomicUsize,
        live: AtomicUsize,
        confirmations: AtomicUsize,
        owners_dropped: AtomicUsize,
        factories_dropped: AtomicUsize,
        created: AtomicUsize,
        values_dropped: AtomicUsize,
        events: AtomicUsize,
        value_event: AtomicUsize,
        owner_event: AtomicUsize,
    }
    impl Probe {
        fn new(expected: usize) -> Arc<Self> {
            Arc::new(Self {
                expected,
                requests: AtomicUsize::new(0),
                live: AtomicUsize::new(0),
                confirmations: AtomicUsize::new(0),
                owners_dropped: AtomicUsize::new(0),
                factories_dropped: AtomicUsize::new(0),
                created: AtomicUsize::new(0),
                values_dropped: AtomicUsize::new(0),
                events: AtomicUsize::new(0),
                value_event: AtomicUsize::new(0),
                owner_event: AtomicUsize::new(0),
            })
        }
    }
    struct Owner {
        probe: Arc<Probe>,
        panic_confirmation: bool,
    }
    impl NativeAllocation for Owner {
        fn allocated(&mut self) {
            self.probe.confirmations.fetch_add(1, Ordering::SeqCst);
            assert!(!self.panic_confirmation, "sync-result-confirmation-control");
        }
    }
    impl Drop for Owner {
        fn drop(&mut self) {
            self.probe.owner_event.store(
                self.probe.events.fetch_add(1, Ordering::SeqCst) + 1,
                Ordering::SeqCst,
            );
            assert_eq!(self.probe.live.fetch_sub(1, Ordering::SeqCst), 1);
            assert_eq!(self.probe.owners_dropped.fetch_add(1, Ordering::SeqCst), 0);
        }
    }
    struct Factory {
        probe: Arc<Probe>,
        refuse: bool,
        panic_confirmation: bool,
    }
    impl crate::NativeMemory for Factory {
        fn reserve(&self, bytes: usize) -> Result<Box<dyn NativeAllocation>> {
            assert_eq!(bytes, self.probe.expected);
            self.probe.requests.fetch_add(1, Ordering::SeqCst);
            if self.refuse {
                crate::bail!("original-sync-result-refusal-control");
            }
            assert_eq!(self.probe.live.fetch_add(1, Ordering::SeqCst), 0);
            Ok(Box::new(Owner {
                probe: self.probe.clone(),
                panic_confirmation: self.panic_confirmation,
            }))
        }
    }
    impl Drop for Factory {
        fn drop(&mut self) {
            self.probe.factories_dropped.fetch_add(1, Ordering::SeqCst);
        }
    }
    fn memory(probe: &Arc<Probe>, refuse: bool, panic_confirmation: bool) -> Memory {
        Some(Arc::new(Factory {
            probe: probe.clone(),
            refuse,
            panic_confirmation,
        }))
    }

    #[repr(align(128))]
    struct Value {
        probe: Arc<Probe>,
        number: u32,
        panic_drop: bool,
    }
    impl Value {
        fn new(probe: &Arc<Probe>, panic_drop: bool) -> Self {
            probe.created.fetch_add(1, Ordering::SeqCst);
            Self {
                probe: probe.clone(),
                number: 42,
                panic_drop,
            }
        }
    }
    impl Drop for Value {
        fn drop(&mut self) {
            self.probe.value_event.store(
                self.probe.events.fetch_add(1, Ordering::SeqCst) + 1,
                Ordering::SeqCst,
            );
            assert_eq!(self.probe.values_dropped.fetch_add(1, Ordering::SeqCst), 0);
            assert!(!self.panic_drop, "sync-result-destructor-control");
        }
    }
    fn extract<R: Send + Sync + 'static>(value: SyncResult) -> R {
        match value.into_value::<R>() {
            Ok(value) => value,
            Err(_) => panic!("actual result type mismatch"),
        }
    }

    #[test]
    fn sync_result_refuses_before_value_and_unbuilt_reservation_refunds() {
        let probe = Probe::new(Layout::new::<Value>().size());
        let refused = PreparedSyncResult::<Value>::new(&memory(&probe, true, false));
        let error = refused.err().expect("original refusal");
        assert!(format!("{error:#}").contains("original-sync-result-refusal-control"));
        assert_eq!(probe.requests.load(Ordering::SeqCst), 1);
        assert_eq!(probe.created.load(Ordering::SeqCst), 0);
        assert_eq!(probe.live.load(Ordering::SeqCst), 0);
        assert_eq!(probe.confirmations.load(Ordering::SeqCst), 0);

        let probe = Probe::new(Layout::new::<Value>().size());
        let source = memory(&probe, false, false);
        let prepared = PreparedSyncResult::<Value>::new(&source).unwrap();
        drop(source);
        assert_eq!(probe.factories_dropped.load(Ordering::SeqCst), 1);
        assert_eq!(probe.live.load(Ordering::SeqCst), 1);
        drop(prepared);
        assert_eq!(probe.created.load(Ordering::SeqCst), 0);
        assert_eq!(probe.confirmations.load(Ordering::SeqCst), 0);
        assert_eq!(probe.owners_dropped.load(Ordering::SeqCst), 1);
        assert_eq!(probe.live.load(Ordering::SeqCst), 0);
    }

    #[test]
    fn sync_result_overaligned_move_out_refunds_before_returned_value_drop() {
        let probe = Probe::new(Layout::new::<Value>().size());
        let prepared = PreparedSyncResult::<Value>::new(&memory(&probe, false, false)).unwrap();
        assert_eq!(probe.factories_dropped.load(Ordering::SeqCst), 1);
        let owned = prepared.finish(Value::new(&probe, false));
        match &owned.0 {
            Kind::Accounted(value) => {
                let pointer =
                    value.value.as_ref() as *const (dyn core::any::Any + Send + Sync) as *const ();
                assert_eq!((pointer as usize) % Layout::new::<Value>().align(), 0);
            }
            Kind::Legacy(_) => panic!("paid nonzero result expected"),
        }
        assert_eq!(probe.live.load(Ordering::SeqCst), 1);
        let value = extract::<Value>(owned);
        assert_eq!(value.number, 42);
        assert_eq!(probe.confirmations.load(Ordering::SeqCst), 1);
        assert_eq!(probe.owners_dropped.load(Ordering::SeqCst), 1);
        assert_eq!(probe.live.load(Ordering::SeqCst), 0);
        assert_eq!(probe.values_dropped.load(Ordering::SeqCst), 0);
        drop(value);
        assert_eq!(probe.values_dropped.load(Ordering::SeqCst), 1);
        assert!(
            probe.owner_event.load(Ordering::SeqCst) < probe.value_event.load(Ordering::SeqCst)
        );
    }

    #[test]
    fn sync_result_wrong_type_preserves_envelope_and_abandon_drops_value_before_owner() {
        let probe = Probe::new(Layout::new::<Value>().size());
        let result = PreparedSyncResult::<Value>::new(&memory(&probe, false, false))
            .unwrap()
            .finish(Value::new(&probe, false));
        let result = match result.into_value::<u64>() {
            Err(result) => result,
            Ok(_) => panic!("wrong downcast unexpectedly succeeded"),
        };
        assert_eq!(probe.live.load(Ordering::SeqCst), 1);
        assert_eq!(probe.values_dropped.load(Ordering::SeqCst), 0);
        assert_eq!(probe.owners_dropped.load(Ordering::SeqCst), 0);
        drop(result);
        assert_eq!(probe.live.load(Ordering::SeqCst), 0);
        assert_eq!(probe.values_dropped.load(Ordering::SeqCst), 1);
        assert_eq!(probe.owners_dropped.load(Ordering::SeqCst), 1);
        assert!(
            probe.value_event.load(Ordering::SeqCst) < probe.owner_event.load(Ordering::SeqCst)
        );
    }

    #[test]
    fn sync_result_confirmation_unwind_has_installed_physical_cleanup() {
        let probe = Probe::new(Layout::new::<Value>().size());
        let prepared = PreparedSyncResult::<Value>::new(&memory(&probe, false, true)).unwrap();
        assert!(
            catch_unwind(AssertUnwindSafe(
                || prepared.finish(Value::new(&probe, false))
            ))
            .is_err()
        );
        assert_eq!(probe.confirmations.load(Ordering::SeqCst), 1);
        assert_eq!(probe.values_dropped.load(Ordering::SeqCst), 1);
        assert_eq!(probe.owners_dropped.load(Ordering::SeqCst), 1);
        assert_eq!(probe.live.load(Ordering::SeqCst), 0);
        assert!(
            probe.value_event.load(Ordering::SeqCst) < probe.owner_event.load(Ordering::SeqCst)
        );
    }

    #[test]
    fn sync_result_destructor_unwind_retains_same_original_charge() {
        let probe = Probe::new(Layout::new::<Value>().size());
        let result = PreparedSyncResult::<Value>::new(&memory(&probe, false, false))
            .unwrap()
            .finish(Value::new(&probe, true));
        assert!(catch_unwind(AssertUnwindSafe(|| drop(result))).is_err());
        assert_eq!(probe.values_dropped.load(Ordering::SeqCst), 1);
        assert_eq!(probe.owners_dropped.load(Ordering::SeqCst), 0);
        assert_eq!(probe.live.load(Ordering::SeqCst), 1);
        assert_eq!(probe.confirmations.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn sync_result_zst_and_none_keep_legacy_boxes_without_native_admission() {
        static ZERO_DROPS: AtomicUsize = AtomicUsize::new(0);
        #[repr(align(64))]
        struct Zero;
        impl Drop for Zero {
            fn drop(&mut self) {
                ZERO_DROPS.fetch_add(1, Ordering::SeqCst);
            }
        }
        assert_eq!(Layout::new::<Zero>().size(), 0);
        let probe = Probe::new(0);
        let source = memory(&probe, false, false);
        let prepared = PreparedSyncResult::<Zero>::new(&source).unwrap();
        assert_eq!(probe.requests.load(Ordering::SeqCst), 0);
        let result = prepared.finish(Zero);
        assert!(matches!(&result.0, Kind::Legacy(_)));
        let value = extract::<Zero>(result);
        assert_eq!(ZERO_DROPS.load(Ordering::SeqCst), 0);
        drop(value);
        assert_eq!(ZERO_DROPS.load(Ordering::SeqCst), 1);
        drop(
            PreparedSyncResult::<Zero>::new(&source)
                .unwrap()
                .finish(Zero),
        );
        assert_eq!(ZERO_DROPS.load(Ordering::SeqCst), 2);
        assert_eq!(probe.requests.load(Ordering::SeqCst), 0);
        assert_eq!(probe.owners_dropped.load(Ordering::SeqCst), 0);

        let probe = Probe::new(Layout::new::<Value>().size());
        let result = PreparedSyncResult::<Value>::new(&None)
            .unwrap()
            .finish(Value::new(&probe, false));
        assert!(matches!(&result.0, Kind::Legacy(_)));
        assert_eq!(extract::<Value>(result).number, 42);
        assert_eq!(probe.requests.load(Ordering::SeqCst), 0);
        assert_eq!(probe.values_dropped.load(Ordering::SeqCst), 1);
        assert_eq!(probe.owners_dropped.load(Ordering::SeqCst), 0);
    }
}
