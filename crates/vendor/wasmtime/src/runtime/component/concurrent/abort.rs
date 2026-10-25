use crate::runtime::native_memory::{self, Memory};
use crate::try_mutex::{TryMutex, TryMutexGuard};
use crate::{NativeAllocation, Result};
use alloc::boxed::Box;
use alloc::sync::Arc;
use core::alloc::Layout;
use core::mem::{self, ManuallyDrop};
use core::pin::Pin;
use core::sync::atomic::AtomicUsize;
use core::task::{Context, Poll, Waker};

/// Handle to a task which may be used to join on the result of executing it.
///
/// This represents a handle to a running task which can be cancelled with
/// [`JoinHandle::abort`]. The final result and drop of the task can be
/// determined by `await`-ing this handle.
///
/// Note that dropping this handle does not affect the running task it's
/// connected to. A manual invocation of [`JoinHandle::abort`] is required to
/// affect the task.
pub struct JoinHandle {
    // Note that at this time the usage of this type within Wasmtime's async
    // implementation is not expected to ever expose the ability to expose
    // a situation where this lock can be contended. Everything's bound to the
    // store and this is largely just used to satisfy compiler bounds. Hence,
    // lock operations in this module all unwrap.
    state: JoinStateHandle,
}

// Keep the original Arc payload/layout for unselected embeddings. Selected
// state has only two private strong handles, never Weak/raw/public Arc aliases.
// The enum can enlarge inline JoinHandle/Future metadata; only the legacy Arc
// backing/payload stays exact. Generic paid F boxes use their actual Layout.
enum JoinStateHandle {
    Legacy(Arc<TryMutex<JoinState>>),
    Accounted(AccountedJoinState),
}

struct AccountedJoinState {
    inner: Option<Arc<AccountedJoinStateInner>>,
}

struct AccountedJoinStateInner {
    state: ManuallyDrop<TryMutex<JoinState>>,
    allocation: ManuallyDrop<Box<dyn NativeAllocation>>,
}

// Pinned Rust1.97.1/8bab26f4f library/alloc/src/sync.rs:
// ArcInner is repr(C,align(2)), two Atomic<usize> fields, then T. Arc::new
// allocates Box<ArcInner<T>>. Primary source:
// https://github.com/rust-lang/rust/blob/8bab26f4f/library/alloc/src/sync.rs
// Complete source177276B/SHA256
// 768776d4a37cfeb28c71a0c6d8b2ad33332d11ceaef7e47cb01463bd71b9048a.
#[repr(C, align(2))]
struct ArcHeader {
    strong: AtomicUsize,
    weak: AtomicUsize,
}

impl AccountedJoinState {
    fn layout() -> Result<Layout> {
        Ok(Layout::new::<ArcHeader>()
            .extend(Layout::new::<AccountedJoinStateInner>())?
            .0
            .pad_to_align())
    }

    fn new(allocation: Box<dyn NativeAllocation>) -> Self {
        let mut owner = Self {
            inner: Some(Arc::new(AccountedJoinStateInner {
                state: ManuallyDrop::new(TryMutex::new(JoinState::running())),
                allocation: ManuallyDrop::new(allocation),
            })),
        };
        // Install the owning wrapper before confirmation. If confirmation
        // unwinds, its Drop still frees the actual Arc before releasing credit.
        let inner = Arc::get_mut(owner.inner.as_mut().expect("private state exists"))
            .expect("state has not been shared before confirmation");
        inner.allocation.allocated();
        owner
    }

    fn inner(&self) -> &AccountedJoinStateInner {
        self.inner.as_ref().expect("live private state")
    }

    fn clone_private(&self) -> Self {
        Self {
            inner: Some(Arc::clone(self.inner.as_ref().expect("live private state"))),
        }
    }
}

impl Drop for AccountedJoinState {
    fn drop(&mut self) {
        let Some(inner) = self.inner.take().and_then(Arc::into_inner) else {
            return;
        };
        // EVERY strong wrapper uses into_inner. The one winner receives the
        // payload only after the sole implicit Weak/header allocation is freed
        // (pinned sync.rs into_inner drops Weak before returning Some(inner)).
        // Keep the charge through state/waker destruction too. If that panics,
        // ManuallyDrop deliberately retains uncertain credit; no early refund.
        let mut inner = ManuallyDrop::new(inner);
        // SAFETY: into_inner transferred this sole payload after freeing its
        // Arc header. Neither field has been dropped; we destroy each at most
        // once in order, intentionally leaking allocation if state Drop unwinds.
        unsafe {
            ManuallyDrop::drop(&mut inner.state);
            ManuallyDrop::drop(&mut inner.allocation);
        }
    }
}

impl JoinStateHandle {
    fn legacy() -> Self {
        Self::Legacy(Arc::new(TryMutex::new(JoinState::running())))
    }

    fn with_memory(memory: &Memory) -> Result<Self> {
        if memory.is_none() {
            return Ok(Self::legacy());
        }
        let layout = AccountedJoinState::layout()?;
        // The supplied original factory pays the entire Arc header+payload
        // BEFORE allocation. Its affine allocation guard owns budget directly;
        // no factory Arc is retained by an escaping cancellation handle.
        let allocation = native_memory::reserve(memory, layout.size())?
            .expect("selected nonzero Arc requires an affine allocation owner");
        Ok(Self::Accounted(AccountedJoinState::new(allocation)))
    }

    fn clone_private(&self) -> Self {
        match self {
            Self::Legacy(state) => Self::Legacy(Arc::clone(state)),
            Self::Accounted(state) => Self::Accounted(state.clone_private()),
        }
    }

    fn try_lock(&self) -> Option<TryMutexGuard<'_, JoinState>> {
        match self {
            Self::Legacy(state) => state.try_lock(),
            Self::Accounted(state) => state.inner().state.try_lock(),
        }
    }
}

enum JoinState {
    /// The task this is connected to is still running and has not completed or
    /// been dropped.
    Running {
        /// The waker that the running task has registered which is signaled
        /// upon abort.
        waiting_for_abort_signal: Option<Waker>,

        /// The waker that the `JoinHandle` has registered to await
        /// destruction of the running task itself.
        waiting_for_abort_to_complete: Option<Waker>,
    },

    /// An abort as been requested through an `JoinHandle`. The task specified
    /// here is used for `Future for JoinHandle`.
    AbortRequested {
        waiting_for_abort_to_complete: Option<Waker>,
    },

    /// The running task has completed, so no need to abort it and nothing else
    /// needs to wait.
    Complete,
}

impl JoinState {
    fn running() -> Self {
        Self::Running {
            waiting_for_abort_signal: None,
            waiting_for_abort_to_complete: None,
        }
    }
}

impl JoinHandle {
    /// Abort the task.
    ///
    /// This flags the connected task should abort in the near future, but note
    /// that if this is called while the future is being polled then that call
    /// will still complete.
    ///
    /// Note that this `JoinHandle` is itself a `Future` and can be used to
    /// await the result and destruction of the task that this is associated
    /// with.
    pub fn abort(&self) {
        let mut state = self.state.try_lock().expect("should not be contended");

        match &mut *state {
            // If this task is still running, then fall through to below to
            // transition it into the `AbortRequested` state. If present the
            // waker for the running task is notified to indicate that an abort
            // signal has been received.
            JoinState::Running {
                waiting_for_abort_signal,
                waiting_for_abort_to_complete,
            } => {
                if let Some(task) = waiting_for_abort_signal.take() {
                    task.wake();
                }

                *state = JoinState::AbortRequested {
                    waiting_for_abort_to_complete: waiting_for_abort_to_complete.take(),
                };
            }

            // If this task has already been aborted or has completed, nothing
            // is left to do.
            JoinState::AbortRequested { .. } | JoinState::Complete => {}
        }
    }

    /// Wraps the `future` provided in a new future which is "abortable" where
    /// if the returned `JoinHandle` is flagged then the future will resolve
    /// ASAP with `None` and drop the provided `future`.
    #[cfg(test)]
    pub(crate) fn run<F>(future: F) -> (JoinHandle, impl Future<Output = Option<F::Output>>)
    where
        F: Future,
    {
        Self::from_state(future, JoinStateHandle::legacy())
    }

    // Original NativeMemory is selected before Store construction. A typed
    // refusal publishes no join handle and never polls the provided future.
    pub(crate) fn run_with_memory<F>(
        future: F,
        memory: Memory,
    ) -> Result<(JoinHandle, impl Future<Output = Option<F::Output>>)>
    where
        F: Future,
    {
        Ok(Self::from_state(
            future,
            JoinStateHandle::with_memory(&memory)?,
        ))
    }

    fn from_state<F: Future>(
        future: F,
        state: JoinStateHandle,
    ) -> (JoinHandle, JoinHandleFuture<F>) {
        let handle = JoinHandle { state };
        let future = JoinHandleFuture {
            future: ManuallyDrop::new(future),
            state: handle.state.clone_private(),
        };
        (handle, future)
    }
}

impl Future for JoinHandle {
    type Output = ();

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let mut state = self
            .state
            .try_lock()
            .expect("this lock should not be contended");
        match &mut *state {
            // If this task is running or still only has requested an abort,
            // wait further for the task to get dropped.
            JoinState::Running {
                waiting_for_abort_to_complete,
                ..
            }
            | JoinState::AbortRequested {
                waiting_for_abort_to_complete,
            } => {
                *waiting_for_abort_to_complete = Some(cx.waker().clone());
                Poll::Pending
            }

            // The task is dropped, done!
            JoinState::Complete => Poll::Ready(()),
        }
    }
}

struct JoinHandleFuture<F> {
    future: ManuallyDrop<F>,
    state: JoinStateHandle,
}

impl<F> Future for JoinHandleFuture<F>
where
    F: Future,
{
    type Output = Option<F::Output>;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        // SAFETY: this is a pin-projection from `Self` to the state and `Pin`
        // of the internal future. This is the exclusive access of these fields
        // apart from the destructor and should be safe.
        let (state, future) = unsafe {
            let me = self.get_unchecked_mut();
            (&me.state, Pin::new_unchecked(&mut *me.future))
        };

        // First, before polling the future, check to see if we've been
        // aborted. If not register our task as awaiting such an abort.
        {
            let mut state = state.try_lock().expect("this lock should not be contended");
            match &mut *state {
                JoinState::Running {
                    waiting_for_abort_signal,
                    ..
                } => {
                    *waiting_for_abort_signal = Some(cx.waker().clone());
                }
                JoinState::AbortRequested { .. } | JoinState::Complete => {
                    return Poll::Ready(None);
                }
            }
        }

        future.poll(cx).map(Some)
    }
}

impl<F> Drop for JoinHandleFuture<F> {
    fn drop(&mut self) {
        // SAFETY: this is the exclusive owner of this future and it's safe to
        // drop here during the owning destructor.
        //
        // Note that this explicitly happens before notifying the abort handle
        // that the task completed so that when the notification goes through
        // it's guaranteed that the future has been destroyed.
        unsafe {
            ManuallyDrop::drop(&mut self.future);
        }

        // After the future dropped see if there was a task awaiting its
        // destruction. Simultaneously flag this state as complete.
        let prev = mem::replace(
            &mut *self.state.try_lock().expect("should not be contended"),
            JoinState::Complete,
        );
        let task = match prev {
            JoinState::Running {
                waiting_for_abort_to_complete,
                ..
            }
            | JoinState::AbortRequested {
                waiting_for_abort_to_complete,
            } => waiting_for_abort_to_complete,
            JoinState::Complete => None,
        };
        if let Some(task) = task {
            task.wake();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::JoinHandle;
    use alloc::{boxed::Box, string::ToString};
    use std::pin::{Pin, pin};
    use std::task::{Context, Poll, Waker};
    use tokio::sync::oneshot;

    fn is_ready<F>(future: Pin<&mut F>) -> bool
    where
        F: Future,
    {
        match future.poll(&mut Context::from_waker(Waker::noop())) {
            Poll::Ready(_) => true,
            Poll::Pending => false,
        }
    }

    #[tokio::test]
    async fn abort_in_progress() {
        let (tx, rx) = oneshot::channel::<()>();
        let (mut handle, future) = JoinHandle::run(rx);
        let mut handle = Pin::new(&mut handle);
        {
            let mut future = pin!(future);
            assert!(!is_ready(future.as_mut()));
            assert!(!is_ready(handle.as_mut()));
            handle.abort();
            assert!(is_ready(future.as_mut()));
            assert!(!is_ready(handle.as_mut()));
            assert!(!tx.is_closed());
        }
        assert!(is_ready(handle.as_mut()));
        assert!(tx.is_closed());
    }

    #[tokio::test]
    async fn abort_complete() {
        let (tx, rx) = oneshot::channel::<()>();
        let (mut handle, future) = JoinHandle::run(rx);
        let mut handle = Pin::new(&mut handle);
        tx.send(()).unwrap();
        assert!(!is_ready(handle.as_mut()));
        {
            let mut future = pin!(future);
            assert!(is_ready(future.as_mut()));
            assert!(!is_ready(handle.as_mut()));
        }
        assert!(is_ready(handle.as_mut()));
        handle.abort();
        assert!(is_ready(handle.as_mut()));
    }

    #[tokio::test]
    async fn abort_dropped() {
        let (tx, rx) = oneshot::channel::<()>();
        let (mut handle, future) = JoinHandle::run(rx);
        let mut handle = Pin::new(&mut handle);
        drop(future);
        assert!(is_ready(handle.as_mut()));
        handle.abort();
        assert!(is_ready(handle.as_mut()));
        assert!(tx.is_closed());
    }

    #[tokio::test]
    async fn await_completion() {
        let (tx, rx) = oneshot::channel::<()>();
        tx.send(()).unwrap();
        let (handle, future) = JoinHandle::run(rx);
        let task = tokio::task::spawn(future);
        handle.await;
        task.await.unwrap();
    }

    #[tokio::test]
    async fn await_abort() {
        let (tx, rx) = oneshot::channel::<()>();
        tx.send(()).unwrap();
        let (handle, future) = JoinHandle::run(rx);
        handle.abort();
        let task = tokio::task::spawn(future);
        handle.await;
        task.await.unwrap();
    }

    // These controls exercise the actual private cell and allocation callbacks.
    // Counters observe this exact backing owner; they are not a host/RSS ledger.
    #[derive(Default)]
    struct CellObservations {
        requested: std::sync::atomic::AtomicUsize,
        reserved: std::sync::atomic::AtomicUsize,
        confirmed: std::sync::atomic::AtomicUsize,
        refunded: std::sync::atomic::AtomicUsize,
        factory_dropped: std::sync::atomic::AtomicUsize,
        future_polled: std::sync::atomic::AtomicUsize,
        future_dropped: std::sync::atomic::AtomicBool,
        completion_woken: std::sync::atomic::AtomicBool,
    }
    struct CellMemory {
        observations: std::sync::Arc<CellObservations>,
        refuse: bool,
        panic_confirmation: bool,
    }
    struct CellAllocation {
        observations: std::sync::Arc<CellObservations>,
        bytes: usize,
        panic_confirmation: bool,
    }
    impl crate::NativeMemory for CellMemory {
        fn reserve(&self, bytes: usize) -> crate::Result<Box<dyn crate::NativeAllocation>> {
            use std::sync::atomic::Ordering::SeqCst;
            self.observations.requested.store(bytes, SeqCst);
            if self.refuse {
                return Err(crate::Error::msg("join-cell-original-memory-refused"));
            }
            self.observations.reserved.fetch_add(bytes, SeqCst);
            Ok(Box::new(CellAllocation {
                observations: self.observations.clone(),
                bytes,
                panic_confirmation: self.panic_confirmation,
            }))
        }
    }
    impl Drop for CellMemory {
        fn drop(&mut self) {
            self.observations
                .factory_dropped
                .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        }
    }
    impl crate::NativeAllocation for CellAllocation {
        fn allocated(&mut self) {
            self.observations
                .confirmed
                .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
            assert!(!self.panic_confirmation, "controlled confirmation unwind");
        }
    }
    impl Drop for CellAllocation {
        fn drop(&mut self) {
            use std::sync::atomic::Ordering::SeqCst;
            self.observations.reserved.fetch_sub(self.bytes, SeqCst);
            self.observations.refunded.fetch_add(1, SeqCst);
        }
    }
    fn cell_memory(
        observations: &std::sync::Arc<CellObservations>,
        refuse: bool,
        panic_confirmation: bool,
    ) -> crate::runtime::native_memory::Memory {
        Some(std::sync::Arc::new(CellMemory {
            observations: observations.clone(),
            refuse,
            panic_confirmation,
        }))
    }
    struct CellFuture {
        observations: std::sync::Arc<CellObservations>,
        ready: bool,
        paid: bool,
    }
    impl Future for CellFuture {
        type Output = ();
        fn poll(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<()> {
            self.observations
                .future_polled
                .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
            if self.ready {
                Poll::Ready(())
            } else {
                Poll::Pending
            }
        }
    }
    impl Drop for CellFuture {
        fn drop(&mut self) {
            use std::sync::atomic::Ordering::SeqCst;
            if self.paid {
                assert!(self.observations.reserved.load(SeqCst) > 0);
            }
            self.observations.future_dropped.store(true, SeqCst);
        }
    }
    struct CompletionWake(std::sync::Arc<CellObservations>);
    impl std::task::Wake for CompletionWake {
        fn wake(self: std::sync::Arc<Self>) {
            use std::sync::atomic::Ordering::SeqCst;
            assert!(self.0.future_dropped.load(SeqCst));
            assert!(self.0.reserved.load(SeqCst) > 0);
            self.0.completion_woken.store(true, SeqCst);
        }
    }

    #[test]
    fn accounted_join_state_refuses_before_poll_and_none_retains_legacy_arc() {
        use std::sync::atomic::Ordering::SeqCst;
        let seen = std::sync::Arc::new(CellObservations::default());
        let future = CellFuture {
            observations: seen.clone(),
            ready: false,
            paid: false,
        };
        let result = JoinHandle::run_with_memory(future, cell_memory(&seen, true, false));
        let error = match result {
            Err(error) => error,
            Ok(_) => panic!("must refuse"),
        };
        assert!(
            error
                .to_string()
                .contains("join-cell-original-memory-refused")
        );
        assert_eq!(
            seen.requested.load(SeqCst),
            super::AccountedJoinState::layout().unwrap().size()
        );
        println!("LSF_JOIN_STATE_LAYOUT={}", seen.requested.load(SeqCst));
        assert_eq!(seen.confirmed.load(SeqCst), 0);
        assert_eq!(seen.future_polled.load(SeqCst), 0);
        assert!(seen.future_dropped.load(SeqCst));
        assert_eq!(seen.reserved.load(SeqCst), 0);
        let (handle, future) = JoinHandle::run_with_memory(async {}, None).unwrap();
        assert!(matches!(&handle.state, super::JoinStateHandle::Legacy(_)));
        drop(future);
        drop(handle);
        assert_eq!(seen.confirmed.load(SeqCst), 0);
    }

    #[test]
    fn accounted_join_state_normal_and_abort_keep_charge_through_last_alias() {
        use std::sync::atomic::Ordering::SeqCst;
        for abort in [false, true] {
            let seen = std::sync::Arc::new(CellObservations::default());
            let original = CellFuture {
                observations: seen.clone(),
                ready: !abort,
                paid: true,
            };
            // Exercise the real owned Store-factory binding, not just an
            // external Arc. Its separate pre-admitted header owner must retire
            // while both cell aliases and their original allocation survive.
            let factory_seen = std::sync::Arc::new(CellObservations::default());
            let factory_bytes = crate::NativeMemoryBinding::allocation_size::<CellMemory>();
            factory_seen.reserved.store(factory_bytes, SeqCst);
            let binding = crate::NativeMemoryBinding::new(
                CellMemory {
                    observations: seen.clone(),
                    refuse: false,
                    panic_confirmation: false,
                },
                Box::new(CellAllocation {
                    observations: factory_seen.clone(),
                    bytes: factory_bytes,
                    panic_confirmation: false,
                }),
            );
            let (mut handle, future) =
                JoinHandle::run_with_memory(original, Some(binding.memory())).unwrap();
            assert_eq!(factory_seen.confirmed.load(SeqCst), 1);
            assert_eq!(seen.factory_dropped.load(SeqCst), 0);
            drop(binding);
            assert_eq!(factory_seen.reserved.load(SeqCst), 0);
            assert_eq!(factory_seen.refunded.load(SeqCst), 1);
            let bytes = seen.requested.load(SeqCst);
            assert_eq!(bytes, super::AccountedJoinState::layout().unwrap().size());
            assert_eq!(seen.confirmed.load(SeqCst), 1);
            // The state owns its paid allocation, not the factory Arc.
            assert_eq!(seen.factory_dropped.load(SeqCst), 1);
            let waker = Waker::from(std::sync::Arc::new(CompletionWake(seen.clone())));
            assert!(
                Pin::new(&mut handle)
                    .poll(&mut Context::from_waker(&waker))
                    .is_pending()
            );
            if abort {
                handle.abort();
            }
            let mut future = Box::pin(future);
            assert!(
                future
                    .as_mut()
                    .poll(&mut Context::from_waker(Waker::noop()))
                    .is_ready()
            );
            assert!(!seen.future_dropped.load(SeqCst));
            drop(future);
            assert!(seen.future_dropped.load(SeqCst));
            assert!(seen.completion_woken.load(SeqCst));
            assert_eq!(seen.reserved.load(SeqCst), bytes);
            drop(handle);
            assert_eq!(seen.reserved.load(SeqCst), 0);
            assert_eq!(seen.refunded.load(SeqCst), 1);
        }
        // Dropping the cancellation handle first cannot refund the live future.
        let seen = std::sync::Arc::new(CellObservations::default());
        let (handle, future) =
            JoinHandle::run_with_memory(async {}, cell_memory(&seen, false, false)).unwrap();
        drop(handle);
        assert!(seen.reserved.load(SeqCst) > 0);
        drop(future);
        assert_eq!(seen.reserved.load(SeqCst), 0);
        assert_eq!(seen.refunded.load(SeqCst), 1);
    }

    #[test]
    fn accounted_join_state_concurrent_final_drops_refund_exactly_once() {
        use std::sync::atomic::Ordering::SeqCst;
        let seen = std::sync::Arc::new(CellObservations::default());
        let first = super::JoinStateHandle::with_memory(&cell_memory(&seen, false, false)).unwrap();
        let second = first.clone_private();
        let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));
        std::thread::scope(|scope| {
            let other = barrier.clone();
            scope.spawn(move || {
                other.wait();
                drop(first);
            });
            scope.spawn(move || {
                barrier.wait();
                drop(second);
            });
        });
        assert_eq!(seen.reserved.load(SeqCst), 0);
        assert_eq!(seen.refunded.load(SeqCst), 1);
    }

    #[test]
    fn accounted_join_state_confirmation_unwind_destroys_cell_before_refund() {
        use std::sync::atomic::Ordering::SeqCst;
        let seen = std::sync::Arc::new(CellObservations::default());
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let _ = JoinHandle::run_with_memory(async {}, cell_memory(&seen, false, true));
        }));
        assert!(result.is_err());
        assert_eq!(seen.confirmed.load(SeqCst), 1);
        assert_eq!(seen.reserved.load(SeqCst), 0);
        assert_eq!(seen.refunded.load(SeqCst), 1);
    }

    #[test]
    fn accounted_join_state_waker_destructor_unwind_retains_uncertain_charge() {
        use std::sync::atomic::Ordering::SeqCst;
        struct PanicOnDrop;
        impl std::task::Wake for PanicOnDrop {
            fn wake(self: std::sync::Arc<Self>) {}
        }
        impl Drop for PanicOnDrop {
            fn drop(&mut self) {
                panic!("controlled state-waker unwind");
            }
        }
        let seen = std::sync::Arc::new(CellObservations::default());
        let state = super::JoinStateHandle::with_memory(&cell_memory(&seen, false, false)).unwrap();
        {
            let mut locked = state.try_lock().unwrap();
            match &mut *locked {
                super::JoinState::Running {
                    waiting_for_abort_signal,
                    ..
                } => {
                    *waiting_for_abort_signal = Some(Waker::from(std::sync::Arc::new(PanicOnDrop)));
                }
                _ => panic!("original running state"),
            }
        }
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(state)));
        assert!(result.is_err());
        assert!(seen.reserved.load(SeqCst) > 0);
        assert_eq!(seen.refunded.load(SeqCst), 0);
        // One intentionally retained affine owner; no retry/reset or fake free.
    }
}
