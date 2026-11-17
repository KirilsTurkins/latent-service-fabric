//! Provider-owned boxed futures. This is deliberately not the core BoxFuture alias.
use super::{capacity, PlatformError, ALLOCATION_BOOKKEEPING};
use latent_core::{ActivationBudget, HostMemoryReservation};
use std::{
    alloc::Layout,
    future::Future,
    marker::PhantomData,
    pin::Pin,
    sync::Arc,
    task::{Context, Poll},
};

/// Trusted host adapter only: one pre-existing stream row, never a guest callback.
#[doc(hidden)]
pub trait StreamRetirementObserver: Send + Sync {
    fn release_stream_retirement(&self, sequence: u64);
}

/// Trusted host adapter custody of the same original paid stream row.
#[doc(hidden)]
pub struct StreamRetirementGuard {
    owner: Option<Arc<dyn StreamRetirementObserver>>,
    sequence: u64,
    entered_unwinding: bool,
}
impl StreamRetirementGuard {
    pub fn new(owner: Arc<dyn StreamRetirementObserver>, sequence: u64) -> Self {
        Self {
            owner: Some(owner),
            sequence,
            entered_unwinding: std::thread::panicking(),
        }
    }
    pub fn begin_drop(&mut self) {
        self.entered_unwinding = std::thread::panicking();
    }
    /// Keep the original row outstanding after a caught owner failure without
    /// retaining an additional marker allocation or invoking a callback.
    pub(in crate::broker) fn retain_failed(mut self) {
        drop(self.owner.take());
    }
}
impl Drop for StreamRetirementGuard {
    fn drop(&mut self) {
        if let Some(owner) = self.owner.take() {
            if !std::thread::panicking() || self.entered_unwinding {
                owner.release_stream_retirement(self.sequence);
            }
        }
    }
}

trait ErasedIoFuture<T>: Future<Output = T> {
    fn take_stream_retirement(self: Pin<&mut Self>) -> Option<StreamRetirementGuard>;
}

pin_project_lite::pin_project! {
    #[repr(transparent)]
    struct PlainFuture<F> {
        #[pin]
        future: F,
    }
}
impl<F: Future> Future for PlainFuture<F> {
    type Output = F::Output;
    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        self.project().future.poll(cx)
    }
}
impl<T, F: Future<Output = T>> ErasedIoFuture<T> for PlainFuture<F> {
    fn take_stream_retirement(self: Pin<&mut Self>) -> Option<StreamRetirementGuard> {
        None
    }
}

pin_project_lite::pin_project! {
    struct StreamFuture<F> {
        #[pin]
        future: F,
        retirement: Option<StreamRetirementGuard>,
    }
}
impl<F: Future> Future for StreamFuture<F> {
    type Output = F::Output;
    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        self.project().future.poll(cx)
    }
}
impl<T, F: Future<Output = T>> ErasedIoFuture<T> for StreamFuture<F> {
    fn take_stream_retirement(self: Pin<&mut Self>) -> Option<StreamRetirementGuard> {
        self.project().retirement.take()
    }
}

/// A pinned provider future with its original charge, or an unallocated refusal.
///
/// Only the declared F payload plus the existing allocation bookkeeping is
/// charged. Captures' transitive allocations and allocator RSS are separate.
pub struct IoFuture<'a, T> {
    state: Option<IoFutureState<'a, T>>,
    allocation: Option<HostMemoryReservation>,
}

// No public budgetless future-Box construction. Ready is available only through
// the error-only constructor below; it does not represent provider execution.
enum IoFutureState<'a, T> {
    Boxed(Pin<Box<dyn ErasedIoFuture<T> + Send + 'a>>),
    Ready(T),
}

impl<'a, T, E> IoFuture<'a, Result<T, E>> {
    /// Propagate refusal before invoking a provider builder, without allocating.
    pub fn failed(error: E) -> Self {
        Self {
            state: Some(IoFutureState::Ready(Err(error))),
            allocation: None,
        }
    }
}

// Ready output is never pin-projected; moving the pointer never moves boxed F.
impl<T> Unpin for IoFuture<'_, T> {}

impl<T> Future for IoFuture<'_, T> {
    type Output = T;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<T> {
        let this = self.get_mut();
        if let Some(IoFutureState::Boxed(future)) = this.state.as_mut() {
            return future.as_mut().poll(cx);
        }
        match this.state.take() {
            Some(IoFutureState::Ready(value)) => Poll::Ready(value),
            _ => panic!("provider future polled after completion"),
        }
    }
}

impl<T> Drop for IoFuture<'_, T> {
    fn drop(&mut self) {
        let allocation = self.allocation.take();
        let mut retirement = match self.state.as_mut() {
            Some(IoFutureState::Boxed(future)) => future.as_mut().take_stream_retirement(),
            _ => None,
        };
        if let Some(retirement) = &mut retirement {
            retirement.begin_drop();
        }
        // The pinned Box's drop glue deallocates its own backing even if F's
        // destructor unwinds. This local guard drops after that glue finishes;
        // independently retained captures keep their own original guards.
        // Rust 1.97.1 Box drop elaboration and deallocator:
        // https://github.com/rust-lang/rust/blob/8bab26f4f68e0e26f0bb7960be334d5b520ea452/compiler/rustc_mir_transform/src/elaborate_drop.rs#L745-L753
        // https://github.com/rust-lang/rust/blob/8bab26f4f68e0e26f0bb7960be334d5b520ea452/library/alloc/src/boxed.rs#L1885-L1898
        drop(self.state.take());
        drop(allocation);
        drop(retirement);
    }
}

/// Type-connected admission before invoking a provider's future builder.
/// No budget/factory reference is stored in the finished IoFuture.
pub struct PreparedIoFuture<Make, F> {
    make: Make,
    allocation: Option<HostMemoryReservation>,
    output: PhantomData<fn() -> F>,
}

impl<Make, F> PreparedIoFuture<Make, F>
where
    Make: FnOnce() -> F,
{
    pub fn new(budget: &ActivationBudget, make: Make) -> Result<Self, PlatformError> {
        let allocation = reserve::<F>(budget)?;
        Ok(Self {
            make,
            allocation,
            output: PhantomData,
        })
    }

    pub fn finish<'a, T>(self) -> IoFuture<'a, T>
    where
        F: Future<Output = T> + Send + 'a,
    {
        // Unused preparation or a builder panic refunds the unallocated credit.
        let value = (self.make)();
        let mut owner = IoFuture {
            state: Some(IoFutureState::Boxed(Box::pin(PlainFuture {
                future: value,
            }))),
            allocation: self.allocation,
        };
        // Install physical-first Drop BEFORE confirmation can panic.
        if let Some(allocation) = &mut owner.allocation {
            allocation.confirm();
        }
        owner
    }
}

/// Reserve the exact future type before its effectful arguments even exist.
/// The caller creates Args only after admission; no Args/factory is published.
pub struct PreparedIoFutureWith<Make, F, Args> {
    make: Make,
    allocation: Option<HostMemoryReservation>,
    output: PhantomData<fn(Args) -> F>,
}
impl<Make, F, Args> PreparedIoFutureWith<Make, F, Args>
where
    Make: FnOnce(Args) -> F,
{
    pub fn new(budget: &ActivationBudget, make: Make) -> Result<Self, PlatformError> {
        Ok(Self {
            make,
            allocation: reserve::<F>(budget)?,
            output: PhantomData,
        })
    }

    pub fn finish<'a, T>(self, args: Args) -> IoFuture<'a, T>
    where
        F: Future<Output = T> + Send + 'a,
    {
        let value = (self.make)(args);
        let mut owner = IoFuture {
            state: Some(IoFutureState::Boxed(Box::pin(PlainFuture {
                future: value,
            }))),
            allocation: self.allocation,
        };
        if let Some(allocation) = &mut owner.allocation {
            allocation.confirm();
        }
        owner
    }
}

/// Admit the exact stream future and its paid retirement token before creation.
pub struct PreparedStreamIoFutureWith<Make, F, Args> {
    make: Make,
    allocation: Option<HostMemoryReservation>,
    output: PhantomData<fn(Args) -> F>,
}
impl<Make, F, Args> PreparedStreamIoFutureWith<Make, F, Args>
where
    Make: FnOnce(Args) -> (F, StreamRetirementGuard),
{
    pub(in crate::broker) fn new(
        budget: &ActivationBudget,
        make: Make,
    ) -> Result<Self, PlatformError> {
        Ok(Self {
            make,
            allocation: reserve::<StreamFuture<F>>(budget)?,
            output: PhantomData,
        })
    }

    pub fn finish<'a, T>(self, args: Args) -> IoFuture<'a, T>
    where
        F: Future<Output = T> + Send + 'a,
    {
        let (future, retirement) = (self.make)(args);
        let mut owner = IoFuture {
            state: Some(IoFutureState::Boxed(Box::pin(StreamFuture {
                future,
                retirement: Some(retirement),
            }))),
            allocation: self.allocation,
        };
        if let Some(allocation) = &mut owner.allocation {
            allocation.confirm();
        }
        owner
    }
}

fn reserve<F>(budget: &ActivationBudget) -> Result<Option<HostMemoryReservation>, PlatformError> {
    let bytes = Layout::new::<F>().size();
    let bytes = if bytes == 0 {
        0
    } else {
        bytes
            .checked_add(ALLOCATION_BOOKKEEPING)
            .and_then(|n| u64::try_from(n).ok())
            .ok_or_else(capacity)?
    };
    if budget.profile().supports_descendants() && bytes != 0 {
        budget
            .reserve_host_memory(bytes)
            .map(Some)
            .map_err(|e| e.to_platform_error())
    } else {
        Ok(None)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use latent_core::{BudgetProfile, ClockSample, EffectiveActivationBudget, ResourceBudget};
    use std::{
        marker::PhantomPinned,
        panic::{catch_unwind, AssertUnwindSafe},
        sync::{
            atomic::{AtomicBool, AtomicUsize, Ordering},
            Arc,
        },
        task::Waker,
    };

    fn budget(bytes: u64, profile: BudgetProfile) -> ActivationBudget {
        let request = ResourceBudget {
            cpu_fuel: 1_000_000_000,
            memory_bytes: bytes,
            wall_time_limit_millis: Some(5_000),
            child_calls: 0,
            outbound_requests: 0,
            state_read_bytes: 0,
            state_write_bytes: 0,
            blob_read_bytes: 0,
            blob_write_bytes: 0,
            log_bytes: 0,
            effect_count: 0,
        };
        let grant = EffectiveActivationBudget::admit_profile_at(
            profile,
            &request,
            &request,
            &request,
            None,
            ClockSample::system_now(),
        )
        .unwrap();
        ActivationBudget::with_profile(grant, profile).unwrap()
    }

    #[repr(align(256))]
    struct PinnedBody {
        budget: ActivationBudget,
        address: Arc<AtomicUsize>,
        drops: Arc<AtomicUsize>,
        panic_on_drop: Arc<AtomicBool>,
        _pin: PhantomPinned,
    }
    impl Future for PinnedBody {
        type Output = usize;
        fn poll(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<usize> {
            let this = self.as_ref().get_ref();
            let address = this as *const Self as usize;
            assert_eq!(address % 256, 0);
            let previous = this.address.swap(address, Ordering::SeqCst);
            if previous == 0 {
                Poll::Pending
            } else {
                assert_eq!(previous, address);
                Poll::Ready(42)
            }
        }
    }
    impl Drop for PinnedBody {
        fn drop(&mut self) {
            assert_eq!(self.budget.host_memory_bytes(), charge());
            self.drops.fetch_add(1, Ordering::SeqCst);
            assert!(!self.panic_on_drop.load(Ordering::SeqCst), "body drop");
        }
    }
    fn charge() -> u64 {
        (Layout::new::<PinnedBody>().size() + ALLOCATION_BOOKKEEPING) as u64
    }
    fn body(budget: &ActivationBudget, panic: bool) -> PinnedBody {
        PinnedBody {
            budget: budget.clone(),
            address: Arc::new(AtomicUsize::new(0)),
            drops: Arc::new(AtomicUsize::new(0)),
            panic_on_drop: Arc::new(AtomicBool::new(panic)),
            _pin: PhantomPinned,
        }
    }

    #[test]
    fn plain_future_and_public_owner_layouts_are_unchanged() {
        #[allow(dead_code)]
        enum PreviousState<'a, T> {
            Boxed(Pin<Box<dyn Future<Output = T> + Send + 'a>>),
            Ready(T),
        }
        #[allow(dead_code)]
        struct PreviousFuture<'a, T> {
            state: Option<PreviousState<'a, T>>,
            allocation: Option<HostMemoryReservation>,
        }
        fn same<T>() {
            assert_eq!(
                Layout::new::<IoFuture<'_, T>>(),
                Layout::new::<PreviousFuture<'_, T>>()
            );
        }
        assert_eq!(
            Layout::new::<PlainFuture<PinnedBody>>(),
            Layout::new::<PinnedBody>()
        );
        assert_eq!(
            Layout::new::<PlainFuture<std::future::Pending<()>>>(),
            Layout::new::<std::future::Pending<()>>()
        );
        same::<()>();
        same::<Result<usize, ()>>();
        same::<[u8; 1024]>();
    }

    #[test]
    fn stream_future_custody_retires_after_the_original_allocation_refund() {
        struct Owner {
            budget: ActivationBudget,
            released: Arc<AtomicUsize>,
        }
        impl StreamRetirementObserver for Owner {
            fn release_stream_retirement(&self, sequence: u64) {
                assert_eq!(sequence, 17);
                assert_eq!(self.budget.host_memory_bytes(), 0);
                self.released.fetch_add(1, Ordering::SeqCst);
            }
        }
        struct Body {
            budget: ActivationBudget,
            should_panic: bool,
        }
        impl Future for Body {
            type Output = ();
            fn poll(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<()> {
                Poll::Pending
            }
        }
        impl Drop for Body {
            fn drop(&mut self) {
                assert_eq!(self.budget.host_memory_bytes(), stream_charge());
                assert!(!self.should_panic, "inner destructor");
            }
        }
        fn stream_charge() -> u64 {
            (Layout::new::<StreamFuture<Body>>().size() + ALLOCATION_BOOKKEEPING) as u64
        }
        let denied = budget(stream_charge() - 1, BudgetProfile::Phase3);
        let called = AtomicBool::new(false);
        assert!(PreparedStreamIoFutureWith::new(
            &denied,
            |_: ()| -> (Body, StreamRetirementGuard) {
                called.store(true, Ordering::SeqCst);
                panic!("refused builder must not run")
            }
        )
        .is_err());
        assert!(!called.load(Ordering::SeqCst));

        let admitted = budget(stream_charge(), BudgetProfile::Phase3);
        let released = Arc::new(AtomicUsize::new(0));
        let make = |panic| {
            let guard = StreamRetirementGuard::new(
                Arc::new(Owner {
                    budget: admitted.clone(),
                    released: released.clone(),
                }),
                17,
            );
            PreparedStreamIoFutureWith::new(&admitted, |guard| {
                (
                    Body {
                        budget: admitted.clone(),
                        should_panic: panic,
                    },
                    guard,
                )
            })
            .unwrap()
            .finish(guard)
        };
        drop(make(false));
        assert_eq!(released.load(Ordering::SeqCst), 1);
        assert!(catch_unwind(AssertUnwindSafe(|| {
            let _future = make(false);
            panic!("caller");
        }))
        .is_err());
        assert_eq!(released.load(Ordering::SeqCst), 2);
        assert!(catch_unwind(AssertUnwindSafe(|| drop(make(true)))).is_err());
        assert_eq!(released.load(Ordering::SeqCst), 2);
        assert_eq!(admitted.host_memory_bytes(), 0);
        assert_eq!(admitted.outstanding_reservations(), 0);
    }

    #[test]
    fn provider_future_refuses_before_builder_and_refunds_unused_preparation() {
        let denied = budget(charge() - 1, BudgetProfile::Phase3);
        let called = AtomicBool::new(false);
        assert!(PreparedIoFuture::new(&denied, || {
            called.store(true, Ordering::SeqCst);
            body(&denied, false)
        })
        .is_err());
        assert!(!called.load(Ordering::SeqCst));
        assert_eq!(denied.host_memory_bytes(), 0);
        assert_eq!(denied.outstanding_reservations(), 0);

        let admitted = budget(charge(), BudgetProfile::Phase3);
        let prepared = PreparedIoFuture::new(&admitted, || body(&admitted, false)).unwrap();
        assert_eq!(admitted.host_memory_bytes(), charge());
        drop(prepared);
        assert_eq!(admitted.host_memory_bytes(), 0);
        assert_eq!(admitted.outstanding_reservations(), 0);

        let result = catch_unwind(AssertUnwindSafe(|| {
            PreparedIoFuture::new(&admitted, || -> PinnedBody { panic!("builder") })
                .unwrap()
                .finish()
        }));
        assert!(result.is_err());
        assert_eq!(admitted.host_memory_bytes(), 0);

        assert_eq!(Layout::new::<std::future::Pending<()>>().size(), 0);
        let future = PreparedIoFuture::new(&admitted, std::future::pending::<()>)
            .unwrap()
            .finish();
        assert_eq!(admitted.host_memory_bytes(), 0);
        drop(future);

        let legacy = budget(charge(), BudgetProfile::Phase1);
        let borrowed = 42usize;
        let mut future = PreparedIoFuture::new(&legacy, || async { borrowed })
            .unwrap()
            .finish();
        let mut cx = Context::from_waker(Waker::noop());
        assert_eq!(Pin::new(&mut future).poll(&mut cx), Poll::Ready(42));
        assert_eq!(legacy.host_memory_bytes(), 0);
        drop(future);
        assert_eq!(legacy.outstanding_reservations(), 0);
    }

    #[test]
    fn provider_future_pin_and_physical_first_cleanup_keep_original_charge() {
        let admitted = budget(charge(), BudgetProfile::Phase3);
        let value = body(&admitted, false);
        let drops = value.drops.clone();
        let mut future = PreparedIoFuture::new(&admitted, || value).unwrap().finish();
        let mut cx = Context::from_waker(Waker::noop());
        assert!(Pin::new(&mut future).poll(&mut cx).is_pending());
        let mut moved = future;
        assert_eq!(Pin::new(&mut moved).poll(&mut cx), Poll::Ready(42));
        assert_eq!(admitted.host_memory_bytes(), charge());
        drop(moved);
        assert_eq!(drops.load(Ordering::SeqCst), 1);
        assert_eq!(admitted.host_memory_bytes(), 0);
        assert_eq!(admitted.outstanding_reservations(), 0);

        // Unrelated caller unwind still refunds after successful physical drop.
        assert!(catch_unwind(AssertUnwindSafe(|| {
            let _future = PreparedIoFuture::new(&admitted, || body(&admitted, false))
                .unwrap()
                .finish();
            panic!("caller");
        }))
        .is_err());
        assert_eq!(admitted.host_memory_bytes(), 0);

        // The box backing is deallocated even when its payload unwinds.
        let future = PreparedIoFuture::new(&admitted, || body(&admitted, true))
            .unwrap()
            .finish();
        assert!(catch_unwind(AssertUnwindSafe(|| drop(future))).is_err());
        assert_eq!(admitted.host_memory_bytes(), 0);
        assert_eq!(admitted.outstanding_reservations(), 0);
    }

    #[test]
    fn future_refund_preserves_the_original_separately_owned_capture() {
        const CAPTURE_BYTES: u64 = 512;
        struct Retained {
            _allocation: HostMemoryReservation,
        }
        struct CapturedBody {
            budget: ActivationBudget,
            expected: u64,
            _retained: Arc<Retained>,
            should_panic: bool,
        }
        impl Future for CapturedBody {
            type Output = ();
            fn poll(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<()> {
                Poll::Pending
            }
        }
        impl Drop for CapturedBody {
            fn drop(&mut self) {
                assert_eq!(self.budget.host_memory_bytes(), self.expected);
                assert!(!self.should_panic, "captured future destructor");
            }
        }
        struct Observer {
            budget: ActivationBudget,
            releases: Arc<AtomicUsize>,
        }
        impl StreamRetirementObserver for Observer {
            fn release_stream_retirement(&self, sequence: u64) {
                assert_eq!(sequence, 17);
                assert_eq!(self.budget.host_memory_bytes(), CAPTURE_BYTES);
                self.releases.fetch_add(1, Ordering::SeqCst);
            }
        }

        let admitted = budget(16 * 1024, BudgetProfile::Phase3);
        let mut capture = admitted.reserve_host_memory(CAPTURE_BYTES).unwrap();
        capture.confirm();
        let retained = Arc::new(Retained {
            _allocation: capture,
        });
        for stream in [false, true] {
            for should_panic in [false, true] {
                let layout = if stream {
                    Layout::new::<StreamFuture<CapturedBody>>()
                } else {
                    Layout::new::<PlainFuture<CapturedBody>>()
                };
                let charge = (layout.size() + ALLOCATION_BOOKKEEPING) as u64;
                let releases = Arc::new(AtomicUsize::new(0));
                let body = CapturedBody {
                    budget: admitted.clone(),
                    expected: CAPTURE_BYTES + charge,
                    _retained: retained.clone(),
                    should_panic,
                };
                let future = if stream {
                    let custody = StreamRetirementGuard::new(
                        Arc::new(Observer {
                            budget: admitted.clone(),
                            releases: releases.clone(),
                        }),
                        17,
                    );
                    PreparedStreamIoFutureWith::new(&admitted, |(body, custody)| (body, custody))
                        .unwrap()
                        .finish((body, custody))
                } else {
                    PreparedIoFuture::new(&admitted, || body).unwrap().finish()
                };
                assert_eq!(admitted.host_memory_bytes(), CAPTURE_BYTES + charge);
                assert_eq!(admitted.outstanding_reservations(), 2);
                assert_eq!(
                    catch_unwind(AssertUnwindSafe(|| drop(future))).is_err(),
                    should_panic
                );
                assert_eq!(admitted.host_memory_bytes(), CAPTURE_BYTES);
                assert_eq!(admitted.outstanding_reservations(), 1);
                assert_eq!(
                    releases.load(Ordering::SeqCst),
                    usize::from(stream && !should_panic)
                );
            }
        }
        drop(retained);
        assert_eq!(admitted.host_memory_bytes(), 0);
        assert_eq!(admitted.outstanding_reservations(), 0);
    }

    #[test]
    fn provider_future_early_failure_is_inline_and_consumed_once() {
        use std::convert::Infallible;
        struct Refusal(Arc<AtomicUsize>);
        impl Drop for Refusal {
            fn drop(&mut self) {
                self.0.fetch_add(1, Ordering::SeqCst);
            }
        }
        let drops = Arc::new(AtomicUsize::new(0));
        let mut future: IoFuture<'_, Result<Infallible, Refusal>> =
            IoFuture::failed(Refusal(drops.clone()));
        assert!(future.allocation.is_none());
        assert!(matches!(
            future.state.as_ref(),
            Some(IoFutureState::Ready(Err(_)))
        ));
        let mut cx = Context::from_waker(Waker::noop());
        let Poll::Ready(Err(error)) = Pin::new(&mut future).poll(&mut cx) else {
            panic!("early refusal must be immediately ready");
        };
        assert_eq!(drops.load(Ordering::SeqCst), 0);
        assert!(future.state.is_none());
        assert!(catch_unwind(AssertUnwindSafe(|| Pin::new(&mut future).poll(&mut cx))).is_err());
        drop(future);
        assert_eq!(drops.load(Ordering::SeqCst), 0);
        drop(error);
        assert_eq!(drops.load(Ordering::SeqCst), 1);

        let future: IoFuture<'_, Result<Infallible, Refusal>> =
            IoFuture::failed(Refusal(drops.clone()));
        drop(future);
        assert_eq!(drops.load(Ordering::SeqCst), 2);
    }
}
