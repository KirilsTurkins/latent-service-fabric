package dev.latent.guest.runtime.util;

import dev.latent.generated.Bindings;
import dev.latent.guest.runtime.Activation;
import java.util.ArrayList;
import java.util.Date;
import java.util.Objects;

/** One managed logical worker and an admitted finite queue per ordinary timer. */
public class Timer implements Activation.ManagedPool {
    private static int serial;
    private final Object lock = new Object();
    private final ArrayList<Entry> queue = new ArrayList<>();
    private final Thread worker;
    private Activation.Lease owner;
    private boolean cancelled;
    private volatile boolean retiring;
    private volatile int pendingWork;

    private static final class Entry {
        final TimerTask task;
        final long period;
        long next;
        Activation.Lease queued;
        Entry(TimerTask task, long next, long period, Activation.Lease queued) {
            this.task = task; this.next = next; this.period = period; this.queued = queued;
        }
        void release() {
            if (queued != null) { queued.close(); queued = null; }
        }
    }

    private static synchronized String nextName() { return "Timer-" + serial++; }
    public Timer() { this(nextName(), false); }
    public Timer(boolean daemon) { this(nextName(), daemon); }
    public Timer(String name) { this(name, false); }
    public Timer(String name, boolean daemon) {
        Objects.requireNonNull(name);
        worker = new Thread(this::work, name);
        worker.setDaemon(daemon);
        owner = Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.Executor);
        try {
            Activation.manage(this);
            Activation.startManaged(worker);
        } catch (Throwable error) {
            cancelled = true;
            owner.close(); owner = null;
            throw error;
        }
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
    public void schedule(TimerTask task, long delay, long period) { scheduleAt(task, after(delay), period(period, false)); }
    public void schedule(TimerTask task, Date time, long period) {
        scheduleAt(task, Objects.requireNonNull(time).getTime(), period(period, false));
    }
    public void scheduleAtFixedRate(TimerTask task, long delay, long period) {
        scheduleAt(task, after(delay), period(period, true));
    }
    public void scheduleAtFixedRate(TimerTask task, Date time, long period) {
        scheduleAt(task, Objects.requireNonNull(time).getTime(), period(period, true));
    }

    private void scheduleAt(TimerTask task, long time, long period) {
        Objects.requireNonNull(task);
        if (time < 0) throw new IllegalArgumentException("negative timer deadline");
        synchronized (lock) {
            if (cancelled || retiring || Activation.closing() && !Activation.acceptedContinuation())
                throw new IllegalStateException("activation-timer-closed");
            synchronized (task) {
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
                    queued.close();
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
            synchronized (entry.task) { entry.task.timer = null; }
            entry.release();
            pendingWork--;
        }
    }

    private void work() {
        try {
            while (true) {
                Entry entry;
                synchronized (lock) {
                    while (queue.isEmpty() && !cancelled && !retiring) {
                        try { lock.wait(); } catch (InterruptedException wake) { }
                    }
                    if (cancelled || retiring) return;
                    int index = first();
                    entry = queue.get(index);
                    long remaining;
                    synchronized (entry.task) {
                        if (entry.task.state == TimerTask.CANCELLED) {
                            entry.task.timer = null;
                            queue.remove(index); entry.release(); pendingWork--; continue;
                        }
                        long now = System.currentTimeMillis();
                        remaining = entry.next - now;
                        if (remaining <= 0) {
                            pendingWork++;
                            entry.task.lastScheduled = entry.period < 0 ? now : entry.next;
                            if (entry.period == 0) {
                                queue.remove(index); entry.task.state = TimerTask.EXECUTED;
                                entry.task.timer = null;
                                entry.release(); pendingWork--;
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
                try { entry.task.run(); }
                finally { synchronized (lock) { pendingWork--; } }
                Activation.checkpoint();
            }
        } finally {
            synchronized (lock) {
                cancelled = true;
                clearQueue();
                if (owner != null) { owner.close(); owner = null; }
                lock.notifyAll();
            }
        }
    }

    public void cancel() {
        synchronized (lock) {
            cancelled = true;
            clearQueue();
            lock.notifyAll();
        }
    }

    void taskCancelled() { synchronized (lock) { lock.notifyAll(); } }

    public int purge() {
        synchronized (lock) {
            int removed = 0;
            for (int i = queue.size() - 1; i >= 0; i--) {
                Entry entry = queue.get(i);
                synchronized (entry.task) {
                    if (entry.task.state != TimerTask.CANCELLED) continue;
                    entry.task.timer = null;
                }
                queue.remove(i); entry.release(); pendingWork--; removed++;
            }
            if (removed != 0) lock.notifyAll();
            return removed;
        }
    }

    @Override public boolean hasPendingWork() { return pendingWork != 0; }
    @Override public void closeAtRoot() {
        // The coordinator observes an idle queue without taking a suspendable
        // monitor. The known worker wakes and retires through its real finally.
        retiring = true;
        worker.interrupt();
    }
}
