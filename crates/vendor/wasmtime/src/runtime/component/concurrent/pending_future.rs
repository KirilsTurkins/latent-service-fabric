//! Prepare the exact pending continuation Box before the initial host poll.
//!
//! Factory output type, argument tuple and affine reservation travel together.
//! No factory invocation or continuation allocation happens during preparation.

use super::BoxedHostTaskFuture;
use crate::runtime::native_memory::{self, Memory};
use crate::{NativeAllocation, Result};
use alloc::boxed::Box;
use core::alloc::Layout;
use core::future::Future;
use core::marker::PhantomData;
use core::mem::ManuallyDrop;
use core::pin::Pin;
use core::task::{Context, Poll};

pub(super) struct PreparedFuture<Args, Factory, Output> {
    args: Args,
    factory: Factory,
    allocation: Option<Box<dyn NativeAllocation>>,
    _output: PhantomData<fn() -> Output>,
}

impl<Args, Factory, Output> PreparedFuture<Args, Factory, Output>
where
    Factory: FnOnce(Args) -> Output,
    Output: Future<Output = Result<()>> + Send + 'static,
{
    pub(super) fn new(memory: &Memory, args: Args, factory: Factory) -> Result<Self> {
        // Output is the SAME concrete future type later returned by factory.
        // In particular, no guessed erased layout or factory execution is used.
        let allocation = native_memory::reserve(memory, Layout::new::<Output>().size())?;
        Ok(Self {
            args,
            factory,
            allocation,
            _output: PhantomData,
        })
    }

    pub(super) fn args_mut(&mut self) -> &mut Args {
        &mut self.args
    }

    pub(super) fn into_args(self) -> Args {
        let Self {
            args,
            factory,
            allocation,
            ..
        } = self;
        // The initial poll completed. No continuation Box was allocated and
        // its reservation is never confirmed; release it before direct lower.
        drop(factory);
        drop(allocation);
        args
    }

    pub(super) fn finish(self) -> HostTaskFuture {
        let Self {
            args,
            factory,
            allocation,
            ..
        } = self;
        // No fallible admission occurs here after the original poll. Erasing
        // Box<Output> changes its pointer metadata, never allocates a second Box.
        let future: BoxedHostTaskFuture = Box::pin(factory(args));
        let Some(allocation) = allocation else {
            return HostTaskFuture::legacy(future);
        };
        let mut owner = AccountedFuture {
            future: ManuallyDrop::new(future),
            allocation: ManuallyDrop::new(allocation),
        };
        // Install physical cleanup before an allocating confirmation can unwind.
        owner.allocation.allocated();
        HostTaskFuture(Kind::Accounted(owner))
    }
}

// Crate visibility permits the existing Store teardown collector signature;
// the representation and both allocation fields remain private to this module.
pub(crate) struct HostTaskFuture(Kind);

enum Kind {
    Legacy(BoxedHostTaskFuture),
    Accounted(AccountedFuture),
}

struct AccountedFuture {
    future: ManuallyDrop<BoxedHostTaskFuture>,
    allocation: ManuallyDrop<Box<dyn NativeAllocation>>,
}

impl HostTaskFuture {
    // Only adapt the six pre-existing boxed paths, without allocating or adding
    // fallible admission to existing stream-pipe mutations. These old paths and
    // container/node backing are NOT covered by the prepared continuation owner.
    pub(super) fn legacy(future: BoxedHostTaskFuture) -> Self {
        Self(Kind::Legacy(future))
    }
}

impl Future for HostTaskFuture {
    type Output = Result<()>;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        match &mut self.get_mut().0 {
            Kind::Legacy(future) => future.as_mut().poll(cx),
            Kind::Accounted(owner) => owner.future.as_mut().poll(cx),
        }
    }
}

impl Drop for AccountedFuture {
    fn drop(&mut self) {
        // SAFETY: one private owner destroys each field once. The erased Box
        // destroys/deallocates its original concrete Output before the guard.
        // Future-destructor unwind deliberately retains that original charge.
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
        requests: AtomicUsize,
        live: AtomicUsize,
        factories: AtomicUsize,
        confirmations: AtomicUsize,
        polls: AtomicUsize,
        inner_dropped: AtomicBool,
        output_dropped: AtomicBool,
        owner_dropped: AtomicBool,
        address: AtomicUsize,
    }
    struct Input {
        probe: Arc<Probe>,
        ready: bool,
    }
    impl Future for Input {
        type Output = ();
        fn poll(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<()> {
            self.probe.polls.fetch_add(1, Ordering::SeqCst);
            if self.ready {
                Poll::Ready(())
            } else {
                Poll::Pending
            }
        }
    }
    impl Drop for Input {
        fn drop(&mut self) {
            self.probe.inner_dropped.store(true, Ordering::SeqCst);
        }
    }
    struct Args {
        input: Input,
        panic_drop: bool,
        selected: bool,
    }
    struct Output {
        args: Args,
        _pinned: PhantomPinned,
    }
    impl Future for Output {
        type Output = Result<()>;
        fn poll(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<Result<()>> {
            let this = self.into_ref().get_ref();
            let probe = &this.args.input.probe;
            probe.polls.fetch_add(1, Ordering::SeqCst);
            let address = this as *const Self as usize;
            let prior = probe.address.swap(address, Ordering::SeqCst);
            assert!(prior == 0 || prior == address);
            if this.args.selected {
                assert_eq!(probe.live.load(Ordering::SeqCst), 1);
            }
            if this.args.input.ready {
                Poll::Ready(Ok(()))
            } else {
                Poll::Pending
            }
        }
    }
    impl Drop for Output {
        fn drop(&mut self) {
            let probe = &self.args.input.probe;
            if self.args.selected {
                assert_eq!(probe.live.load(Ordering::SeqCst), 1);
                assert!(!probe.owner_dropped.load(Ordering::SeqCst));
            }
            probe.output_dropped.store(true, Ordering::SeqCst);
            assert!(!self.args.panic_drop, "pending-destructor-control");
        }
    }
    fn factory(args: Args) -> Output {
        args.input.probe.factories.fetch_add(1, Ordering::SeqCst);
        Output {
            args,
            _pinned: PhantomPinned,
        }
    }
    fn args(probe: &Arc<Probe>, ready: bool, panic_drop: bool, selected: bool) -> Args {
        Args {
            input: Input {
                probe: probe.clone(),
                ready,
            },
            panic_drop,
            selected,
        }
    }
    struct Owner {
        probe: Arc<Probe>,
        panic_confirmation: bool,
    }
    impl NativeAllocation for Owner {
        fn allocated(&mut self) {
            self.probe.confirmations.fetch_add(1, Ordering::SeqCst);
            assert!(!self.panic_confirmation, "pending-confirmation-control");
        }
    }
    impl Drop for Owner {
        fn drop(&mut self) {
            if self.probe.factories.load(Ordering::SeqCst) != 0 {
                assert!(self.probe.output_dropped.load(Ordering::SeqCst));
                assert!(self.probe.inner_dropped.load(Ordering::SeqCst));
            } else {
                assert_eq!(self.probe.confirmations.load(Ordering::SeqCst), 0);
            }
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
            // This is the exact concrete output type of factory, not Args,
            // the erased pointer, or a guessed upper bound.
            assert_eq!(bytes, Layout::new::<Output>().size());
            self.probe.requests.fetch_add(1, Ordering::SeqCst);
            if self.refuse {
                crate::bail!("original-pending-refusal-control");
            }
            assert_eq!(self.probe.live.fetch_add(1, Ordering::SeqCst), 0);
            Ok(Box::new(Owner {
                probe: self.probe.clone(),
                panic_confirmation: self.panic_confirmation,
            }))
        }
    }
    fn memory(probe: &Arc<Probe>, refuse: bool, panic_confirmation: bool) -> native_memory::Memory {
        Some(Arc::new(Memory {
            probe: probe.clone(),
            refuse,
            panic_confirmation,
        }))
    }
    fn poll(future: &mut HostTaskFuture) -> Poll<Result<()>> {
        Pin::new(future).poll(&mut Context::from_waker(Waker::noop()))
    }

    #[test]
    fn pending_future_refuses_before_input_poll_or_factory_and_ready_refunds_unused() {
        let probe = Arc::new(Probe::default());
        let prepared = PreparedFuture::new(
            &memory(&probe, true, false),
            args(&probe, false, false, true),
            factory,
        );
        assert!(prepared.is_err());
        assert_eq!(probe.requests.load(Ordering::SeqCst), 1);
        assert_eq!(probe.factories.load(Ordering::SeqCst), 0);
        assert_eq!(probe.polls.load(Ordering::SeqCst), 0);
        assert_eq!(probe.live.load(Ordering::SeqCst), 0);
        assert!(probe.inner_dropped.load(Ordering::SeqCst));

        let probe = Arc::new(Probe::default());
        let mut prepared = PreparedFuture::new(
            &memory(&probe, false, false),
            args(&probe, true, false, true),
            factory,
        )
        .unwrap();
        assert!(
            Pin::new(&mut prepared.args_mut().input)
                .poll(&mut Context::from_waker(Waker::noop()))
                .is_ready()
        );
        let original = prepared.into_args();
        assert_eq!(probe.live.load(Ordering::SeqCst), 0);
        assert_eq!(probe.factories.load(Ordering::SeqCst), 0);
        assert_eq!(probe.confirmations.load(Ordering::SeqCst), 0);
        assert!(!probe.output_dropped.load(Ordering::SeqCst));
        assert!(!probe.inner_dropped.load(Ordering::SeqCst));
        drop(original);
        assert!(probe.inner_dropped.load(Ordering::SeqCst));
    }

    #[test]
    fn pending_future_same_reservation_keeps_pinned_output_until_physical_drop() {
        for ready in [false, true] {
            let probe = Arc::new(Probe::default());
            let prepared = PreparedFuture::new(
                &memory(&probe, false, false),
                args(&probe, ready, false, true),
                factory,
            )
            .unwrap();
            assert_eq!(probe.factories.load(Ordering::SeqCst), 0);
            let mut task = prepared.finish();
            assert_eq!(probe.requests.load(Ordering::SeqCst), 1);
            assert_eq!(probe.factories.load(Ordering::SeqCst), 1);
            assert_eq!(probe.confirmations.load(Ordering::SeqCst), 1);
            for _ in 0..2 {
                assert_eq!(poll(&mut task).is_ready(), ready);
                assert_eq!(probe.live.load(Ordering::SeqCst), 1);
                assert!(!probe.output_dropped.load(Ordering::SeqCst));
            }
            drop(task);
            assert_eq!(probe.live.load(Ordering::SeqCst), 0);
            assert!(probe.owner_dropped.load(Ordering::SeqCst));
        }
        let probe = Arc::new(Probe::default());
        let mut task = PreparedFuture::new(&None, args(&probe, true, false, false), factory)
            .unwrap()
            .finish();
        assert!(matches!(&task.0, Kind::Legacy(_)));
        assert!(poll(&mut task).is_ready());
        drop(task);
        assert_eq!(probe.requests.load(Ordering::SeqCst), 0);
        assert!(probe.output_dropped.load(Ordering::SeqCst));
    }

    #[test]
    fn pending_future_confirmation_unwind_destroys_output_before_refund() {
        let probe = Arc::new(Probe::default());
        let prepared = PreparedFuture::new(
            &memory(&probe, false, true),
            args(&probe, false, false, true),
            factory,
        )
        .unwrap();
        assert!(catch_unwind(AssertUnwindSafe(|| prepared.finish())).is_err());
        assert_eq!(probe.polls.load(Ordering::SeqCst), 0);
        assert!(probe.output_dropped.load(Ordering::SeqCst));
        assert!(probe.inner_dropped.load(Ordering::SeqCst));
        assert!(probe.owner_dropped.load(Ordering::SeqCst));
        assert_eq!(probe.live.load(Ordering::SeqCst), 0);
    }

    #[test]
    fn pending_future_destructor_unwind_retains_only_original_charge() {
        let probe = Arc::new(Probe::default());
        let task = PreparedFuture::new(
            &memory(&probe, false, false),
            args(&probe, false, true, true),
            factory,
        )
        .unwrap()
        .finish();
        assert!(catch_unwind(AssertUnwindSafe(|| drop(task))).is_err());
        assert!(probe.output_dropped.load(Ordering::SeqCst));
        assert!(probe.inner_dropped.load(Ordering::SeqCst));
        assert!(!probe.owner_dropped.load(Ordering::SeqCst));
        assert_eq!(probe.live.load(Ordering::SeqCst), 1);
        assert_eq!(probe.requests.load(Ordering::SeqCst), 1);
    }
}
