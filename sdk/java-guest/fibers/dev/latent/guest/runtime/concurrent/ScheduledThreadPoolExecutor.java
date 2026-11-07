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
    private final ArrayList<Task<?>> queue = new ArrayList<>();
    private final ArrayList<Thread> workers = new ArrayList<>();
    private volatile Activation.Lease owner;
    private boolean shutdown;
    private volatile boolean interrupting;
    private boolean continuePeriodic;
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
        catch (Throwable error) { owner.close(); owner = null; throw error; }
    }

    private long elapsed() { return System.nanoTime() - origin; }
    private long after(long delay) {
        long now = elapsed();
        delay = Math.max(0, delay);
        return now > Long.MAX_VALUE - delay ? Long.MAX_VALUE : now + delay;
    }
    private boolean allowed(Task<?> task) {
        return !retiring && !interrupting && (!shutdown || (task.period == 0 ? executeDelayed : continuePeriodic));
    }

    private static final class RunnableCall<V> implements Callable<V> {
        final Runnable command;
        final V result;
        volatile boolean invoked;
        RunnableCall(Runnable command, V result) { this.command = Objects.requireNonNull(command); this.result = result; }
        @Override public V call() { invoked = true; command.run(); return result; }
    }

    private final class Task<V> extends FutureTask<V> implements ScheduledFuture<V> {
        final long order;
        final long period; // positive=fixed rate, negative=fixed delay, zero=once
        volatile long next;
        Activation.Lease queued;
        boolean executing;
        boolean released;
        boolean resultAccepted;
        Runnable action;
        RunnableCall<?> runnableCall;
        boolean actionAccepted;
        boolean futureAccepted;
        int invocations;
        Task(Callable<V> callable, Runnable action, long next, long period, long order, Activation.Lease queued) {
            super(callable);
            this.action = action;
            this.runnableCall = callable instanceof RunnableCall<?> call ? call : null;
            this.next = next; this.period = period; this.order = order; this.queued = queued;
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
        @Override synchronized boolean acceptQueueCopy() {
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
        @Override synchronized void removeQueueCopy(boolean removed) {
            super.removeQueueCopy(removed);
            releaseActionIfIdle();
        }
        private synchronized void beginInvocation() { invocations++; }
        private synchronized void endInvocation() { invocations--; releaseActionIfIdle(); }
        @Override public void run() {
            // A returned ScheduledFuture is also a Runnable. A caller may
            // start it while the pool is concurrently withdrawing its copy.
            beginInvocation();
            try {
                // Like the JDK scheduled task, a wrapper cannot start its
                // callback after shutdownNow or activation retirement.
                if (interrupting || retiring) cancel(false);
                else super.run();
            } finally { endInvocation(); }
        }
        boolean invoke() {
            beginInvocation();
            try {
                // A worker can dequeue just before shutdownNow and reach this
                // boundary afterwards. Do not start that callback either.
                if (interrupting || retiring) { cancel(false); return false; }
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
            if (invocations == 0 && (complete || released && !hasQueueCopies())) {
                if (futureAccepted) {
                    // A FutureTask subclass may return without completing;
                    // its physical invocation then remains uncertain.
                    ((FutureTask<?>)action).removeQueueCopy(runnableCall == null || !runnableCall.invoked);
                    futureAccepted = false;
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
        private synchronized void abandon() { released = true; releaseActionIfIdle(); }
        void release() {
            if (released) return;
            if (resultAccepted) { resultAccepted = false; removeQueueCopy(true); }
            queued.close(); queued = null;
            pendingWork--;
            abandon();
        }
        @Override public boolean cancel(boolean interrupt) {
            boolean changed = super.cancel(interrupt);
            synchronized (ScheduledThreadPoolExecutor.this) {
                if (!executing && queue.remove(this)) release();
                ScheduledThreadPoolExecutor.this.notifyAll();
            }
            synchronized (this) { releaseActionIfIdle(); }
            return changed;
        }
    }

    private synchronized <V> ScheduledFuture<V> add(Callable<V> command, Runnable action, long delay, long period) {
        Objects.requireNonNull(command);
        Activation.Lease queued = null;
        Task<V> task = null;
        boolean accepted = false;
        boolean installed = false;
        try {
            if (shutdown || retiring || Activation.closing() && !Activation.acceptedContinuation())
                throw new java.util.concurrent.RejectedExecutionException("activation-scheduled-executor-closed");
            if (sequence == Long.MAX_VALUE) throw new java.util.concurrent.RejectedExecutionException("scheduled-sequence-overflow");
            queued = Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork);
            task = new Task<>(command, action, after(delay), period, sequence++, queued);
            accepted = task.acceptQueueCopy();
            task.resultAccepted = accepted;
            queue.add(task);
            pendingWork++;
            installed = true;
            if (workers.size() < parallelism && workers.size() < queue.size() + running) startWorker();
            notifyAll();
            return task;
        } catch (Throwable error) {
            if (!installed || queue.remove(task)) {
                if (installed) pendingWork--;
                if (queued != null) queued.close();
                if (accepted) { task.resultAccepted = false; task.removeQueueCopy(true); }
                if (task != null) task.abandon();
                // Only the exact SDK implementation witnesses rejection. A
                // subclass may already have retained the submitted action.
                if (Executors.isManaged(this)) CompletableFuture.rejectedBeforeAcceptance(action, this);
            }
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
            Task<?> a = queue.get(i), b = queue.get(first);
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
                synchronized (this) {
                    while (queue.isEmpty() && !shutdown && !retiring) {
                        try { wait(); } catch (InterruptedException wake) { if (interrupting) return; }
                    }
                    if (queue.isEmpty() || interrupting || retiring) return;
                    int index = first();
                    task = queue.get(index);
                    if (!allowed(task) || task.isCancelled()) {
                        queue.remove(index); task.cancel(false); task.release(); continue;
                    }
                    long remaining = task.next - elapsed();
                    if (remaining > 0) {
                        try { wait(remaining / 1_000_000, (int)(remaining % 1_000_000)); }
                        catch (InterruptedException wake) { if (interrupting) return; }
                        continue;
                    }
                    queue.remove(index); task.executing = true; running++;
                }
                boolean repeat = false;
                if (!interrupting) Thread.interrupted();
                try { repeat = task.invoke(); }
                finally {
                    synchronized (this) {
                        task.executing = false; running--;
                        if (repeat && !task.isCancelled() && allowed(task)) {
                            long step = task.period < 0 ? -task.period : task.period;
                            long base = task.period < 0 ? elapsed() : task.next;
                            task.next = base > Long.MAX_VALUE - step ? Long.MAX_VALUE : base + step;
                            queue.add(task);
                        } else {
                            if (!task.isDone()) task.cancel(false);
                            task.release();
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
        for (int i = queue.size() - 1; i >= 0; --i) {
            Task<?> task = queue.get(i);
            if (!allowed(task)) task.cancel(false);
        }
        notifyAll();
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
            Task<?> task = queue.remove(queue.size() - 1);
            pending.add(task);
            // An unexecuted returned future no longer owns accepted work.
            task.release();
        }
        for (Thread worker : workers) worker.interrupt();
        notifyAll(); settleIfTerminated();
        return pending;
    }
    private void settleIfTerminated() {
        if ((shutdown || retiring) && pendingWork == 0 && workers.isEmpty() && owner != null) {
            owner.close(); owner = null;
            Activation.unmanageRetired(this);
        }
    }
    @Override public boolean isRetired() { return owner == null; }
    @Override public synchronized boolean isShutdown() { return shutdown || retiring; }
    @Override public synchronized boolean isTerminated() { return (shutdown || retiring) && owner == null; }
    @Override public boolean awaitTermination(long timeout, TimeUnit unit) throws InterruptedException {
        long nanos = Objects.requireNonNull(unit).toNanos(timeout), started = System.nanoTime();
        synchronized (this) {
            if (isTerminated()) return true;
            if (Thread.interrupted()) throw new InterruptedException();
            while (!isTerminated()) {
                long remaining = nanos - (System.nanoTime() - started);
                if (nanos <= 0 || remaining <= 0) return false;
                wait(remaining / 1_000_000, (int)(remaining % 1_000_000));
            }
            return true;
        }
    }
    @Override public boolean hasPendingWork() { return pendingWork != 0; }
    @Override public void closeAtRoot() {
        retiring = true;
        for (Thread worker : workers) worker.interrupt();
        if (workers.isEmpty()) settleIfTerminated();
    }
}
