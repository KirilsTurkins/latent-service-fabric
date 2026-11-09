package dev.latent.guest.runtime.util;

/** Standard task state is independent of its physical queue/worker owners. */
public abstract class TimerTask implements Runnable {
    static final int VIRGIN = 0, SCHEDULED = 1, EXECUTED = 2, CANCELLED = 3;
    // Applications may use a TimerTask's public monitor independently. Only
    // this monitor protects the scheduler's task state and association.
    final Object stateLock = new Object();
    int state;
    long lastScheduled;
    Timer timer;

    protected TimerTask() { }

    @Override public abstract void run();

    public boolean cancel() {
        boolean scheduled;
        Timer selected;
        synchronized (stateLock) {
            scheduled = state == SCHEDULED;
            state = CANCELLED;
            selected = timer;
        }
        if (selected != null) selected.taskCancelled();
        return scheduled;
    }

    public long scheduledExecutionTime() {
        synchronized (stateLock) { return lastScheduled; }
    }
}
