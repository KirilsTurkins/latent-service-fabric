package dev.latent.guest.runtime.util;

import dev.latent.generated.Bindings;
import dev.latent.guest.runtime.Activation;
import java.util.ArrayList;
import java.util.Date;
import java.util.Objects;

/** One managed logical worker and an admitted finite queue per ordinary timer. */
public class Timer implements Activation.ManagedPool {
    private static int serial;
    private static final Object serialLock = new Object();
    private final Object lock = new Object();
    private final ArrayList<Entry> queue = new ArrayList<>();
    private final Thread worker;
    private volatile Activation.Lease owner;
    private boolean ownerSettlementAttempted;
    private boolean cancelled;
    private volatile boolean retiring;
    private volatile int pendingWork;

    private static final class Entry {
        final TimerTask task;
        final long period;
        long next;
        Activation.Lease queued;
        boolean invoking;
        boolean withdrawn;
        Entry(TimerTask task, long next, long period, Activation.Lease queued) {
            this.task = task; this.next = next; this.period = period; this.queued = queued;
        }
        void release() {
            Activation.Lease held = queued;
            if (held == null) return;
            // Mark the only settlement attempt before the host call. A lost
            // acknowledgement retains this exact lease and poisons the Store.
            queued = null;
            try { held.close(); }
            catch (Throwable uncertain) {
                Activation.fenceUncertainQueuedWorkSettlement(held);
                throw uncertain;
            }
        }
        void withdraw() {
            withdrawn = true;
            if (!invoking) release();
        }
        void returned() {
            invoking = false;
            if (withdrawn) release();
        }
    }

    private static final class Worker implements Runnable {
        private Timer timer;
        Worker(Timer timer) { this.timer = timer; }
        @Override public void run() {
            Timer current = timer;
            if (current == null) return;
            try { current.work(); } finally { clear(); }
        }
        void clear() { timer = null; }
    }

    private static String nextName() {
        int value;
        synchronized (serialLock) { value = serial++; }
        return "Timer-" + value;
    }
    public Timer() { this(nextName(), false); }
    public Timer(boolean daemon) { this(nextName(), daemon); }
    public Timer(String name) { this(name, false); }
    public Timer(String name, boolean daemon) {
        Objects.requireNonNull(name);
        Worker target = new Worker(this);
        worker = new Thread(target, name);
        worker.setDaemon(daemon);
        owner = Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.Executor);
        try {
            Activation.manage(this);
            Activation.startManaged(worker, this);
        } catch (Throwable error) {
            synchronized (lock) {
                cancelled = true;
                // A failed start may still own an accepted worker or a
                // rollback-uncertain registration. Keep the executor lease
                // until that worker's actual finally, or Store destruction.
                if (!Activation.alive(worker)) {
                    target.clear();
                    try { settleOwner(); }
                    catch (Throwable uncertain) { /* preserve the original start failure */ }
                }
                // An already-entered worker may be waiting on this timer.
                lock.notifyAll();
            }
            throw error;
        }
    }

    // Both constructor rollback and the worker's finally can reach here.
    // The timer lock protects a single settlement attempt and keeps a failed
    // lease rooted through Store teardown, including lost acknowledgements.
    private void settleOwner() {
        if (owner == null || ownerSettlementAttempted) return;
        ownerSettlementAttempted = true;
        Activation.Lease held = owner;
        try { held.close(); }
        catch (Throwable uncertain) {
            Activation.fenceUncertainQueuedWorkSettlement(held);
            throw uncertain;
        }
        owner = null;
        Activation.unmanageRetired(this);
    }

    private static long after(long delay) {
        if (delay < 0) throw new IllegalArgumentException("negative delay");
        long time = System.currentTimeMillis() + delay;
        if (time < 0) throw new IllegalArgumentException("timer deadline overflow");
        return time;
    }
    private static long period(long value, boolean rate) {
        if (value <= 0) throw new IllegalArgumentException("non-positive period");
        // Match the reference timer's overflow margin for extreme periods.
        if (value > Long.MAX_VALUE / 2) value >>= 1;
        return rate ? value : -value;
    }

    public void schedule(TimerTask task, long delay) { scheduleAt(task, after(delay), 0); }
    public void schedule(TimerTask task, Date time) { scheduleAt(task, Objects.requireNonNull(time).getTime(), 0); }
    public void schedule(TimerTask task, long delay, long period) {
        if (delay < 0) throw new IllegalArgumentException("negative delay");
        long selectedPeriod = period(period, false);
        scheduleAt(task, after(delay), selectedPeriod);
    }
    public void schedule(TimerTask task, Date time, long period) {
        long selectedPeriod = period(period, false);
        scheduleAt(task, Objects.requireNonNull(time).getTime(), selectedPeriod);
    }
    public void scheduleAtFixedRate(TimerTask task, long delay, long period) {
        if (delay < 0) throw new IllegalArgumentException("negative delay");
        long selectedPeriod = period(period, true);
        scheduleAt(task, after(delay), selectedPeriod);
    }
    public void scheduleAtFixedRate(TimerTask task, Date time, long period) {
        long selectedPeriod = period(period, true);
        scheduleAt(task, Objects.requireNonNull(time).getTime(), selectedPeriod);
    }

    private void scheduleAt(TimerTask task, long time, long period) {
        if (time < 0) throw new IllegalArgumentException("negative timer deadline");
        synchronized (lock) {
            if (cancelled || retiring || Activation.closing() && !Activation.acceptedContinuation())
                throw new IllegalStateException("activation-timer-closed");
            Objects.requireNonNull(task);
            synchronized (task.stateLock) {
                if (task.state != TimerTask.VIRGIN) throw new IllegalStateException("timer task already scheduled or cancelled");
                Activation.Lease queued = Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork);
                Entry entry = null;
                try {
                    entry = new Entry(task, time, period, queued);
                    queue.add(entry);
                    task.state = TimerTask.SCHEDULED;
                    task.timer = this;
                    pendingWork++;
                } catch (Throwable error) {
                    if (entry != null) queue.remove(entry);
                    try {
                        if (entry != null) entry.withdraw();
                        else {
                            try { queued.close(); }
                            catch (Throwable uncertain) {
                                Activation.fenceUncertainQueuedWorkSettlement(queued);
                                throw uncertain;
                            }
                        }
                    } catch (Throwable uncertain) { /* retain original admission error */ }
                    throw error;
                }
            }
            lock.notifyAll();
        }
    }

    private int first() {
        int selected = 0;
        for (int i = 1; i < queue.size(); i++) if (queue.get(i).next < queue.get(selected).next) selected = i;
        return selected;
    }

    private void clearQueue() {
        while (!queue.isEmpty()) {
            Entry entry = queue.remove(queue.size() - 1);
            synchronized (entry.task.stateLock) { entry.task.timer = null; }
            entry.withdraw(); pendingWork--;
        }
    }

    private void work() {
        Throwable primary = null;
        try {
            while (true) {
                Entry entry;
                synchronized (lock) {
                    while (queue.isEmpty() && !cancelled && !retiring) {
                        try { lock.wait(); } catch (InterruptedException wake) { }
                    }
                    if (cancelled || retiring) return;
                    // Cancellation may target a later entry behind a long-lived
                    // recurring task. Reclaim those entries on this worker turn
                    // instead of keeping their owners until their deadlines.
                    purgeCancelled();
                    if (queue.isEmpty()) continue;
                    int index = first();
                    entry = queue.get(index);
                    long remaining;
                    synchronized (entry.task.stateLock) {
                        if (entry.task.state == TimerTask.CANCELLED) {
                            entry.task.timer = null;
                            queue.remove(index);
                            entry.withdraw(); pendingWork--;
                            continue;
                        }
                        long now = System.currentTimeMillis();
                        remaining = entry.next - now;
                        if (remaining <= 0) {
                            entry.invoking = true;
                            pendingWork++;
                            entry.task.lastScheduled = entry.period < 0 ? now : entry.next;
                            if (entry.period == 0) {
                                queue.remove(index); entry.task.state = TimerTask.EXECUTED;
                                entry.task.timer = null;
                                entry.withdraw(); pendingWork--;
                            } else {
                                long step = entry.period < 0 ? -entry.period : entry.period;
                                long base = entry.period < 0 ? now : entry.next;
                                entry.next = base > Long.MAX_VALUE - step ? Long.MAX_VALUE : base + step;
                            }
                        }
                    }
                    if (remaining > 0) {
                        try { lock.wait(remaining); } catch (InterruptedException wake) { }
                        continue;
                    }
                }
                Throwable callbackFailure = null;
                try { entry.task.run(); }
                catch (Throwable error) { callbackFailure = error; throw error; }
                finally {
                    synchronized (lock) {
                        try { entry.returned(); pendingWork--; }
                        catch (Throwable uncertain) {
                            if (callbackFailure == null) throw uncertain;
                        }
                    }
                }
                Activation.checkpoint();
            }
        } catch (Throwable error) {
            primary = error;
            throw error;
        } finally {
            synchronized (lock) {
                cancelled = true;
                try {
                    clearQueue();
                    if (pendingWork != 0) Activation.fenceUncertainResultSettlement();
                    else settleOwner();
                } catch (Throwable cleanupFailure) {
                    // The Timer still owns any unretired pool or queue entries.
                    // Never allow completion after an uncertain cleanup.
                    Activation.fenceUncertainResultSettlement();
                    if (primary == null) throw cleanupFailure;
                } finally { lock.notifyAll(); }
            }
        }
    }

    public void cancel() {
        synchronized (lock) {
            cancelled = true;
            try { clearQueue(); } finally { lock.notifyAll(); }
        }
    }

    void taskCancelled() { synchronized (lock) { lock.notifyAll(); } }

    // Caller holds the Timer lock before acquiring each task's state lock.
    private int purgeCancelled() {
        int removed = 0;
        for (int i = queue.size() - 1; i >= 0; i--) {
            Entry entry = queue.get(i);
            synchronized (entry.task.stateLock) {
                if (entry.task.state != TimerTask.CANCELLED) continue;
                entry.task.timer = null;
            }
            queue.remove(i);
            entry.withdraw(); pendingWork--;
            removed++;
        }
        return removed;
    }

    public int purge() {
        synchronized (lock) {
            int removed = purgeCancelled();
            if (removed != 0) lock.notifyAll();
            return removed;
        }
    }

    @Override public boolean isRetired() { return owner == null; }
    @Override public boolean hasPendingWork() { return pendingWork != 0; }
    @Override public void closeAtRoot() {
        // The coordinator observes an idle queue without taking a suspendable
        // monitor. The known worker wakes and retires through its real finally.
        retiring = true;
        worker.interrupt();
    }
}
