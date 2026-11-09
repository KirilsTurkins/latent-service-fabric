package dev.latent.guest.runtime.concurrent;

import dev.latent.generated.Bindings;
import dev.latent.guest.runtime.Activation;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.TimeUnit;

/** An independent FIFO pool of maintained Java fibers, never a host thread pool. */
final class ManagedExecutor extends AbstractExecutorService implements Activation.ManagedPool {
    private final int parallelism;
    private final ThreadFactory factory;
    private final boolean cached;
    private final boolean expireIdle;
    private final ArrayDeque<Item> queue = new ArrayDeque<>();
    private final ArrayList<Thread> workers = new ArrayList<>();
    private volatile Activation.Lease owner;
    private final java.util.concurrent.atomic.AtomicBoolean ownerSettlementStarted =
        new java.util.concurrent.atomic.AtomicBoolean();
    private boolean shutdown;
    private boolean interrupting;
    private volatile boolean retiring;
    private int running;
    private volatile int pendingWork;

    private static final class Item {
        final Runnable command;
        final Activation.Lease queued;
        final boolean actionAccepted;
        final boolean futureAccepted;
        Item(Runnable command, Activation.Lease queued, boolean actionAccepted, boolean futureAccepted) {
            this.command = command; this.queued = queued; this.actionAccepted = actionAccepted; this.futureAccepted = futureAccepted;
        }
    }

    ManagedExecutor(int parallelism, ThreadFactory factory) {
        this(parallelism, factory, false);
    }
    ManagedExecutor(int parallelism, ThreadFactory factory, boolean cached) {
        this(parallelism, factory, cached, cached);
    }
    ManagedExecutor(int parallelism, ThreadFactory factory, boolean cached, boolean expireIdle) {
        if (parallelism <= 0) throw new IllegalArgumentException();
        this.parallelism = parallelism;
        this.factory = Objects.requireNonNull(factory);
        this.cached = cached;
        this.expireIdle = expireIdle;
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

    /** Preserve the admitted lease and fence completion if settlement is uncertain. */
    private static void closeQueued(Activation.Lease queued) {
        try { queued.close(); }
        catch (Throwable uncertain) {
            Activation.fenceUncertainQueuedWorkSettlement(queued);
            throw uncertain;
        }
    }

    @Override public synchronized void execute(Runnable command) {
        Objects.requireNonNull(command);
        Activation.Lease queued = null;
        FutureTask<?> future = command instanceof FutureTask<?> ? (FutureTask<?>)command : null;
        boolean acceptedResult = false;
        boolean acceptedAction = false;
        Item item = null;
        boolean installed = false;
        try {
            if (shutdown || retiring || Activation.closing() && !Activation.acceptedContinuation())
                throw new java.util.concurrent.RejectedExecutionException("activation-executor-closed");
            queued = Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork);
            if (future != null) acceptedResult = future.acceptQueueCopy();
            acceptedAction = CompletableFuture.acceptedByQueue(command);
            item = new Item(command, queued, acceptedAction, acceptedResult);
            queue.addLast(item);
            pendingWork++;
            installed = true;
            if (workers.size() < parallelism && (!cached || queue.size() > workers.size() - running)) startWorker();
            notifyAll();
        } catch (Throwable error) {
            if (!installed || queue.remove(item)) {
                if (installed) pendingWork--;
                if (queued != null) closeQueued(queued);
                if (acceptedResult) future.removeQueueCopy(true);
                CompletableFuture.removedFromQueue(command, acceptedAction, true);
                CompletableFuture.rejectedBeforeAcceptance(command, this);
            }
            throw error;
        }
    }

    // TeaVM retains a completed Thread's Runnable; do not let that target
    // retain an otherwise retired executor through the thread identity ledger.
    private static final class Worker {
        private volatile ManagedExecutor pool;
        private volatile Thread thread;
        Worker(ManagedExecutor pool) { this.pool = pool; }
        void prepare(Thread thread) { this.thread = thread; }
        void run() {
            ManagedExecutor current = pool;
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

    private void removeWorker(Thread thread) {
        for (int index = 0; index < workers.size(); index++) {
            if (workers.get(index) == thread) { workers.remove(index); return; }
        }
    }

    private void work() {
        Thread current = Thread.currentThread();
        try {
            while (true) {
                Item item;
                synchronized (this) {
                    long idleStart = System.nanoTime();
                    while (queue.isEmpty() && !shutdown && !retiring) {
                        try {
                            if (expireIdle) {
                                long remaining = 60_000_000_000L - (System.nanoTime() - idleStart);
                                if (remaining <= 0) return;
                                wait(remaining / 1_000_000, (int)(remaining % 1_000_000));
                            } else wait();
                        } catch (InterruptedException wake) { if (interrupting) return; }
                    }
                    if (queue.isEmpty()) return;
                    item = queue.removeFirst();
                    running++;
                    closeQueued(item.queued);
                }
                if (!interrupting) Thread.interrupted();
                try { item.command.run(); }
                finally {
                    try {
                        if (item.futureAccepted) ((FutureTask<?>)item.command).removeQueueCopy(false);
                    } finally {
                        try { CompletableFuture.removedFromQueue(item.command, item.actionAccepted, false); }
                        finally { synchronized (this) { running--; pendingWork--; notifyAll(); } }
                    }
                }
                Activation.checkpoint();
            }
        } finally {
            synchronized (this) {
                removeWorker(current);
                if (!queue.isEmpty() && !interrupting) startWorker();
                settleIfTerminated();
                notifyAll();
            }
        }
    }

    private void settleIfTerminated() { settleIfTerminated(false); }
    private void settleIfTerminated(boolean root) {
        if ((shutdown || retiring) && queue.isEmpty() && workers.isEmpty()) settleOwner(root);
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
    // The coordinator is outside any logical Java fiber. Observing this value
    // must not try to suspend on a monitor held by a runnable factory/callback.
    @Override public boolean hasPendingWork() { return pendingWork != 0; }
    @Override public void closeAtRoot() {
        // This coordinator hook runs outside a Java Fiber, only after every
        // pool reports no queued/running callback. It must never acquire a
        // suspendable monitor. Interrupting known idle waits enqueues their
        // ordinary resumed finally paths; workers keep their physical owners.
        retiring = true;
        for (Thread worker : workers) worker.interrupt();
        if (workers.isEmpty()) settleIfTerminated(true);
    }
    @Override public synchronized void shutdown() { shutdown = true; notifyAll(); settleIfTerminated(); }
    @Override public synchronized List<Runnable> shutdownNow() {
        shutdown = interrupting = true;
        List<Runnable> pending = new ArrayList<>(queue.size());
        while (!queue.isEmpty()) {
            Item item = queue.removeFirst(); pendingWork--; pending.add(item.command); closeQueued(item.queued);
            if (item.futureAccepted) ((FutureTask<?>)item.command).removeQueueCopy(true);
            CompletableFuture.removedFromQueue(item.command, item.actionAccepted, true);
        }
        // Standard shutdownNow returns queued tasks without cancelling them.
        // They no longer own an accepted pending execution in this activation.
        for (Thread worker : workers) worker.interrupt();
        notifyAll();
        settleIfTerminated();
        return pending;
    }
    @Override public synchronized boolean isShutdown() { return shutdown || retiring; }
    @Override public synchronized boolean isTerminated() { return (shutdown || retiring) && owner == null; }
    @Override public boolean awaitTermination(long timeout, TimeUnit unit) throws InterruptedException {
        long nanos = Objects.requireNonNull(unit).toNanos(timeout);
        long started = System.nanoTime();
        synchronized (this) {
            if (isTerminated()) return true;
            if (Thread.interrupted()) throw new InterruptedException();
            if (nanos <= 0) return false;
            while (!isTerminated()) {
                long remaining = nanos - (System.nanoTime() - started);
                if (remaining <= 0) return false;
                wait(remaining / 1_000_000, (int)(remaining % 1_000_000));
            }
            return true;
        }
    }
}
