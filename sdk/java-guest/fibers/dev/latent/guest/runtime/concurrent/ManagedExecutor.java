package dev.latent.guest.runtime.concurrent;

import dev.latent.generated.Bindings;
import dev.latent.guest.runtime.Activation;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.TimeUnit;

/** An independent FIFO pool of maintained Java fibers, never a host thread pool. */
final class ManagedExecutor extends AbstractExecutorService implements Activation.ManagedPool {
    private final int parallelism;
    private final ThreadFactory factory;
    private final boolean cached;
    private final boolean expireIdle;
    private final ArrayDeque<Item> queue = new ArrayDeque<>();
    // Root retirement runs outside a suspendable pool monitor. Its iterator
    // must remain valid if a worker retires during an interrupt callback.
    private final List<Thread> workers = new CopyOnWriteArrayList<>();
    private volatile Activation.Lease owner;
    private final java.util.concurrent.atomic.AtomicBoolean ownerSettlementStarted =
        new java.util.concurrent.atomic.AtomicBoolean();
    // Status observations must remain available while an application holds
    // the executor monitor or a worker interrupt hook runs under it.
    private volatile boolean shutdown;
    private volatile boolean interrupting;
    private volatile boolean retiring;
    private int running;
    private volatile int pendingWork;
    // A reentrant factory must not create a second worker for this slot.
    private volatile int startingWorkers;
    // A pool worker can be published before its Activation Work is registered.
    private volatile int enteringWorkers;
    // Worker-creating first tasks stay out of the public FIFO until startup resolves.
    private Item reservedFirsts;
    // Only workers actually entering a cached idle wait are eligible for a handoff.
    private Worker idleWorkers;
    private static final int RESERVED = 0, TRANSFERRING = 1, CLAIMING = 2,
        CLAIMED = 3, WITHDRAWING = 4, WITHDRAWN = 5, QUARANTINED = 6,
        SETTLING = 7, QUEUED = 8, HANDOFF = 9;
    // Never reuse a preference: an accepted but unstarted worker can outlive
    // withdrawal of its entry. Zero means there is no preference.
    private long nextPreference;

    private static final class Item {
        final Runnable command;
        final Activation.Lease queued;
        boolean actionAccepted;
        boolean futureAccepted;
        long preference;
        Item nextReserved;
        int transferState;
        boolean uncertainStart;
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

    @Override public void execute(Runnable command) {
        executeManaged(command);
    }

    // Historical path retained for compatibility with existing source controls;
    // application dispatch and replacement startup do not call it.
    private synchronized void executeLegacy(Runnable command) {
        Objects.requireNonNull(command);
        Activation.Lease queued = null;
        FutureTask<?> future = command instanceof FutureTask<?> ? (FutureTask<?>)command : null;
        boolean acceptedResult = false;
        boolean acceptedAction = false;
        Item item = null;
        boolean installed = false;
        boolean fallbackAccepted = false;
        boolean withdrawnForShutdown = false;
        boolean counted = false, linked = false;
        try {
            if (shutdown || retiring || Activation.closing() && !Activation.acceptedContinuation())
                throw new java.util.concurrent.RejectedExecutionException("activation-executor-closed");
            if (Activation.admissionPoisoned()) throw new IllegalStateException("activation-runtime-poisoned-store");
            if (pendingWork == Integer.MAX_VALUE)
                throw new java.util.concurrent.RejectedExecutionException("activation-executor-pending-capacity");
            // Admission can reenter shutdown before the Queue lease returns.
            pendingWork++; counted = true;
            queued = Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork);
            item = new Item(command, queued, false, false);
            item.nextReserved = reservedFirsts; reservedFirsts = item; linked = true;
            if (shutdown || retiring)
                throw new java.util.concurrent.RejectedExecutionException("activation-executor-closed");
            if (future != null) item.futureAccepted = acceptedResult = future.acceptQueueCopy();
            item.actionAccepted = acceptedAction = CompletableFuture.acceptedByQueue(command);
            if (shutdown || retiring)
                throw new java.util.concurrent.RejectedExecutionException("activation-executor-closed");
            transferReserved(item);
            installed = true;
            if (workers.size() < parallelism && (!cached || queue.size() > workers.size() - running)) {
                if (cached) startWorker();
                else if (tryStartWorker(false, item)) {
                    if (soleGracefulShutdown(item)) {
                        var rejection = new java.util.concurrent.RejectedExecutionException("activation-executor-closed");
                        queue.removeFirst(); pendingWork--;
                        withdrawnForShutdown = true;
                        try {
                            closeQueued(queued);
                            if (acceptedResult) future.removeQueueCopy(true);
                            CompletableFuture.removedFromQueue(command, acceptedAction, true);
                            CompletableFuture.rejectedBeforeAcceptance(command, this);
                            // The startup finally saw the entry still queued;
                            // finish retirement only after its rollback.
                            settleIfTerminated();
                        } catch (Throwable uncertain) {
                            // The original rejection remains primary. A failed
                            // settlement keeps the activation from succeeding.
                            Activation.fenceUncertainCompletion();
                        } finally { notifyAll(); }
                        throw rejection;
                    }
                    deferAfterReentrantSubmissions(item);
                    if (workers.isEmpty() && startingWorkers == 0
                            && !interrupting && !retiring && !queue.isEmpty()) {
                        // Fixed pools retry once after the first null factory when
                        // no worker exists, keeping already-admitted queue owners.
                        fallbackAccepted = true;
                        tryStartWorker(true, null);
                    }
                }
            }
            notifyAll();
        } catch (Throwable error) {
            // Any fallback startup failure follows queue acceptance. Keep the
            // exact entry, or its existing physical disposition, owned.
            if (fallbackAccepted || withdrawnForShutdown) throw error;
            try {
                if (linked && reserved(item.queued) == item) {
                    if (item.transferState != QUARANTINED && !item.uncertainStart) rollbackReserved(item);
                } else if (!linked) {
                    if (queued != null) closeQueued(queued);
                    if (acceptedResult) future.removeQueueCopy(true);
                    CompletableFuture.removedFromQueue(command, acceptedAction, true);
                    CompletableFuture.rejectedBeforeAcceptance(command, this);
                    if (counted && !Activation.admissionPoisoned()) pendingWork--;
                } else if (installed && queue.remove(item)) {
                    item.transferState = RESERVED; item.nextReserved = reservedFirsts; reservedFirsts = item;
                    rollbackReserved(item);
                }
                settleIfTerminated();
            } catch (Throwable uncertain) { Activation.fenceUncertainCompletion(); }
            finally { notifyAll(); }
            throw error;
        }
    }

    // A reserved Item is charged to its original QueuedWork/Result owners.
    // The prospective Worker keeps only that Queue lease's identity.
    private Item reserved(Activation.Lease lease) {
        for (Item item = reservedFirsts; item != null; item = item.nextReserved)
            if (item.queued == lease) return item;
        return null;
    }

    private void unlinkReserved(Item selected) {
        Item previous = null;
        for (Item item = reservedFirsts; item != null; item = item.nextReserved) {
            if (item == selected) {
                if (previous == null) reservedFirsts = item.nextReserved;
                else previous.nextReserved = item.nextReserved;
                item.nextReserved = null;
                return;
            }
            previous = item;
        }
    }

    private void rollbackReserved(Item item) {
        item.transferState = SETTLING;
        try {
            closeQueued(item.queued);
            if (item.futureAccepted) ((FutureTask<?>)item.command).removeQueueCopy(true);
            CompletableFuture.removedFromQueue(item.command, item.actionAccepted, true);
            CompletableFuture.rejectedBeforeAcceptance(item.command, this);
            if (Activation.admissionPoisoned()) { item.transferState = QUARANTINED; return; }
            pendingWork--;
            unlinkReserved(item);
        } catch (Throwable uncertain) {
            // Keep the same Item and any unsettled owners rooted until teardown.
            item.transferState = QUARANTINED;
            Activation.fenceUncertainCompletion();
            throw uncertain;
        }
    }

    // A null factory turns the original first into ordinary queued work. Keep
    // custody during insertion: a reentrant claim/withdrawal may already own
    // its disposition when a synthetic insertion failure propagates.
    private void transferReserved(Item item) {
        item.transferState = TRANSFERRING;
        try { queue.addLast(item); }
        catch (Throwable error) {
            if (item.transferState == CLAIMED || item.transferState == WITHDRAWN) {
                unlinkReserved(item);
            } else if (item.transferState == CLAIMING || item.transferState == WITHDRAWING) {
                // The physical owner is still settling this exact Item.
                item.uncertainStart = true;
            } else if (item.transferState != QUARANTINED) {
                try {
                    if (queue.remove(item)) item.transferState = RESERVED;
                    else {
                        item.transferState = QUARANTINED;
                        Activation.fenceUncertainCompletion();
                    }
                } catch (Throwable uncertain) {
                    item.transferState = QUARANTINED;
                    Activation.fenceUncertainCompletion();
                }
            }
            throw error;
        }
        // An in-flight claim or withdrawal clears its own retained Item only
        // after its original settlement is acknowledged.
        if (item.transferState == QUARANTINED) {
            Activation.fenceUncertainCompletion();
            throw new IllegalStateException("activation-executor-transfer-uncertain");
        }
        if (item.transferState != CLAIMING && item.transferState != WITHDRAWING) {
            if (item.transferState == TRANSFERRING) item.transferState = QUEUED;
            unlinkReserved(item);
        }
    }

    private void executeManaged(Runnable command) {
        Objects.requireNonNull(command);
        Activation.Lease queued = null;
        FutureTask<?> future = command instanceof FutureTask<?> ? (FutureTask<?>)command : null;
        boolean acceptedResult = false, acceptedAction = false, linked = false, counted = false;
        Item item = null;
        Worker handoff = null;
        try {
            synchronized (this) {
                if (shutdown || retiring || Activation.closing() && !Activation.acceptedContinuation())
                    throw new java.util.concurrent.RejectedExecutionException("activation-executor-closed");
                if (Activation.admissionPoisoned()) throw new IllegalStateException("activation-runtime-poisoned-store");
                if (pendingWork == Integer.MAX_VALUE)
                    throw new java.util.concurrent.RejectedExecutionException("activation-executor-pending-capacity");
                // Keep the pool owned across reentrant host admission.
                pendingWork++; counted = true;
                queued = Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork);
                item = new Item(command, queued, false, false);
                item.nextReserved = reservedFirsts; reservedFirsts = item; linked = true;
                if (shutdown || retiring)
                    throw new java.util.concurrent.RejectedExecutionException("activation-executor-closed");
                if (future != null) item.futureAccepted = acceptedResult = future.acceptQueueCopy();
                item.actionAccepted = acceptedAction = CompletableFuture.acceptedByQueue(command);
                // A reentrant host call may have closed the pool after the
                // original pre-admission check.
                if (shutdown || retiring)
                    throw new java.util.concurrent.RejectedExecutionException("activation-executor-closed");
                // A cached handoff is committed only to a worker already in
                // its idle wait. Keep the same Item and Queue owner until it
                // physically claims them, including after shutdownNow.
                if (cached && queue.isEmpty()) {
                    handoff = takeIdleWorker();
                    if (handoff != null) {
                        item.transferState = HANDOFF;
                        handoff.firstLease = item.queued;
                        notifyAll();
                        return;
                    }
                }
                if (workers.size() >= parallelism - startingWorkers) {
                    transferReserved(item);
                    notifyAll();
                    return;
                }
                startingWorkers++;
                notifyAll();
            }
            startReservedWorker(item);
        } catch (Throwable error) {
            synchronized (this) {
                try {
                    if (handoff != null && handoff.firstLease == item.queued) handoff.firstLease = null;
                    if (linked && reserved(item.queued) == item) {
                        if (item.transferState != QUARANTINED && !item.uncertainStart) rollbackReserved(item);
                    } else if (!linked) {
                        if (queued != null) closeQueued(queued);
                        if (acceptedResult) future.removeQueueCopy(true);
                        CompletableFuture.removedFromQueue(command, acceptedAction, true);
                        CompletableFuture.rejectedBeforeAcceptance(command, this);
                        if (counted && !Activation.admissionPoisoned()) pendingWork--;
                    }
                    settleIfTerminated();
                } catch (Throwable uncertain) {
                    Activation.fenceUncertainCompletion();
                } finally { notifyAll(); }
            }
            throw error;
        }
    }

    // Each call owns one previously counted startingWorkers slot. Initial
    // first tasks remain reserved; fallback and replacement workers take FIFO.
    private void startReservedWorker(Item first) {
        Worker worker = null;
        boolean reservation = true, entering = false;
        Throwable failure = null;
        try {
            worker = new Worker(this, first == null ? null : first.queued);
            Thread thread = factory.newThread(worker::run);
            if (thread == null) {
                worker.clear();
                if (cached) throw new java.util.concurrent.RejectedExecutionException("activation-thread-factory");
                boolean fallback = false;
                synchronized (this) {
                    if (first != null) {
                        if (shutdown || retiring)
                            throw new java.util.concurrent.RejectedExecutionException("activation-executor-closed");
                        transferReserved(first);
                    }
                    startingWorkers--; reservation = false;
                    if (first != null && workers.isEmpty() && startingWorkers == 0
                            && !interrupting && !retiring && !queue.isEmpty()) {
                        startingWorkers++; fallback = true;
                    }
                    notifyAll();
                }
                if (fallback) startReservedWorker(null);
                return;
            }
            synchronized (this) {
                if (first != null && (shutdown || retiring)) {
                    worker.clear();
                    throw new java.util.concurrent.RejectedExecutionException("activation-executor-closed");
                }
                if (first == null && (interrupting || retiring)) { worker.clear(); return; }
                int addedAt = -1;
                try {
                    if (thread.isAlive() && (first == null || cached)) throw new IllegalThreadStateException();
                    if (thread.isAlive())
                        throw new java.util.concurrent.RejectedExecutionException("activation-thread-factory");
                    // A second factory can return the same NEW Thread while
                    // the first start is still entering Activation. Do not
                    // confuse that existing Work with this reservation.
                    for (Thread existing : workers)
                        if (existing == thread) throw new IllegalThreadStateException();
                    if (Activation.alive(thread)) throw new IllegalThreadStateException();
                    addedAt = workers.size(); workers.add(thread); worker.prepare(thread);
                } catch (Throwable error) {
                    worker.clear();
                    try {
                        if (addedAt >= 0 && addedAt < workers.size() && workers.get(addedAt) == thread)
                            workers.remove(addedAt);
                    } catch (Throwable uncertain) { Activation.fenceUncertainCompletion(); }
                    throw error;
                }
                // Root cannot pass between publishing this Thread and the
                // original Activation Work registration.
                enteringWorkers++; startingWorkers--; reservation = false; entering = true;
            }
            try { Activation.startManaged(thread, this); }
            catch (Throwable error) {
                synchronized (this) {
                    if (!Activation.ownsManaged(thread, this)) {
                        try { removeWorker(thread); }
                        catch (Throwable uncertain) { Activation.fenceUncertainCompletion(); }
                        worker.clear();
                    } else if (first != null && reserved(first.queued) == first) {
                        first.uncertainStart = true;
                    }
                }
                throw error;
            }
        } catch (Throwable error) {
            failure = error;
            if (worker != null && !entering) worker.clear();
            throw error;
        } finally {
            synchronized (this) {
                if (reservation) startingWorkers--;
                if (entering) enteringWorkers--;
                try { settleIfTerminated(); }
                catch (Throwable uncertain) { if (failure == null) throw uncertain; }
                finally { notifyAll(); }
            }
        }
    }

    // TeaVM retains a completed Thread's Runnable; do not let that target
    // retain an otherwise retired executor through the thread identity ledger.
    private static final class Worker {
        private volatile ManagedExecutor pool;
        private volatile Thread thread;
        private volatile long first;
        private volatile Activation.Lease firstLease;
        private Worker nextIdle;
        private boolean idle;
        Worker(ManagedExecutor pool, long first) { this.pool = pool; this.first = first; }
        Worker(ManagedExecutor pool, Activation.Lease firstLease) { this.pool = pool; this.firstLease = firstLease; }
        void prepare(Thread thread) { this.thread = thread; }
        void run() {
            ManagedExecutor current = pool;
            Thread expected = thread;
            if (current == null || expected == null || expected != Thread.currentThread()
                    || !Activation.runningManaged(expected, current)) return;
            try { current.work(this); } finally { clear(); }
        }
        void clear() { pool = null; thread = null; first = 0; firstLease = null; nextIdle = null; idle = false; }
    }

    // Callers hold the pool monitor. These links never retain an Item or an
    // application command; every live worker already has its original owner.
    private void registerIdle(Worker worker) {
        if (worker.idle || worker.firstLease != null) {
            Activation.fenceUncertainCompletion();
            throw new IllegalStateException("activation-executor-idle-worker-state");
        }
        worker.nextIdle = idleWorkers; worker.idle = true; idleWorkers = worker;
    }

    private Worker takeIdleWorker() {
        Worker worker = idleWorkers;
        if (worker == null) return null;
        if (!worker.idle || worker.firstLease != null || worker.pool != this || worker.thread == null) {
            Activation.fenceUncertainCompletion();
            throw new IllegalStateException("activation-executor-idle-worker-state");
        }
        idleWorkers = worker.nextIdle; worker.nextIdle = null; worker.idle = false;
        return worker;
    }

    private void unregisterIdle(Worker selected) {
        if (!selected.idle) return;
        Worker previous = null;
        for (Worker worker = idleWorkers; worker != null; worker = worker.nextIdle) {
            if (worker == selected) {
                if (previous == null) idleWorkers = worker.nextIdle;
                else previous.nextIdle = worker.nextIdle;
                worker.nextIdle = null; worker.idle = false;
                return;
            }
            previous = worker;
        }
        Activation.fenceUncertainCompletion();
        throw new IllegalStateException("activation-executor-idle-worker-lost");
    }

    private void startWorker() {
        if (tryStartWorker(false, null)) throw new java.util.concurrent.RejectedExecutionException("activation-thread-factory");
    }

    // True means no worker was admitted after a null factory or a graceful
    // shutdown with only this submission queued. False also covers a
    // reentrant call whose worker slot was already reserved.
    private boolean tryStartWorker(boolean fallback, Item first) {
        // Callers hold the pool monitor, including reentrant admissions.
        if (workers.size() >= parallelism - startingWorkers) return false;
        startingWorkers++;
        boolean transferred = false;
        Throwable failure = null;
        try {
            long preference = 0;
            if (first != null && nextPreference != Long.MAX_VALUE) {
                preference = ++nextPreference;
                first.preference = preference;
            }
            Worker worker = new Worker(this, preference);
            Thread thread = null;
            int addedAt = -1;
            try {
                thread = factory.newThread(worker::run);
                if (thread == null) { worker.clear(); return true; }
                if (thread.isAlive()) {
                    if (fallback) throw new IllegalThreadStateException();
                    throw new java.util.concurrent.RejectedExecutionException("activation-thread-factory");
                }
                if (Activation.alive(thread)) throw new IllegalThreadStateException();
                if (soleGracefulShutdown(first)) { worker.clear(); return true; }
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
            // Transfer the reservation only once the worker registry carries it.
            startingWorkers--;
            transferred = true;
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
            return false;
        } catch (Throwable error) {
            failure = error;
            throw error;
        } finally {
            if (!transferred) startingWorkers--;
            try { settleIfTerminated(); }
            catch (Throwable uncertain) {
                // Keep the original startup failure when retirement also fails.
                if (failure == null) throw uncertain;
            }
            notifyAll();
        }
    }

    private void removeWorker(Thread thread) {
        for (int index = 0; index < workers.size(); index++) {
            if (workers.get(index) == thread) { workers.remove(index); return; }
        }
    }

    // Do not reject after the entry has run, been withdrawn, or other queued
    // work has already been accepted. Immediate shutdown has its own custody.
    private boolean soleGracefulShutdown(Item item) {
        return item != null && shutdown && !interrupting && queue.size() == 1 && queue.peekFirst() == item;
    }

    // The JDK enqueues the outer submission after a null factory returns, so
    // reentrant submissions precede it. All entries here are already owned;
    // rotate only under the pool monitor, without readmission or a larger deque.
    private void deferAfterReentrantSubmissions(Item outer) {
        int count = queue.size();
        if (count < 2 || queue.peekLast() == outer) return;
        Item current = null, delayed = null;
        try {
            for (int index = 0; index < count; index++) {
                current = queue.removeFirst();
                if (current == outer) delayed = current;
                else queue.addLast(current);
                current = null;
            }
        } finally {
            // Restore any detached entries before propagating a failure. Each
            // add replaces an entry removed above, so capacity does not grow.
            if (current != null && current != delayed) queue.addLast(current);
            if (delayed != null) queue.addLast(delayed);
        }
    }

    // Callers hold the pool monitor. A primitive hint has no custody of a
    // withdrawn task; only the still-owned, matching queue entry can be taken.
    private Item removePreferred(long preference) {
        if (preference == 0) return null;
        for (Iterator<Item> entries = queue.iterator(); entries.hasNext();) {
            Item candidate = entries.next();
            if (candidate.preference == preference) {
                entries.remove();
                return candidate;
            }
        }
        return null;
    }

    private void work(Worker worker) {
        Thread current = Thread.currentThread();
        try {
            while (true) {
                Item item;
                synchronized (this) {
                    Activation.Lease firstLease = worker.firstLease; worker.firstLease = null;
                    item = firstLease == null ? null : reserved(firstLease);
                    if (firstLease != null && item == null) {
                        Activation.fenceUncertainCompletion();
                        throw new IllegalStateException("activation-executor-handoff-lost");
                    }
                    if (item == null) {
                        long idleStart = System.nanoTime();
                        while (queue.isEmpty() && worker.firstLease == null && !shutdown && !retiring) {
                            long remaining = expireIdle ? 60_000_000_000L - (System.nanoTime() - idleStart) : 0;
                            if (expireIdle && remaining <= 0) return;
                            if (cached) registerIdle(worker);
                            try {
                                if (expireIdle) wait(remaining / 1_000_000, (int)(remaining % 1_000_000));
                                else wait();
                            } catch (InterruptedException wake) {
                                if (interrupting && worker.firstLease == null) return;
                            } finally { if (cached) unregisterIdle(worker); }
                        }
                        firstLease = worker.firstLease; worker.firstLease = null;
                        item = firstLease == null ? null : reserved(firstLease);
                        if (firstLease != null && item == null) {
                            Activation.fenceUncertainCompletion();
                            throw new IllegalStateException("activation-executor-handoff-lost");
                        }
                    }
                    if (item != null) {
                        if (retiring) {
                            item.transferState = QUARANTINED;
                            Activation.fenceUncertainCompletion();
                            return;
                        }
                        item.transferState = CLAIMED;
                        running++;
                        try { closeQueued(item.queued); }
                        catch (Throwable uncertain) { item.transferState = QUARANTINED; throw uncertain; }
                        unlinkReserved(item);
                    } else {
                        if (queue.isEmpty()) return;
                        long first = worker.first; worker.first = 0;
                        item = removePreferred(first);
                        if (item == null) item = queue.removeFirst();
                        boolean transferring = item.transferState == TRANSFERRING;
                        if (transferring) item.transferState = CLAIMING;
                        running++;
                        try { closeQueued(item.queued); }
                        catch (Throwable uncertain) {
                            if (transferring) item.transferState = QUARANTINED;
                            throw uncertain;
                        }
                        if (transferring) { item.transferState = CLAIMED; unlinkReserved(item); }
                    }
                }
                try {
                    // Startup hooks, idle waits, or host settlement may consume
                    // the stop wakeup. Recheck after clearing a non-stop flag so
                    // a concurrent shutdownNow cannot lose its interruption.
                    if ((interrupting || (Thread.interrupted() && interrupting)) && !current.isInterrupted())
                        current.interrupt();
                } catch (Throwable error) {
                    // Application Thread hooks can throw before the callback.
                    // Queue settlement already succeeded: keep this exact Item
                    // and its Result/action custody, without retrying that lease
                    // or pretending the accepted callback physically completed.
                    synchronized (this) {
                        item.transferState = QUARANTINED;
                        item.nextReserved = reservedFirsts; reservedFirsts = item;
                        Activation.fenceUncertainCompletion();
                    }
                    throw error;
                }
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
            boolean replacement = false;
            synchronized (this) {
                try { unregisterIdle(worker); }
                catch (Throwable uncertain) { Activation.fenceUncertainCompletion(); }
                Activation.Lease stranded = worker.firstLease; worker.firstLease = null;
                if (stranded != null) {
                    Item pending = reserved(stranded);
                    if (pending != null) pending.transferState = QUARANTINED;
                    Activation.fenceUncertainCompletion();
                }
                removeWorker(current);
                if (!queue.isEmpty() && !interrupting) {
                    if (!retiring && workers.size() < parallelism - startingWorkers
                            && (!cached || pendingWork > workers.size() + startingWorkers)) {
                        startingWorkers++; replacement = true;
                    }
                }
                settleIfTerminated();
                notifyAll();
            }
            if (replacement) startReservedWorker(null);
        }
    }

    private void settleIfTerminated() { settleIfTerminated(false); }
    private void settleIfTerminated(boolean root) {
        if ((shutdown || retiring) && queue.isEmpty() && pendingWork == 0
                && startingWorkers == 0 && enteringWorkers == 0 && workers.isEmpty()) settleOwner(root);
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
    @Override public boolean hasPendingWork() {
        return pendingWork != 0 || startingWorkers != 0 || enteringWorkers != 0;
    }
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
            Item item = queue.removeFirst();
            if (item.transferState == TRANSFERRING) {
                item.transferState = WITHDRAWING;
                try {
                    pending.add(item.command); closeQueued(item.queued);
                    if (item.futureAccepted) ((FutureTask<?>)item.command).removeQueueCopy(true);
                    CompletableFuture.removedFromQueue(item.command, item.actionAccepted, true);
                    pendingWork--; item.transferState = WITHDRAWN; unlinkReserved(item);
                } catch (Throwable uncertain) {
                    item.transferState = QUARANTINED;
                    Activation.fenceUncertainCompletion();
                    throw uncertain;
                }
            } else {
                pendingWork--; pending.add(item.command); closeQueued(item.queued);
                if (item.futureAccepted) ((FutureTask<?>)item.command).removeQueueCopy(true);
                CompletableFuture.removedFromQueue(item.command, item.actionAccepted, true);
            }
        }
        // Standard shutdownNow returns queued tasks without cancelling them.
        // They no longer own an accepted pending execution in this activation.
        for (Thread worker : workers) worker.interrupt();
        notifyAll();
        settleIfTerminated();
        return pending;
    }
    @Override public boolean isShutdown() { return shutdown || retiring; }
    @Override public boolean isTerminated() { return (shutdown || retiring) && owner == null; }
    @Override public boolean awaitTermination(long timeout, TimeUnit unit) throws InterruptedException {
        long nanos = Objects.requireNonNull(unit).toNanos(timeout);
        long started = System.nanoTime();
        synchronized (this) {
            if (isTerminated()) return true;
            // No wait occurs for a nonpositive timeout; preserve interruption.
            if (nanos <= 0) return false;
            if (Thread.interrupted()) throw new InterruptedException();
            while (!isTerminated()) {
                long remaining = nanos - (System.nanoTime() - started);
                if (remaining <= 0) return false;
                wait(remaining / 1_000_000, (int)(remaining % 1_000_000));
            }
            return true;
        }
    }
}
