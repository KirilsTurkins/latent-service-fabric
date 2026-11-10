package dev.latent.guest.runtime.concurrent;

import dev.latent.generated.Bindings;
import dev.latent.guest.runtime.Activation;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.Callable;
import java.util.concurrent.Delayed;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.TimeUnit;

/** Standard scheduled work on activation-owned logical workers and timed waits.
 * A periodic result stays pending until cancellation or exceptional completion;
 * returning the application root cannot erase its queue or running callback. */
public class ScheduledThreadPoolExecutor extends AbstractExecutorService
        implements java.util.concurrent.ScheduledExecutorService, Activation.ManagedPool {
    private final int parallelism;
    private final ThreadFactory factory;
    private final long origin = System.nanoTime();
    private final ArrayList<Entry> queue = new ArrayList<>();
    private final ArrayList<Thread> workers = new ArrayList<>();
    private volatile Activation.Lease owner;
    private final java.util.concurrent.atomic.AtomicBoolean ownerSettlementStarted =
        new java.util.concurrent.atomic.AtomicBoolean();
    private volatile boolean shutdown;
    private volatile boolean interrupting;
    private volatile boolean continuePeriodic;
    private boolean executeDelayed = true;
    private volatile boolean retiring;
    private volatile int pendingWork;
    private long sequence;
    private int running;

    public ScheduledThreadPoolExecutor(int corePoolSize) {
        this(corePoolSize, Executors.defaultThreadFactory());
    }
    public ScheduledThreadPoolExecutor(int corePoolSize, ThreadFactory factory) {
        if (corePoolSize < 0) throw new IllegalArgumentException();
        // Like the standard scheduled pool, a zero-core configuration must
        // still arrange a worker for queued work. Host task admission bounds it.
        parallelism = Math.max(1, corePoolSize);
        this.factory = Objects.requireNonNull(factory);
        owner = Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.Executor);
        try { Activation.manage(this); }
        catch (Throwable error) {
            try { settleOwner(true); }
            catch (Throwable uncertain) {
                // Preserve the entry failure even if rollback is unknown.
                // This also fences an already in-flight settlement attempt.
                Activation.fenceUncertainCompletion();
            }
            throw error;
        }
    }

    private long elapsed() { return System.nanoTime() - origin; }
    private long after(long delay) {
        long now = elapsed();
        delay = Math.max(0, delay);
        return now > Long.MAX_VALUE - delay ? Long.MAX_VALUE : now + delay;
    }
    private boolean allowed(Task<?> task) {
        return !retiring && !interrupting && (!shutdown || (task.period == 0
            ? executeDelayed || task.next - elapsed() <= 0 : continuePeriodic));
    }
    private boolean mayInvoke(Task<?> task) {
        // Preserve the existing one-shot shutdown behavior; periodic tasks
        // must additionally honor the continuation policy at invocation.
        return !retiring && !interrupting && (!shutdown || task.period == 0 || continuePeriodic);
    }

    private static final class RunnableCall<V> implements Callable<V> {
        final Runnable command;
        final V result;
        volatile boolean invoked;
        RunnableCall(Runnable command, V result) { this.command = Objects.requireNonNull(command); this.result = result; }
        @Override public V call() { invoked = true; command.run(); return result; }
    }

    /** Retain the original lease and fence completion if settlement is uncertain. */
    private static void closeQueued(Activation.Lease queued) {
        try { queued.close(); }
        catch (Throwable uncertain) {
            Activation.fenceUncertainQueuedWorkSettlement(queued);
            throw uncertain;
        }
    }

    /** Each queued occurrence owns its own lease, even when Task is shared. */
    private final class Entry {
        final Task<?> task;
        Activation.Lease queued;
        boolean resultAccepted;
        boolean released;
        boolean releasing;
        Entry(Task<?> task, Activation.Lease queued, boolean resultAccepted) {
            this.task = task; this.queued = queued; this.resultAccepted = resultAccepted;
        }
        void release() {
            if (released || releasing) return;
            // A denied or uncertain settlement must not be retried as if the
            // entire occurrence had never entered its physical release path.
            releasing = true;
            if (resultAccepted) { resultAccepted = false; task.removeQueueCopy(true); }
            closeQueued(queued); queued = null;
            task.abandon();
            pendingWork--;
            released = true;
        }
    }

    private final class Task<V> extends FutureTask<V> implements ScheduledFuture<V> {
        final long order;
        final long period; // positive=fixed rate, negative=fixed delay, zero=once
        volatile long next;
        long scheduleRevision;
        boolean released;
        Runnable action;
        RunnableCall<?> runnableCall;
        boolean actionAccepted;
        boolean futureAccepted;
        Task(Callable<V> callable, Runnable action, long next, long period, long order) {
            super(callable);
            this.action = action;
            this.runnableCall = callable instanceof RunnableCall<?> call ? call : null;
            this.next = next; this.period = period; this.order = order;
        }
        @Override public long getDelay(TimeUnit unit) {
            return Objects.requireNonNull(unit).convert(next - elapsed(), TimeUnit.NANOSECONDS);
        }
        @Override public int compareTo(Delayed other) {
            if (other == this) return 0;
            if (other instanceof ScheduledThreadPoolExecutor.Task<?> task
                    && task.executor() == ScheduledThreadPoolExecutor.this) {
                int compared = Long.compare(next, task.next);
                return compared != 0 ? compared : Long.compare(order, task.order);
            }
            return Long.compare(getDelay(TimeUnit.NANOSECONDS), other.getDelay(TimeUnit.NANOSECONDS));
        }
        private ScheduledThreadPoolExecutor executor() { return ScheduledThreadPoolExecutor.this; }
        @Override boolean acceptQueueCopy() {
            synchronized (stateLock) {
                if (!super.acceptQueueCopy()) return false;
                try {
                    if (!futureAccepted && action instanceof FutureTask<?>)
                        futureAccepted = ((FutureTask<?>)action).acceptQueueCopy();
                    if (!actionAccepted) actionAccepted = CompletableFuture.acceptedByQueue(action);
                    return true;
                } catch (Throwable error) {
                    super.removeQueueCopy(true);
                    throw error;
                }
            }
        }
        @Override void removeQueueCopy(boolean removed) {
            synchronized (stateLock) {
                // This private final task accounts for its actual invocations;
                // unlike an arbitrary FutureTask subclass its run is not opaque.
                super.removeQueueCopy(true);
                releaseActionIfIdle();
            }
        }
        private void beginInvocation() { beginInternalPhysicalClaim(); }
        private void endInvocation() {
            synchronized (stateLock) { endInternalPhysicalClaim(); releaseActionIfIdle(); }
        }
        @Override public void run() {
            // A returned ScheduledFuture is also a Runnable. A caller may
            // start it while the pool is concurrently withdrawing its copy.
            beginInvocation();
            try {
                // Like the JDK scheduled task, a wrapper cannot start its
                // callback after shutdownNow or activation retirement.
                if (!mayInvoke(this)) cancel(false);
                else if (period == 0) super.run();
                else if (runAndReset()) requeueManual(this);
                else if (isDone()) discardCompleted(this);
            } finally { endInvocation(); }
        }
        boolean invoke() {
            beginInvocation();
            try {
                // A worker can dequeue just before shutdownNow and reach this
                // boundary afterwards. Do not start that callback either.
                if (!mayInvoke(this)) { cancel(false); return false; }
                if (period != 0) return runAndReset();
                super.run();
                return false;
            } finally { endInvocation(); }
        }
        private void releaseActionIfIdle() {
            // The wrapper itself can be submitted to another managed queue.
            // Its remaining copies and all entered invocations must retire
            // before the inner action's last queue claim is withdrawn.
            boolean complete = isDone();
            if (!hasInternalPhysicalClaim() && (complete || released && !hasQueueCopies())) {
                if (futureAccepted) {
                    // A FutureTask subclass may return without completing;
                    // its physical invocation then remains uncertain.
                    futureAccepted = false;
                    ((FutureTask<?>)action).removeQueueCopy(runnableCall == null || !runnableCall.invoked);
                }
                if (actionAccepted) {
                    // Action retains any other accepted copy or an opaque
                    // executor's uncertain ownership.
                    CompletableFuture.removedFromQueue(action, true, true);
                    actionAccepted = false;
                }
                // FutureTask has cleared its callable on completion. Keep no
                // additional callback capture in a user-retained future.
                if (complete) { action = null; runnableCall = null; }
            }
        }
        private void abandon() { synchronized (stateLock) { released = true; releaseActionIfIdle(); } }
        @Override public boolean cancel(boolean interrupt) {
            boolean changed = super.cancel(interrupt);
            synchronized (ScheduledThreadPoolExecutor.this) {
                try {
                    for (int index = queue.size() - 1; index >= 0; --index) {
                        Entry entry = queue.get(index);
                        if (entry.task == this) { queue.remove(index); entry.release(); }
                    }
                } finally { ScheduledThreadPoolExecutor.this.notifyAll(); }
            }
            synchronized (stateLock) { releaseActionIfIdle(); }
            return changed;
        }
    }

    private synchronized <V> ScheduledFuture<V> add(Callable<V> command, Runnable action, long delay, long period) {
        Objects.requireNonNull(command);
        Activation.Lease queued = null;
        Task<V> task = null;
        Entry entry = null;
        boolean accepted = false;
        boolean installed = false;
        boolean counted = false;
        try {
            if (shutdown || retiring || Activation.closing() && !Activation.acceptedContinuation())
                throw new java.util.concurrent.RejectedExecutionException("activation-scheduled-executor-closed");
            if (sequence == Long.MAX_VALUE) throw new java.util.concurrent.RejectedExecutionException("scheduled-sequence-overflow");
            queued = Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork);
            task = new Task<>(command, action, after(delay), period, sequence++);
            accepted = task.acceptQueueCopy();
            entry = new Entry(task, queued, accepted);
            pendingWork++; counted = true;
            queue.add(entry);
            installed = true;
            if (workers.size() < parallelism && workers.size() < queue.size() + running) startWorker();
            notifyAll();
            return task;
        } catch (Throwable error) {
            boolean withdrawn;
            try { withdrawn = withdrawFailed(entry, installed); }
            catch (Throwable uncertain) { throw error; }
            if (withdrawn) {
                try {
                    if (queued != null) closeQueued(queued);
                    if (accepted) task.removeQueueCopy(true);
                    if (task != null) task.abandon();
                    // Only the exact SDK implementation witnesses rejection. A
                    // subclass may already have retained the submitted action.
                    if (Executors.isManaged(this)) CompletableFuture.rejectedBeforeAcceptance(action, this);
                    if (counted) pendingWork--;
                } catch (Throwable uncertain) { throw error; }
            }
            throw error;
        }
    }

    // ArrayList insertion may fail before or after it becomes visible. Only
    // refund after removing this exact entry, or proving it was never present.
    private boolean withdrawFailed(Entry entry, boolean installed) {
        if (entry == null) return true;
        if (entry.released || entry.releasing) return false;
        return queue.remove(entry) || !installed && !queue.contains(entry);
    }

    private void advance(Task<?> task) {
        long step = task.period < 0 ? -task.period : task.period;
        long base = task.period < 0 ? elapsed() : task.next;
        task.next = base > Long.MAX_VALUE - step ? Long.MAX_VALUE : base + step;
        task.scheduleRevision++;
    }

    /** Completed tasks cannot use their remaining queued occurrences. */
    private synchronized void discardCompleted(Task<?> task) {
        if (!task.isDone()) return;
        for (int index = queue.size() - 1; index >= 0; --index) {
            Entry entry = queue.get(index);
            if (entry.task == task) { queue.remove(index); entry.release(); }
        }
        notifyAll();
    }

    /** A manual periodic run creates another independently admitted copy. */
    private synchronized void requeueManual(Task<?> task) {
        if (task.isDone()) return;
        if (!allowed(task)) { task.cancel(false); return; }
        Activation.Lease queued = null;
        Entry entry = null;
        boolean accepted = false;
        boolean installed = false;
        boolean counted = false;
        boolean advanced = false;
        boolean settlementAttempted = false;
        long previous = task.next;
        long revision = task.scheduleRevision;
        try {
            queued = Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork);
            accepted = task.acceptQueueCopy();
            if (!accepted) { settlementAttempted = true; closeQueued(queued); return; }
            entry = new Entry(task, queued, true);
            advance(task); advanced = true; revision = task.scheduleRevision;
            pendingWork++; counted = true;
            queue.add(entry); installed = true;
            if (workers.size() < parallelism && workers.size() < queue.size() + running) startWorker();
            notifyAll();
        } catch (Throwable error) {
            // The no-copy path may have already attempted settlement.
            if (settlementAttempted) throw error;
            boolean withdrawn;
            try { withdrawn = withdrawFailed(entry, installed); }
            catch (Throwable uncertain) { throw error; }
            if (withdrawn) {
                try {
                    if (queued != null) closeQueued(queued);
                    if (accepted) task.removeQueueCopy(true);
                    task.abandon();
                    if (counted) pendingWork--;
                    // A reentrant factory may already have advanced this shared
                    // task again. Never overwrite that later successful change.
                    if (advanced && task.scheduleRevision == revision) {
                        task.next = previous; task.scheduleRevision++;
                    }
                } catch (Throwable uncertain) { throw error; }
            }
            try { if (!task.hasQueueCopies() && !task.isDone()) task.cancel(false); }
            catch (Throwable uncertain) { throw error; }
            throw error;
        }
    }

    // TeaVM retains a completed Thread's Runnable; do not let that target
    // retain an otherwise retired executor through the thread identity ledger.
    private static final class Worker {
        private volatile ScheduledThreadPoolExecutor pool;
        private volatile Thread thread;
        Worker(ScheduledThreadPoolExecutor pool) { this.pool = pool; }
        void prepare(Thread thread) { this.thread = thread; }
        void run() {
            ScheduledThreadPoolExecutor current = pool;
            Thread expected = thread;
            if (current == null || expected == null || expected != Thread.currentThread()
                    || !Activation.runningManaged(expected, current)) return;
            try { current.work(); } finally { clear(); }
        }
        void clear() { pool = null; thread = null; }
    }

    private void startWorker() {
        Worker worker = new Worker(this);
        Thread thread = null;
        int addedAt = -1;
        try {
            thread = factory.newThread(worker::run);
            if (thread == null || thread.isAlive())
                throw new java.util.concurrent.RejectedExecutionException("activation-thread-factory");
            if (Activation.alive(thread)) throw new IllegalThreadStateException();
            addedAt = workers.size();
            workers.add(thread);
            worker.prepare(thread);
        } catch (Throwable error) {
            // Admission has not started, so the retained target cannot own a
            // managed worker. Preserve any pre-existing worker identity.
            worker.clear();
            if (addedAt >= 0 && addedAt < workers.size() && workers.get(addedAt) == thread)
                workers.remove(addedAt);
            throw error;
        }
        try { Activation.startManaged(thread, this); }
        catch (Throwable error) {
            // Accepted or rollback-uncertain work keeps both its thread and its
            // target for root interruption and eventual physical settlement.
            if (!Activation.ownsManaged(thread, this)) {
                removeWorker(thread);
                worker.clear();
            }
            throw error;
        }
    }

    private int first() {
        int first = 0;
        for (int i = 1; i < queue.size(); ++i) {
            Task<?> a = queue.get(i).task, b = queue.get(first).task;
            if (a.next < b.next || a.next == b.next && a.order < b.order) first = i;
        }
        return first;
    }
    private void removeWorker(Thread thread) {
        for (int index = 0; index < workers.size(); index++) {
            if (workers.get(index) == thread) { workers.remove(index); return; }
        }
    }

    private void work() {
        Thread current = Thread.currentThread();
        try {
            while (true) {
                Task<?> task;
                Entry entry;
                synchronized (this) {
                    while (queue.isEmpty() && !shutdown && !retiring) {
                        try { wait(); } catch (InterruptedException wake) { if (interrupting) return; }
                    }
                    if (queue.isEmpty() || interrupting || retiring) return;
                    int index = first();
                    entry = queue.get(index); task = entry.task;
                    if (!allowed(task) || task.isCancelled()) {
                        queue.remove(index);
                        if (!task.isDone()) task.cancel(false);
                        entry.release(); continue;
                    }
                    long remaining = task.next - elapsed();
                    if (remaining > 0) {
                        try { wait(remaining / 1_000_000, (int)(remaining % 1_000_000)); }
                        catch (InterruptedException wake) { if (interrupting) return; }
                        continue;
                    }
                    queue.remove(index); running++;
                }
                boolean repeat = false;
                if (!interrupting) Thread.interrupted();
                try { repeat = task.invoke(); }
                finally {
                    synchronized (this) {
                        running--;
                        if (repeat && !task.isCancelled() && allowed(task)) {
                            advance(task);
                            try { queue.add(entry); }
                            catch (Throwable error) {
                                // This occurrence still owns its original
                                // lease. Retire it only after its attempted
                                // insertion is known to be absent.
                                boolean withdrawn;
                                try { withdrawn = withdrawFailed(entry, false); }
                                catch (Throwable uncertain) { throw error; }
                                if (withdrawn) {
                                    try {
                                        if (!task.isDone()) task.cancel(false);
                                        entry.release();
                                    } catch (Throwable uncertain) { throw error; }
                                } else if (!allowed(task) && !task.isDone()) {
                                    try { task.cancel(false); } catch (Throwable uncertain) { throw error; }
                                }
                                throw error;
                            }
                        } else {
                            // A competing invocation may be running the same
                            // periodic task. Retire only this consumed copy.
                            if (!allowed(task) && !task.isDone()) task.cancel(false);
                            if (task.isDone()) discardCompleted(task);
                            entry.release();
                        }
                        notifyAll();
                    }
                }
                Activation.checkpoint();
            }
        } finally {
            synchronized (this) {
                removeWorker(current);
                if (!queue.isEmpty() && !interrupting && !retiring) startWorker();
                settleIfTerminated();
                notifyAll();
            }
        }
    }

    @Override public ScheduledFuture<?> schedule(Runnable command, long delay, TimeUnit unit) {
        return add(new RunnableCall<>(command, null), command, Objects.requireNonNull(unit).toNanos(delay), 0);
    }
    @Override public <V> ScheduledFuture<V> schedule(Callable<V> command, long delay, TimeUnit unit) {
        return add(command, null, Objects.requireNonNull(unit).toNanos(delay), 0);
    }
    @Override public ScheduledFuture<?> scheduleAtFixedRate(Runnable command, long initialDelay, long period, TimeUnit unit) {
        Objects.requireNonNull(unit);
        if (period <= 0) throw new IllegalArgumentException();
        return add(new RunnableCall<>(command, null), command, unit.toNanos(initialDelay), unit.toNanos(period));
    }
    @Override public ScheduledFuture<?> scheduleWithFixedDelay(Runnable command, long initialDelay, long delay, TimeUnit unit) {
        Objects.requireNonNull(unit);
        if (delay <= 0) throw new IllegalArgumentException();
        return add(new RunnableCall<>(command, null), command, unit.toNanos(initialDelay), -unit.toNanos(delay));
    }
    @Override public void execute(Runnable command) { schedule(command, 0, TimeUnit.NANOSECONDS); }
    @Override public <T> java.util.concurrent.Future<T> submit(Callable<T> command) {
        return schedule(command, 0, TimeUnit.NANOSECONDS);
    }
    @Override public <T> java.util.concurrent.Future<T> submit(Runnable command, T result) {
        return add(new RunnableCall<>(command, result), command, 0, 0);
    }
    @Override public java.util.concurrent.Future<?> submit(Runnable command) { return submit(command, null); }

    private void pruneShutdown() {
        try {
            int index = queue.size() - 1;
            while (index >= 0) {
                if (index >= queue.size()) { index = queue.size() - 1; continue; }
                Task<?> task = queue.get(index).task;
                if (!allowed(task)) { task.cancel(false); index = queue.size() - 1; }
                else --index;
            }
        } finally {
            // A failed clock read must not strand the original queued work.
            notifyAll();
        }
        settleIfTerminated();
    }
    public synchronized void setContinueExistingPeriodicTasksAfterShutdownPolicy(boolean value) {
        continuePeriodic = value;
        if (shutdown) pruneShutdown();
    }
    public synchronized boolean getContinueExistingPeriodicTasksAfterShutdownPolicy() { return continuePeriodic; }
    public synchronized void setExecuteExistingDelayedTasksAfterShutdownPolicy(boolean value) {
        executeDelayed = value;
        if (shutdown) pruneShutdown();
    }
    public synchronized boolean getExecuteExistingDelayedTasksAfterShutdownPolicy() { return executeDelayed; }
    @Override public synchronized void shutdown() { shutdown = true; pruneShutdown(); }
    @Override public synchronized List<Runnable> shutdownNow() {
        shutdown = interrupting = true;
        List<Runnable> pending = new ArrayList<>(queue.size());
        while (!queue.isEmpty()) {
            Entry entry = queue.remove(queue.size() - 1);
            pending.add(entry.task);
            // An unexecuted returned future no longer owns accepted work.
            entry.release();
        }
        for (Thread worker : workers) worker.interrupt();
        notifyAll(); settleIfTerminated();
        return pending;
    }
    private void settleIfTerminated() { settleIfTerminated(false); }
    private void settleIfTerminated(boolean root) {
        if ((shutdown || retiring) && pendingWork == 0 && workers.isEmpty()) settleOwner(root);
    }
    private void settleOwner(boolean rootOrRollback) {
        if (owner != null) {
            // closeAtRoot can enter outside a suspendable pool monitor. Claim
            // the sole attempt before the host call, including under reentry.
            if (!ownerSettlementStarted.compareAndSet(false, true)) {
                if (owner == null || !rootOrRollback) return;
                // Root retirement cannot report success while the first host
                // call still has an unknown outcome. Keep its pool rooted.
                Activation.fenceUncertainCompletion();
                throw new IllegalStateException("activation-executor-owner-settlement-uncertain");
            }
            Activation.Lease held = owner;
            try { held.close(); }
            catch (Throwable uncertain) {
                // The intrusive list roots the same lease without allocating.
                Activation.fenceUncertainQueuedWorkSettlement(held);
                throw uncertain;
            }
            owner = null;
            Activation.unmanageRetired(this);
        }
    }
    @Override public boolean isRetired() { return owner == null; }
    @Override public synchronized boolean isShutdown() { return shutdown || retiring; }
    private boolean terminatedUnderLock() { return (shutdown || retiring) && owner == null; }
    @Override public synchronized boolean isTerminated() { return terminatedUnderLock(); }
    @Override public boolean awaitTermination(long timeout, TimeUnit unit) throws InterruptedException {
        long nanos = Objects.requireNonNull(unit).toNanos(timeout), started = System.nanoTime();
        synchronized (this) {
            if (terminatedUnderLock()) return true;
            // No wait occurs for a nonpositive timeout; preserve interruption.
            if (nanos <= 0) return false;
            if (Thread.interrupted()) throw new InterruptedException();
            while (!terminatedUnderLock()) {
                long remaining = nanos - (System.nanoTime() - started);
                if (remaining <= 0) return false;
                wait(remaining / 1_000_000, (int)(remaining % 1_000_000));
            }
            return true;
        }
    }
    @Override public boolean hasPendingWork() { return pendingWork != 0; }
    @Override public void closeAtRoot() {
        retiring = true;
        for (Thread worker : workers) worker.interrupt();
        if (workers.isEmpty()) settleIfTerminated(true);
    }
}
