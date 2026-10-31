//! Original-Store admission for the single physical call-result channel header.
//!
//! Synchronization and the active send/receive/drop bodies below are maintained
//! from futures-channel 0.3.34 (MIT OR Apache-2.0). The complete original source
//! hashes and exact selected-body inverse are retained in the source review.
//! The sibling LICENSE-MIT and LICENSE-APACHE apply to the copied portions.
//! None delegates to the original channel. Paid headers use our declared typed
//! Arc layout; no standard-library Arc layout or post-birth adoption is assumed.
//! Message payloads, cloned task Wakers and callback bodies retain their own
//! original owners; this module claims only the channel's concrete backing.

use super::paid_arc;
use crate::runtime::native_memory::Memory;
use core::future::Future;
use core::pin::Pin;
use core::sync::atomic::AtomicBool;
use core::sync::atomic::Ordering::SeqCst;
use core::task::{Context, Poll, Waker};
use futures::channel::oneshot as legacy;
pub(in crate::runtime::component::concurrent) use legacy::Canceled;

pub(in crate::runtime::component::concurrent) enum Sender<T> {
    Legacy(legacy::Sender<T>),
    Paid(PaidSender<T>),
}
pub(in crate::runtime::component::concurrent) enum Receiver<T> {
    Legacy(legacy::Receiver<T>),
    Paid(PaidReceiver<T>),
}
pub(in crate::runtime::component::concurrent) struct PaidSender<T> {
    inner: paid_arc::Arc<Inner<T>>,
}
pub(in crate::runtime::component::concurrent) struct PaidReceiver<T> {
    inner: paid_arc::Arc<Inner<T>>,
}
impl<T> Unpin for Receiver<T> {}

pub(in crate::runtime::component::concurrent) fn channel<T>(
    memory: &Memory,
) -> crate::Result<(Sender<T>, Receiver<T>)> {
    if memory.is_none() {
        let (tx, rx) = legacy::channel();
        return Ok((Sender::Legacy(tx), Receiver::Legacy(rx)));
    }
    let inner = paid_arc::Arc::new(memory, Inner::new())?;
    let rx = PaidReceiver {
        inner: inner.clone(),
    };
    let tx = PaidSender { inner };
    Ok((Sender::Paid(tx), Receiver::Paid(rx)))
}

impl<T> Sender<T> {
    pub(in crate::runtime::component::concurrent) fn send(self, value: T) -> Result<(), T> {
        match self {
            Self::Legacy(tx) => tx.send(value),
            Self::Paid(tx) => tx.inner.send(value),
        }
    }
}
impl<T> Future for Receiver<T> {
    type Output = Result<T, Canceled>;
    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        match self.get_mut() {
            Self::Legacy(rx) => Pin::new(rx).poll(cx),
            Self::Paid(rx) => rx.inner.recv(cx),
        }
    }
}
impl<T> Drop for PaidSender<T> {
    fn drop(&mut self) {
        self.inner.drop_tx()
    }
}
impl<T> Drop for PaidReceiver<T> {
    fn drop(&mut self) {
        self.inner.drop_rx()
    }
}

impl<T> core::fmt::Debug for Sender<T> {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        match self {
            Self::Legacy(tx) => core::fmt::Debug::fmt(tx, f),
            Self::Paid(tx) => f
                .debug_struct("Sender")
                .field("complete", &tx.inner.complete)
                .finish(),
        }
    }
}
impl<T> core::fmt::Debug for Receiver<T> {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        match self {
            Self::Legacy(rx) => core::fmt::Debug::fmt(rx, f),
            Self::Paid(rx) => f
                .debug_struct("Receiver")
                .field("complete", &rx.inner.complete)
                .finish(),
        }
    }
}

// Preserve the upstream SeqCst complete/data/task protocol and nonblocking locks.
// Receiver rechecks complete after installing its task, preventing lost wakeups.
struct Inner<T> {
    complete: AtomicBool,

    data: Lock<Option<T>>,

    rx_task: Lock<Option<Waker>>,

    tx_task: Lock<Option<Waker>>,
}

impl<T> Inner<T> {
    fn new() -> Self {
        Self {
            complete: AtomicBool::new(false),
            data: Lock::new(None),
            rx_task: Lock::new(None),
            tx_task: Lock::new(None),
        }
    }

    fn send(&self, t: T) -> Result<(), T> {
        if self.complete.load(SeqCst) {
            return Err(t);
        }

        if let Some(mut slot) = self.data.try_lock() {
            assert!(slot.is_none());
            *slot = Some(t);
            drop(slot);

            if self.complete.load(SeqCst) {
                if let Some(mut slot) = self.data.try_lock() {
                    if let Some(t) = slot.take() {
                        return Err(t);
                    }
                }
            }
            Ok(())
        } else {
            Err(t)
        }
    }

    fn drop_tx(&self) {
        self.complete.store(true, SeqCst);

        if let Some(mut slot) = self.rx_task.try_lock() {
            if let Some(task) = slot.take() {
                drop(slot);
                task.wake();
            }
        }

        if let Some(mut slot) = self.tx_task.try_lock() {
            drop(slot.take());
        }
    }

    fn recv(&self, cx: &mut Context<'_>) -> Poll<Result<T, Canceled>> {
        let done = if self.complete.load(SeqCst) {
            true
        } else {
            let task = cx.waker().clone();
            match self.rx_task.try_lock() {
                Some(mut slot) => {
                    *slot = Some(task);
                    false
                }
                None => true,
            }
        };

        if done || self.complete.load(SeqCst) {
            if let Some(mut slot) = self.data.try_lock() {
                if let Some(data) = slot.take() {
                    return Poll::Ready(Ok(data));
                }
            }
            Poll::Ready(Err(Canceled))
        } else {
            Poll::Pending
        }
    }

    fn drop_rx(&self) {
        self.complete.store(true, SeqCst);

        if let Some(mut slot) = self.rx_task.try_lock() {
            let task = slot.take();
            drop(slot);
            drop(task);
        }

        if let Some(mut handle) = self.tx_task.try_lock() {
            if let Some(task) = handle.take() {
                drop(handle);
                task.wake()
            }
        }
    }
}

mod lock {
    use core::cell::UnsafeCell;
    use core::ops::{Deref, DerefMut};
    use core::sync::atomic::AtomicBool;
    use core::sync::atomic::Ordering::SeqCst;

    #[derive(Debug)]
    pub(crate) struct Lock<T> {
        locked: AtomicBool,
        data: UnsafeCell<T>,
    }

    pub(crate) struct TryLock<'a, T> {
        __ptr: &'a Lock<T>,
    }

    // SAFETY: the unique try-lock guard serializes T; both traits require T: Send.
    unsafe impl<T: Send> Send for Lock<T> {}
    unsafe impl<T: Send> Sync for Lock<T> {}

    impl<T> Lock<T> {
        pub(crate) fn new(t: T) -> Self {
            Self {
                locked: AtomicBool::new(false),
                data: UnsafeCell::new(t),
            }
        }

        pub(crate) fn try_lock(&self) -> Option<TryLock<'_, T>> {
            if !self.locked.swap(true, SeqCst) {
                Some(TryLock { __ptr: self })
            } else {
                None
            }
        }
    }

    impl<T> Deref for TryLock<'_, T> {
        type Target = T;
        fn deref(&self) -> &T {
            // SAFETY: this live TryLock guard owns access until its SeqCst unlock.
            unsafe { &*self.__ptr.data.get() }
        }
    }

    impl<T> DerefMut for TryLock<'_, T> {
        fn deref_mut(&mut self) -> &mut T {
            // SAFETY: only this unique TryLock guard can form mutable data access.
            unsafe { &mut *self.__ptr.data.get() }
        }
    }

    impl<T> Drop for TryLock<'_, T> {
        fn drop(&mut self) {
            self.__ptr.locked.store(false, SeqCst);
        }
    }
}
use lock::Lock;

#[cfg(all(test, feature = "std", feature = "cranelift"))]
mod native_memory_tests {
    use super::*;
    use crate::{AsContextMut, Engine, NativeAllocation, NativeMemory, Store};
    use alloc::boxed::Box;
    use alloc::sync::Arc;
    use alloc::vec::Vec;
    use core::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
    use std::panic::{AssertUnwindSafe, catch_unwind};
    use std::sync::Mutex;
    use std::task::Wake;

    #[derive(Default)]
    struct State {
        requests: Mutex<Vec<usize>>,
        active: AtomicUsize,
        confirmations: AtomicUsize,
        deny: AtomicBool,
        confirmation_panic: AtomicBool,
        wakes: AtomicUsize,
        values_dropped: AtomicUsize,
    }
    struct MemoryFactory(Arc<State>);
    struct Allocation(Arc<State>);
    impl NativeAllocation for Allocation {
        fn allocated(&mut self) {
            self.0.confirmations.fetch_add(1, Ordering::SeqCst);
            assert!(
                !self.0.confirmation_panic.load(Ordering::SeqCst),
                "call-result-confirmation-unwind"
            );
        }
    }
    impl Drop for Allocation {
        fn drop(&mut self) {
            self.0.active.fetch_sub(1, Ordering::SeqCst);
        }
    }
    #[derive(Debug)]
    struct Denied;
    impl core::fmt::Display for Denied {
        fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
            f.write_str("call-result-original-admission")
        }
    }
    impl std::error::Error for Denied {}
    impl NativeMemory for MemoryFactory {
        fn reserve(&self, bytes: usize) -> crate::Result<Box<dyn NativeAllocation>> {
            self.0.requests.lock().unwrap().push(bytes);
            if self.0.deny.load(Ordering::SeqCst) {
                return Err(crate::Error::new(Denied));
            }
            self.0.active.fetch_add(1, Ordering::SeqCst);
            Ok(Box::new(Allocation(self.0.clone())))
        }
    }
    impl Wake for State {
        fn wake(self: Arc<Self>) {
            self.wakes.fetch_add(1, Ordering::SeqCst);
        }
    }
    fn original() -> (Store<()>, Memory, Arc<State>) {
        let state = Arc::new(State::default());
        let mut store = Store::try_new_with_memory(
            &Engine::default(),
            (),
            Arc::new(MemoryFactory(state.clone())),
        )
        .unwrap();
        let memory = store.as_context_mut().0.native_memory();
        state.requests.lock().unwrap().clear();
        (store, memory, state)
    }
    #[test]
    fn original_store_refuses_exact_header_before_any_channel_publication() {
        let (store, memory, state) = original();
        let baseline = state.active.load(Ordering::SeqCst);
        let confirmations = state.confirmations.load(Ordering::SeqCst);
        state.deny.store(true, Ordering::SeqCst);
        let error = channel::<u64>(&memory).unwrap_err();
        assert!(error.downcast_ref::<Denied>().is_some());
        assert_eq!(
            *state.requests.lock().unwrap(),
            [paid_arc::Arc::<Inner<u64>>::layout().size()]
        );
        assert_eq!(state.active.load(Ordering::SeqCst), baseline);
        assert_eq!(state.confirmations.load(Ordering::SeqCst), confirmations);
        state.deny.store(false, Ordering::SeqCst);
        let (tx, rx) = channel::<u64>(&memory).unwrap();
        assert_eq!(state.active.load(Ordering::SeqCst), baseline + 1);
        drop(store);
        assert_eq!(state.active.load(Ordering::SeqCst), 1);
        drop(tx);
        assert_eq!(state.active.load(Ordering::SeqCst), 1);
        drop(rx);
        assert_eq!(state.active.load(Ordering::SeqCst), 0);
    }
    #[test]
    fn send_wakes_parked_receiver_and_header_retires_after_last_half() {
        let (store, memory, state) = original();
        let baseline = state.active.load(Ordering::SeqCst);
        let (tx, mut rx) = channel::<u64>(&memory).unwrap();
        let waker = Waker::from(state.clone());
        let mut cx = Context::from_waker(&waker);
        assert!(Pin::new(&mut rx).poll(&mut cx).is_pending());
        assert_eq!(state.wakes.load(Ordering::SeqCst), 0);
        std::thread::scope(|scope| scope.spawn(move || tx.send(42).unwrap()).join().unwrap());
        assert_eq!(state.wakes.load(Ordering::SeqCst), 1);
        assert_eq!(state.active.load(Ordering::SeqCst), baseline + 1);
        assert!(matches!(
            Pin::new(&mut rx).poll(&mut cx),
            Poll::Ready(Ok(42))
        ));
        assert_eq!(state.active.load(Ordering::SeqCst), baseline + 1);
        drop(rx);
        assert_eq!(state.active.load(Ordering::SeqCst), baseline);
        drop(store);
        assert_eq!(state.active.load(Ordering::SeqCst), 0);
    }
    #[test]
    fn cancelled_halves_and_legacy_channels_preserve_value_and_wake_semantics() {
        let (store, memory, state) = original();
        let baseline = state.active.load(Ordering::SeqCst);
        let (tx, rx) = channel::<u64>(&memory).unwrap();
        drop(rx);
        assert_eq!(state.active.load(Ordering::SeqCst), baseline + 1);
        assert_eq!(tx.send(31), Err(31));
        assert_eq!(state.active.load(Ordering::SeqCst), baseline);
        let (tx, mut rx) = channel::<()>(&memory).unwrap();
        let waker = Waker::from(state.clone());
        let mut cx = Context::from_waker(&waker);
        assert!(Pin::new(&mut rx).poll(&mut cx).is_pending());
        let wakes = state.wakes.load(Ordering::SeqCst);
        drop(tx);
        assert_eq!(state.wakes.load(Ordering::SeqCst), wakes + 1);
        assert!(matches!(
            Pin::new(&mut rx).poll(&mut cx),
            Poll::Ready(Err(Canceled))
        ));
        drop(rx);
        assert_eq!(state.active.load(Ordering::SeqCst), baseline);
        let requests = state.requests.lock().unwrap().len();
        let (tx, mut rx) = channel::<u64>(&None).unwrap();
        assert!(matches!(rx, Receiver::Legacy(_)));
        tx.send(53).unwrap();
        assert!(matches!(
            Pin::new(&mut rx).poll(&mut cx),
            Poll::Ready(Ok(53))
        ));
        drop(rx);
        assert_eq!(state.requests.lock().unwrap().len(), requests);
        drop(store);
        assert_eq!(state.active.load(Ordering::SeqCst), 0);
    }
    struct Value(Arc<State>);
    impl Drop for Value {
        fn drop(&mut self) {
            assert!(
                self.0.active.load(Ordering::SeqCst) > 0,
                "channel header retired before its retained payload destructor"
            );
            self.0.values_dropped.fetch_add(1, Ordering::SeqCst);
            panic!("call-result-payload-unwind");
        }
    }
    #[test]
    fn confirmation_refunds_but_payload_unwind_retains_original_header_charge() {
        let (store, memory, state) = original();
        let baseline = state.active.load(Ordering::SeqCst);
        state.confirmation_panic.store(true, Ordering::SeqCst);
        assert!(catch_unwind(AssertUnwindSafe(|| channel::<u64>(&memory))).is_err());
        assert_eq!(state.active.load(Ordering::SeqCst), baseline);
        state.confirmation_panic.store(false, Ordering::SeqCst);
        let (tx, rx) = channel::<Value>(&memory).unwrap();
        assert!(tx.send(Value(state.clone())).is_ok());
        drop(store);
        assert_eq!(state.active.load(Ordering::SeqCst), 1);
        assert!(catch_unwind(AssertUnwindSafe(|| drop(rx))).is_err());
        assert_eq!(state.values_dropped.load(Ordering::SeqCst), 1);
        // The existing owned Arc deliberately retains the implicit weak,
        // physical header and SAME ticket after a payload destructor unwinds.
        // No final-free, recovery or zero-owner claim is made for this path.
        assert_eq!(state.active.load(Ordering::SeqCst), 1);
        let (tx, rx) = channel::<u64>(&memory).unwrap();
        tx.send(7).unwrap();
        drop(rx);
        assert_eq!(state.active.load(Ordering::SeqCst), 1);
    }
}
