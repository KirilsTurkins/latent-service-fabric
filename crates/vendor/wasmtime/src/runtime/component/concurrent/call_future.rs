//! Backing for the abortable async-import future before its first poll.
//!
//! The native owner is outside the pinned Box: completion does not release
//! backing, and the future and its allocation die before the original credit.
//! Other scheduler boxes, queues and transitive captures remain separate.

use crate::runtime::native_memory::{self, Memory};
use crate::{NativeAllocation, Result};
use alloc::boxed::Box;
use core::alloc::Layout;
use core::future::Future;
use core::mem::ManuallyDrop;
use core::pin::Pin;
use core::task::{Context, Poll};

pub(super) enum CallFuture<F> {
    Legacy(Pin<Box<F>>),
    Accounted(AccountedFuture<F>),
}

pub(super) struct AccountedFuture<F> {
    future: ManuallyDrop<Pin<Box<F>>>,
    allocation: ManuallyDrop<Box<dyn NativeAllocation>>,
}

impl<F> CallFuture<F> {
    pub(super) fn new(memory: &Memory, future: F) -> Result<Self> {
        // The concrete abortable future type is still known here. Pin adds
        // no allocation. A zero-sized Box has no backing to account.
        let Some(allocation) = native_memory::reserve(memory, Layout::new::<F>().size())? else {
            return Ok(Self::Legacy(Box::pin(future)));
        };
        let mut owner = AccountedFuture {
            future: ManuallyDrop::new(Box::pin(future)),
            allocation: ManuallyDrop::new(allocation),
        };
        // Install the destructor before confirming allocation, so even an
        // unwinding confirmation follows physical destruction before refund.
        owner.allocation.allocated();
        Ok(Self::Accounted(owner))
    }
}

impl<F: Future> Future for CallFuture<F> {
    type Output = F::Output;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        // Moving a Box pointer never moves its pinned F, including !Unpin F.
        match self.get_mut() {
            Self::Legacy(future) => future.as_mut().poll(cx),
            Self::Accounted(owner) => owner.future.as_mut().poll(cx),
        }
    }
}

impl<F> Drop for AccountedFuture<F> {
    fn drop(&mut self) {
        // SAFETY: these fields have one private owner and are dropped once in
        // order. Box destruction also deallocates the concrete F storage.
        // If F's destructor unwinds, deliberately retain uncertain credit.
        unsafe {
            ManuallyDrop::drop(&mut self.future);
            ManuallyDrop::drop(&mut self.allocation);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use alloc::sync::Arc;
    use core::marker::PhantomPinned;
    use core::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
    use core::task::Waker;
    use std::panic::{AssertUnwindSafe, catch_unwind};

    #[derive(Default)]
    struct Probe {
        live: AtomicUsize,
        requests: AtomicUsize,
        polls: AtomicUsize,
        state_dropped: AtomicBool,
        owner_dropped: AtomicBool,
        address: AtomicUsize,
    }

    struct MemoryOwner {
        probe: Arc<Probe>,
        panic_confirmation: bool,
    }
    impl NativeAllocation for MemoryOwner {
        fn allocated(&mut self) {
            assert!(!self.panic_confirmation, "confirmation-control");
        }
    }
    impl Drop for MemoryOwner {
        fn drop(&mut self) {
            assert!(self.probe.state_dropped.load(Ordering::SeqCst));
            assert_eq!(self.probe.live.fetch_sub(1, Ordering::SeqCst), 1);
            assert!(!self.probe.owner_dropped.swap(true, Ordering::SeqCst));
        }
    }
    struct Memory {
        probe: Arc<Probe>,
        refuse: bool,
        panic_confirmation: bool,
    }
    impl crate::NativeMemory for Memory {
        fn reserve(&self, bytes: usize) -> Result<Box<dyn NativeAllocation>> {
            assert_eq!(bytes, Layout::new::<TestFuture>().size());
            self.probe.requests.fetch_add(1, Ordering::SeqCst);
            if self.refuse {
                crate::bail!("original-refusal-control");
            }
            assert_eq!(self.probe.live.fetch_add(1, Ordering::SeqCst), 0);
            Ok(Box::new(MemoryOwner {
                probe: self.probe.clone(),
                panic_confirmation: self.panic_confirmation,
            }))
        }
    }
    struct TestFuture {
        probe: Arc<Probe>,
        ready: bool,
        panic_drop: bool,
        selected: bool,
        _pinned: PhantomPinned,
    }
    impl Future for TestFuture {
        type Output = u32;
        fn poll(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<u32> {
            let this = self.get_ref_for_test();
            this.probe.polls.fetch_add(1, Ordering::SeqCst);
            let address = this as *const Self as usize;
            let prior = this.probe.address.swap(address, Ordering::SeqCst);
            assert!(prior == 0 || prior == address);
            if this.selected {
                assert_eq!(this.probe.live.load(Ordering::SeqCst), 1);
            }
            if this.ready {
                Poll::Ready(42)
            } else {
                Poll::Pending
            }
        }
    }
    impl TestFuture {
        fn get_ref_for_test(self: Pin<&mut Self>) -> &Self {
            self.into_ref().get_ref()
        }
    }
    impl Drop for TestFuture {
        fn drop(&mut self) {
            if self.selected
                && self.probe.requests.load(Ordering::SeqCst) != 0
                && self.probe.live.load(Ordering::SeqCst) != 0
            {
                assert_eq!(self.probe.live.load(Ordering::SeqCst), 1);
                assert!(!self.probe.owner_dropped.load(Ordering::SeqCst));
            }
            self.probe.state_dropped.store(true, Ordering::SeqCst);
            assert!(!self.panic_drop, "destructor-control");
        }
    }
    fn future(probe: &Arc<Probe>, ready: bool, panic_drop: bool, selected: bool) -> TestFuture {
        TestFuture {
            probe: probe.clone(),
            ready,
            panic_drop,
            selected,
            _pinned: PhantomPinned,
        }
    }
    fn memory(probe: &Arc<Probe>, refuse: bool, panic_confirmation: bool) -> native_memory::Memory {
        Some(Arc::new(Memory {
            probe: probe.clone(),
            refuse,
            panic_confirmation,
        }))
    }
    fn poll(future: &mut CallFuture<TestFuture>) -> Poll<u32> {
        Pin::new(future).poll(&mut Context::from_waker(Waker::noop()))
    }

    #[test]
    fn call_future_refuses_before_first_poll_and_none_preserves_legacy_box() {
        let probe = Arc::new(Probe::default());
        let result = CallFuture::new(
            &memory(&probe, true, false),
            future(&probe, true, false, true),
        );
        assert!(result.is_err());
        assert_eq!(probe.requests.load(Ordering::SeqCst), 1);
        assert_eq!(probe.polls.load(Ordering::SeqCst), 0);
        assert_eq!(probe.live.load(Ordering::SeqCst), 0);
        assert!(probe.state_dropped.load(Ordering::SeqCst));
        let probe = Arc::new(Probe::default());
        let mut task = CallFuture::new(&None, future(&probe, true, false, false)).unwrap();
        assert!(matches!(&task, CallFuture::Legacy(_)));
        assert_eq!(poll(&mut task), Poll::Ready(42));
        drop(task);
        assert_eq!(probe.requests.load(Ordering::SeqCst), 0);
        assert!(probe.state_dropped.load(Ordering::SeqCst));
    }

    #[test]
    fn call_future_pending_completion_and_cancel_keep_charge_until_drop() {
        for ready in [false, true] {
            let probe = Arc::new(Probe::default());
            let mut task = CallFuture::new(
                &memory(&probe, false, false),
                future(&probe, ready, false, true),
            )
            .unwrap();
            for _ in 0..2 {
                assert_eq!(
                    poll(&mut task),
                    if ready {
                        Poll::Ready(42)
                    } else {
                        Poll::Pending
                    }
                );
                assert_eq!(probe.live.load(Ordering::SeqCst), 1);
                assert!(!probe.state_dropped.load(Ordering::SeqCst));
            }
            drop(task);
            assert_eq!(probe.live.load(Ordering::SeqCst), 0);
            assert!(probe.owner_dropped.load(Ordering::SeqCst));
        }
    }

    #[test]
    fn call_future_confirmation_unwind_destroys_state_before_refund() {
        let probe = Arc::new(Probe::default());
        assert!(
            catch_unwind(AssertUnwindSafe(|| {
                let _ = CallFuture::new(
                    &memory(&probe, false, true),
                    future(&probe, false, false, true),
                );
            }))
            .is_err()
        );
        assert_eq!(probe.polls.load(Ordering::SeqCst), 0);
        assert!(probe.state_dropped.load(Ordering::SeqCst));
        assert!(probe.owner_dropped.load(Ordering::SeqCst));
        assert_eq!(probe.live.load(Ordering::SeqCst), 0);
    }

    #[test]
    fn call_future_destructor_unwind_retains_uncertain_original_charge() {
        let probe = Arc::new(Probe::default());
        let task = CallFuture::new(
            &memory(&probe, false, false),
            future(&probe, false, true, true),
        )
        .unwrap();
        assert!(catch_unwind(AssertUnwindSafe(|| drop(task))).is_err());
        assert!(probe.state_dropped.load(Ordering::SeqCst));
        assert!(!probe.owner_dropped.load(Ordering::SeqCst));
        assert_eq!(probe.live.load(Ordering::SeqCst), 1);
    }
}
