// SPDX-License-Identifier: MIT OR Apache-2.0
// Selected port of authenticated futures-executor0.3.31 src/thread_pool.rs.
// Upstream SHA256:6fec12d757b73a5dad7f1c711cf947de2968a8b2d9d549bfad0a3921e77d5fdc.
// The original mpsc queues, UnparkMutex protocol and user Future bodies remain.
// Source WIP: captured std linkage/final graph and signed execution required;
// this file is not selected by any shipping compiler or a qualification result.
use crate::enter;
use crate::lsf_thread_pool as owned;
use crate::unpark_mutex::UnparkMutex;
use futures_core::future::Future;
use futures_core::task::{Context, Poll};
use futures_task::{waker_ref, ArcWake};
use futures_task::{FutureObj, Spawn, SpawnError};
use futures_util::future::FutureExt;
use std::boxed::Box;
use std::cmp;
use std::fmt;
use std::format;
use std::io;
use std::mem::ManuallyDrop;
use std::string::String;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::thread;

/// A general-purpose thread pool for scheduling tasks that poll futures to
/// completion.
///
/// The thread pool multiplexes any number of tasks onto a fixed number of
/// worker threads.
///
/// This type is a clonable handle to the threadpool itself.
/// Cloning it will only create a new reference, not a new threadpool.
///
/// This type is only available when the `thread-pool` feature of this
/// library is activated.
#[cfg_attr(docsrs, doc(cfg(feature = "thread-pool")))]
pub struct ThreadPool {
    state: Arc<PoolState>,
}

/// Thread pool configuration object.
///
/// This type is only available when the `thread-pool` feature of this
/// library is activated.
#[cfg_attr(docsrs, doc(cfg(feature = "thread-pool")))]
pub struct ThreadPoolBuilder {
    pool_size: usize,
    stack_size: usize,
    name_prefix: Option<String>,
    after_start: Option<Arc<dyn Fn(usize) + Send + Sync>>,
    before_stop: Option<Arc<dyn Fn(usize) + Send + Sync>>,
}

#[allow(dead_code)]
trait AssertSendSync: Send + Sync {}
impl AssertSendSync for ThreadPool {}

struct PoolState {
    tx: Mutex<mpsc::Sender<Message>>,
    rx: Mutex<mpsc::Receiver<Message>>,
    cnt: AtomicUsize,
    size: usize,
    runtime: owned::Pool,
    recipe: WorkerRecipe,
}

#[derive(Clone)]
struct WorkerRecipe {
    stack_size: usize,
    name_prefix: Option<String>,
}

impl fmt::Debug for ThreadPool {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("ThreadPool")
            .field("size", &self.state.size)
            .finish()
    }
}

impl fmt::Debug for ThreadPoolBuilder {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("ThreadPoolBuilder")
            .field("pool_size", &self.pool_size)
            .field("name_prefix", &self.name_prefix)
            .finish()
    }
}

enum Message {
    Run(Task),
    Close(owned::Generation),
}

impl ThreadPool {
    /// Creates a new thread pool with the default configuration.
    ///
    /// See documentation for the methods in
    /// [`ThreadPoolBuilder`](ThreadPoolBuilder) for details on the default
    /// configuration.
    pub fn new() -> Result<Self, io::Error> {
        ThreadPoolBuilder::new().create()
    }

    /// Create a default thread pool configuration, which can then be customized.
    ///
    /// See documentation for the methods in
    /// [`ThreadPoolBuilder`](ThreadPoolBuilder) for details on the default
    /// configuration.
    pub fn builder() -> ThreadPoolBuilder {
        ThreadPoolBuilder::new()
    }

    /// Spawns a future that will be run to completion.
    ///
    /// > **Note**: This method is similar to `Spawn::spawn_obj`, except that
    /// >           it is guaranteed to always succeed.
    pub fn spawn_obj_ok(&self, future: FutureObj<'static, ()>) {
        self.try_spawn_obj(future)
            .unwrap_or_else(|_| panic!("selected thread-pool admission refused"));
    }

    fn try_spawn_obj(&self, future: FutureObj<'static, ()>) -> Result<(), SpawnError> {
        self.state
            .ensure_generation()
            .map_err(|_| SpawnError::shutdown())?;
        // Actual Task and first queue escrow precede new wake/task backing and
        // publication. Refusal leaves the original future unpolled and dropped.
        let key = self
            .state
            .runtime
            .admit_future()
            .map_err(|_| SpawnError::shutdown())?;
        self.spawn_admitted(future, key);
        Ok(())
    }

    fn spawn_admitted(&self, future: FutureObj<'static, ()>, key: owned::FutureKey) {
        let task = Task {
            future,
            key,
            wake_handle: Arc::new(WakeHandle {
                exec: self.clone(),
                mutex: UnparkMutex::new(),
                key,
            }),
            exec: self.clone(),
        };
        self.state.send(Message::Run(task));
        self.state.runtime.changed();
    }

    /// Spawns a task that polls the given future with output `()` to
    /// completion.
    ///
    /// ```
    /// # {
    /// use futures::executor::ThreadPool;
    ///
    /// let pool = ThreadPool::new().unwrap();
    ///
    /// let future = async { /* ... */ };
    /// pool.spawn_ok(future);
    /// # }
    /// # std::thread::sleep(std::time::Duration::from_millis(500)); // wait for background threads closed: https://github.com/rust-lang/miri/issues/1371
    /// ```
    ///
    /// > **Note**: This method is similar to `SpawnExt::spawn`, except that
    /// >           it is guaranteed to always succeed.
    pub fn spawn_ok<Fut>(&self, future: Fut)
    where
        Fut: Future<Output = ()> + Send + 'static,
    {
        self.state
            .ensure_generation()
            .expect("selected thread-pool worker admission refused");
        let key = self
            .state
            .runtime
            .admit_future()
            .expect("selected thread-pool task admission refused");
        self.spawn_admitted(FutureObj::new(Box::new(future)), key)
    }
}

impl Spawn for ThreadPool {
    fn spawn_obj(&self, future: FutureObj<'static, ()>) -> Result<(), SpawnError> {
        self.try_spawn_obj(future)
    }
}

impl PoolState {
    fn send(&self, msg: Message) {
        self.tx.lock().unwrap().send(msg).unwrap();
    }

    fn work(&self, worker: owned::Worker) {
        let _scope = enter().unwrap();
        loop {
            // This remains this pool's real independent original mpsc queue.
            let msg = self.rx.lock().unwrap().recv().unwrap();
            match msg {
                Message::Run(task) => {
                    self.runtime.dequeued(task.key);
                    task.run();
                }
                Message::Close(generation) => {
                    if self.runtime.claim_close(worker, generation) {
                        break;
                    }
                    self.send(Message::Close(generation));
                    // Another generation's close belongs to its real worker.
                    // Never promote an arbitrary suspended/running target.
                    thread::yield_now();
                }
            }
        }
        // Closure return is not TLS/frame completion. The PAL's registered
        // retained pool reference supplies both real later notifications.
    }

    fn send_close(&self, close: owned::Close) {
        for _ in 0..close.messages {
            self.send(Message::Close(close.generation));
        }
        self.runtime.changed();
    }

    fn ensure_generation(self: &Arc<Self>) -> io::Result<()> {
        let Some(generation) = self.runtime.begin_generation(self.size)? else {
            return Ok(());
        };
        for counter in 0..self.size {
            // Each worker's eventual Close queue ownership is prepaid here,
            // before thread/handshake allocations. Cleanup admits no new quota.
            let worker = match self.runtime.reserve_worker(generation) {
                Ok(worker) => worker,
                Err(error) => {
                    self.send_close(self.runtime.abort_generation(generation));
                    return Err(error);
                }
            };
            let (started, wait_started) = mpsc::channel();
            let state = self.clone();
            let mut builder = thread::Builder::new();
            if let Some(prefix) = self.recipe.name_prefix.as_ref() {
                builder = builder.name(format!("{}{}", prefix, counter));
            }
            if self.recipe.stack_size > 0 {
                builder = builder.stack_size(self.recipe.stack_size);
            }
            let spawned = builder.spawn(move || {
                // Transfer ONE actual Arc reference to this exact running PAL
                // child. Root keeps another; user values cannot die in System.
                let retained = Arc::into_raw(state.clone());
                let entered = unsafe {
                    state
                        .runtime
                        .worker_entered(worker, retained.cast_mut().cast())
                };
                if entered.is_err() {
                    drop(unsafe { Arc::from_raw(retained) });
                }
                let live = entered.is_ok();
                started
                    .send(entered)
                    .expect("selected worker startup receiver disappeared");
                if live {
                    state.work(worker);
                }
            });
            let handle = match spawned {
                Ok(handle) => handle,
                Err(error) => {
                    self.send_close(self.runtime.abort_generation(generation));
                    return Err(error);
                }
            };
            // Ordinary JoinHandle drop detaches; PAL retains real frames/Task.
            drop(handle);
            // Ack precedes original queue processing; no user future has
            // been accepted by this still-provisioning generation.
            match wait_started
                .recv()
                .expect("selected worker startup ended without evidence")
            {
                Ok(()) => {}
                Err(error) => {
                    self.send_close(self.runtime.abort_generation(generation));
                    return Err(error);
                }
            }
        }
        self.runtime.commit_generation(generation);
        Ok(())
    }

    unsafe extern "C" fn progress(pointer: *mut ()) -> u32 {
        // Borrow the root registration's actual retained Arc without cloning
        // its strong count. It is consumed only by the release callback.
        let state = ManuallyDrop::new(unsafe { Arc::from_raw(pointer.cast::<Self>()) });
        match state.runtime.drain() {
            owned::Drain::Pending => owned::PENDING,
            owned::Drain::Close(close) => {
                state.send_close(close);
                owned::PENDING
            }
            owned::Drain::Quiescent => {
                if state.cnt.load(Ordering::Acquire) == 0 && Arc::strong_count(&state) == 1 {
                    state.runtime.retire();
                    owned::RELEASABLE
                } else {
                    owned::QUIESCENT
                }
            }
        }
    }
    unsafe extern "C" fn release(pointer: *mut ()) {
        drop(unsafe { Arc::from_raw(pointer.cast::<Self>()) });
    }
}

impl Clone for ThreadPool {
    fn clone(&self) -> Self {
        self.state.cnt.fetch_add(1, Ordering::Relaxed);
        Self {
            state: self.state.clone(),
        }
    }
}

impl Drop for ThreadPool {
    fn drop(&mut self) {
        assert!(self.state.cnt.fetch_sub(1, Ordering::AcqRel) > 0);
        // Accepted futures, actual TLS destructors and worker frames still
        // drain. The root, not this handle drop, initiates generation Close.
        self.state.runtime.changed();
    }
}

impl ThreadPoolBuilder {
    /// Create a default thread pool configuration.
    ///
    /// See the other methods on this type for details on the defaults.
    pub fn new() -> Self {
        Self {
            pool_size: cmp::max(1, num_cpus::get()),
            stack_size: 0,
            name_prefix: None,
            after_start: None,
            before_stop: None,
        }
    }

    /// Set size of a future ThreadPool
    ///
    /// The size of a thread pool is the number of worker threads spawned. By
    /// default, this is equal to the number of CPU cores.
    ///
    /// # Panics
    ///
    /// Panics if `pool_size == 0`.
    pub fn pool_size(&mut self, size: usize) -> &mut Self {
        assert!(size > 0);
        self.pool_size = size;
        self
    }

    /// Set stack size of threads in the pool, in bytes.
    ///
    /// By default, worker threads use Rust's standard stack size.
    pub fn stack_size(&mut self, stack_size: usize) -> &mut Self {
        self.stack_size = stack_size;
        self
    }

    /// Set thread name prefix of a future ThreadPool.
    ///
    /// Thread name prefix is used for generating thread names. For example, if prefix is
    /// `my-pool-`, then threads in the pool will get names like `my-pool-1` etc.
    ///
    /// By default, worker threads are assigned Rust's standard thread name.
    pub fn name_prefix<S: Into<String>>(&mut self, name_prefix: S) -> &mut Self {
        self.name_prefix = Some(name_prefix.into());
        self
    }

    /// Execute the closure `f` immediately after each worker thread is started,
    /// but before running any tasks on it.
    ///
    /// This hook is intended for bookkeeping and monitoring.
    /// The closure `f` will be dropped after the `builder` is dropped
    /// and all worker threads in the pool have executed it.
    ///
    /// The closure provided will receive an index corresponding to the worker
    /// thread it's running on.
    pub fn after_start<F>(&mut self, f: F) -> &mut Self
    where
        F: Fn(usize) + Send + Sync + 'static,
    {
        self.after_start = Some(Arc::new(f));
        self
    }

    /// Execute closure `f` just prior to shutting down each worker thread.
    ///
    /// This hook is intended for bookkeeping and monitoring.
    /// The closure `f` will be dropped after the `builder` is dropped
    /// and all threads in the pool have executed it.
    ///
    /// The closure provided will receive an index corresponding to the worker
    /// thread it's running on.
    pub fn before_stop<F>(&mut self, f: F) -> &mut Self
    where
        F: Fn(usize) + Send + Sync + 'static,
    {
        self.before_stop = Some(Arc::new(f));
        self
    }

    /// Create a [`ThreadPool`](ThreadPool) with the given configuration.
    pub fn create(&mut self) -> Result<ThreadPool, io::Error> {
        // The original after_start Arc dies immediately after each callback.
        // Retaining it as a successor recipe would change observable Drop
        // behavior; omitting it on successors would skip requested callbacks.
        // This finite profile therefore refuses both hook configurations
        // before any Executor/Native admission, channel or pool allocation.
        if self.after_start.is_some() || self.before_stop.is_some() {
            return Err(io::Error::from(io::ErrorKind::Unsupported));
        }
        // Executor and bounded control Native admission precede original
        // channel/Arc allocation. Uncommitted setup owns all rollback state.
        let setup = owned::PoolSetup::new()?;
        let (tx, rx) = mpsc::channel();
        let pool = ThreadPool {
            state: Arc::new(PoolState {
                tx: Mutex::new(tx),
                rx: Mutex::new(rx),
                cnt: AtomicUsize::new(1),
                size: self.pool_size,
                runtime: setup.handle(),
                recipe: WorkerRecipe {
                    stack_size: self.stack_size,
                    name_prefix: self.name_prefix.clone(),
                },
            }),
        };
        let retained = Arc::into_raw(pool.state.clone());
        unsafe {
            setup.commit(
                retained.cast_mut().cast(),
                PoolState::progress,
                PoolState::release,
            );
        }
        pool.state.ensure_generation()?;
        Ok(pool)
    }
}

impl Default for ThreadPoolBuilder {
    fn default() -> Self {
        Self::new()
    }
}

/// A task responsible for polling a future to completion.
struct Task {
    future: FutureObj<'static, ()>,
    exec: ThreadPool,
    wake_handle: Arc<WakeHandle>,
    key: owned::FutureKey,
}

struct WakeHandle {
    mutex: UnparkMutex<Task>,
    exec: ThreadPool,
    key: owned::FutureKey,
}
impl Drop for WakeHandle {
    fn drop(&mut self) {
        // This clears a logical fixed registration, not the Arc backing byte
        // charge. The real Pool Arc/worker/root frame lifetimes remain held.
        self.exec.state.runtime.wake_dropped(self.key);
    }
}

impl Task {
    /// Actually run the task (invoking `poll` on the future) on the current
    /// thread.
    fn run(self) {
        let Self {
            mut future,
            wake_handle,
            mut exec,
            key,
        } = self;
        let waker = waker_ref(&wake_handle);
        let mut cx = Context::from_waker(&waker);

        // Safety: The ownership of this `Task` object is evidence that
        // we are in the `POLLING`/`REPOLL` state for the mutex.
        unsafe {
            wake_handle.mutex.start_poll();

            loop {
                let res = future.poll_unpin(&mut cx);
                match res {
                    Poll::Pending => {}
                    Poll::Ready(()) => {
                        wake_handle.mutex.complete();
                        drop(future);
                        exec.state.runtime.completed(key);
                        return;
                    }
                }
                let task = Self {
                    future,
                    wake_handle: wake_handle.clone(),
                    exec,
                    key,
                };
                match wake_handle.mutex.wait(task) {
                    Ok(()) => {
                        wake_handle.exec.state.runtime.waiting(key);
                        return;
                    } // actual original wait
                    Err(task) => {
                        // someone's notified us
                        future = task.future;
                        exec = task.exec;
                    }
                }
            }
        }
    }
}

impl fmt::Debug for Task {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Task").field("contents", &"...").finish()
    }
}

impl ArcWake for WakeHandle {
    fn wake_by_ref(arc_self: &Arc<Self>) {
        if let Ok(task) = arc_self.mutex.notify() {
            arc_self.exec.state.runtime.requeue(task.key);
            arc_self.exec.state.send(Message::Run(task));
            arc_self.exec.state.runtime.changed();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_drop_after_start() {
        {
            let (tx, rx) = mpsc::sync_channel(2);
            let _cpu_pool = ThreadPoolBuilder::new()
                .pool_size(2)
                .after_start(move |_| tx.send(1).unwrap())
                .create()
                .unwrap();

            // After ThreadPoolBuilder is deconstructed, the tx should be dropped
            // so that we can use rx as an iterator.
            let count = rx.into_iter().count();
            assert_eq!(count, 2);
        }
        std::thread::sleep(std::time::Duration::from_millis(500)); // wait for background threads closed: https://github.com/rust-lang/miri/issues/1371
    }
}
