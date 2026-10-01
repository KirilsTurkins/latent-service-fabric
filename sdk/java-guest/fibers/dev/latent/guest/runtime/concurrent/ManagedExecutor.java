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
    private final ArrayDeque<Item> queue = new ArrayDeque<>();
    private final ArrayList<Thread> workers = new ArrayList<>();
    private Activation.Lease owner;
    private boolean shutdown;
    private boolean interrupting;
    private volatile boolean retiring;
    private int running;
    private volatile int pendingWork;

    private static final class Item {
        final Runnable command;
        final Activation.Lease queued;
        Item(Runnable command, Activation.Lease queued) { this.command = command; this.queued = queued; }
    }

    ManagedExecutor(int parallelism, ThreadFactory factory) {
        this(parallelism, factory, false);
    }
    ManagedExecutor(int parallelism, ThreadFactory factory, boolean cached) {
        if (parallelism <= 0) throw new IllegalArgumentException();
        this.parallelism = parallelism;
        this.factory = Objects.requireNonNull(factory);
        this.cached = cached;
        owner = Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.Executor);
        try { Activation.manage(this); }
        catch (Throwable error) { owner.close(); owner = null; throw error; }
    }

    @Override public synchronized void execute(Runnable command) {
        Objects.requireNonNull(command);
        if (shutdown || retiring || Activation.closing() && !Activation.acceptedContinuation())
            throw new java.util.concurrent.RejectedExecutionException("activation-executor-closed");
        Activation.Lease queued = Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork);
        FutureTask<?> future = command instanceof FutureTask<?> ? (FutureTask<?>)command : null;
        boolean acceptedResult = false;
        Item item = null;
        boolean installed = false;
        try {
            if (future != null) acceptedResult = future.accept();
            item = new Item(command, queued);
            queue.addLast(item);
            pendingWork++;
            installed = true;
            if (workers.size() < parallelism && (!cached || queue.size() > workers.size() - running)) startWorker();
            notifyAll();
        } catch (Throwable error) {
            if (!installed || queue.remove(item)) {
                if (installed) pendingWork--;
                queued.close();
                if (acceptedResult) future.rejectAcceptance();
            }
            throw error;
        }
    }

    private void startWorker() {
        Thread thread = factory.newThread(this::work);
        if (thread == null || thread.isAlive()) throw new java.util.concurrent.RejectedExecutionException("activation-thread-factory");
        workers.add(thread);
        try { Activation.startManaged(thread); }
        catch (Throwable error) { workers.remove(thread); throw error; }
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
                            if (cached) {
                                long remaining = 60_000_000_000L - (System.nanoTime() - idleStart);
                                if (remaining <= 0) return;
                                wait(remaining / 1_000_000, (int)(remaining % 1_000_000));
                            } else wait();
                        } catch (InterruptedException wake) { if (interrupting) return; }
                    }
                    if (queue.isEmpty()) return;
                    item = queue.removeFirst();
                    running++;
                    item.queued.close();
                }
                if (!interrupting) Thread.interrupted();
                try { item.command.run(); }
                finally { synchronized (this) { running--; pendingWork--; notifyAll(); } }
                Activation.checkpoint();
            }
        } finally {
            synchronized (this) {
                workers.remove(current);
                if (!queue.isEmpty() && !interrupting) startWorker();
                settleIfTerminated();
                notifyAll();
            }
        }
    }

    private void settleIfTerminated() {
        if ((shutdown || retiring) && queue.isEmpty() && workers.isEmpty() && owner != null) {
            owner.close();
            owner = null;
        }
    }
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
        if (workers.isEmpty()) settleIfTerminated();
    }
    @Override public synchronized void shutdown() { shutdown = true; notifyAll(); settleIfTerminated(); }
    @Override public synchronized List<Runnable> shutdownNow() {
        shutdown = interrupting = true;
        List<Runnable> pending = new ArrayList<>(queue.size());
        while (!queue.isEmpty()) { Item item = queue.removeFirst(); pendingWork--; pending.add(item.command); item.queued.close(); }
        // Standard shutdownNow returns queued tasks without cancelling them.
        // They no longer own an accepted pending execution in this activation.
        for (Runnable command : pending) if (command instanceof FutureTask<?>) ((FutureTask<?>)command).rejectAcceptance();
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
