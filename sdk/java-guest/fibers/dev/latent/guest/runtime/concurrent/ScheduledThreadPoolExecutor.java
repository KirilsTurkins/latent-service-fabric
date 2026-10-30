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
    private Activation.Lease owner;
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

    private final class Task<V> extends FutureTask<V> implements ScheduledFuture<V> {
        final long order;
        final long period; // positive=fixed rate, negative=fixed delay, zero=once
        volatile long next;
        Activation.Lease queued;
        boolean executing;
        boolean released;
        boolean resultAccepted;
        Task(Callable<V> callable, long next, long period, long order, Activation.Lease queued) {
            super(callable);
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
        boolean invoke() {
            if (period != 0) return runAndReset();
            super.run();
            return false;
        }
        void release() {
            if (released) return;
            if (resultAccepted) { resultAccepted = false; removeQueueCopy(true); }
            queued.close(); queued = null;
            released = true;
            pendingWork--;
        }
        @Override public boolean cancel(boolean interrupt) {
            boolean changed = super.cancel(interrupt);
            synchronized (ScheduledThreadPoolExecutor.this) {
                if (!executing && queue.remove(this)) release();
                ScheduledThreadPoolExecutor.this.notifyAll();
            }
            return changed;
        }
    }

    private synchronized <V> ScheduledFuture<V> add(Callable<V> command, long delay, long period) {
        Objects.requireNonNull(command);
        if (shutdown || retiring || Activation.closing() && !Activation.acceptedContinuation())
            throw new java.util.concurrent.RejectedExecutionException("activation-scheduled-executor-closed");
        if (sequence == Long.MAX_VALUE) throw new java.util.concurrent.RejectedExecutionException("scheduled-sequence-overflow");
        Activation.Lease queued = Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork);
        Task<V> task = null;
        boolean accepted = false;
        boolean installed = false;
        try {
            task = new Task<>(command, after(delay), period, sequence++, queued);
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
                queued.close();
                if (accepted) { task.resultAccepted = false; task.removeQueueCopy(true); }
            }
            throw error;
        }
    }

    private void startWorker() {
        Thread thread = factory.newThread(this::work);
        if (thread == null || thread.isAlive())
            throw new java.util.concurrent.RejectedExecutionException("activation-thread-factory");
        workers.add(thread);
        try { Activation.startManaged(thread); }
        catch (Throwable error) { workers.remove(thread); throw error; }
    }

    private int first() {
        int first = 0;
        for (int i = 1; i < queue.size(); ++i) {
            Task<?> a = queue.get(i), b = queue.get(first);
            if (a.next < b.next || a.next == b.next && a.order < b.order) first = i;
        }
        return first;
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
                workers.remove(current);
                if (!queue.isEmpty() && !interrupting && !retiring) startWorker();
                settleIfTerminated();
                notifyAll();
            }
        }
    }

    @Override public ScheduledFuture<?> schedule(Runnable command, long delay, TimeUnit unit) {
        return schedule(Executors.callable(command, null), delay, unit);
    }
    @Override public <V> ScheduledFuture<V> schedule(Callable<V> command, long delay, TimeUnit unit) {
        return add(command, Objects.requireNonNull(unit).toNanos(delay), 0);
    }
    @Override public ScheduledFuture<?> scheduleAtFixedRate(Runnable command, long initialDelay, long period, TimeUnit unit) {
        Objects.requireNonNull(unit);
        if (period <= 0) throw new IllegalArgumentException();
        return add(Executors.callable(command, null), unit.toNanos(initialDelay), unit.toNanos(period));
    }
    @Override public ScheduledFuture<?> scheduleWithFixedDelay(Runnable command, long initialDelay, long delay, TimeUnit unit) {
        Objects.requireNonNull(unit);
        if (delay <= 0) throw new IllegalArgumentException();
        return add(Executors.callable(command, null), unit.toNanos(initialDelay), -unit.toNanos(delay));
    }
    @Override public void execute(Runnable command) { schedule(command, 0, TimeUnit.NANOSECONDS); }
    @Override public <T> java.util.concurrent.Future<T> submit(Callable<T> command) {
        return schedule(command, 0, TimeUnit.NANOSECONDS);
    }
    @Override public <T> java.util.concurrent.Future<T> submit(Runnable command, T result) {
        return schedule(Executors.callable(command, result), 0, TimeUnit.NANOSECONDS);
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
        }
    }
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
