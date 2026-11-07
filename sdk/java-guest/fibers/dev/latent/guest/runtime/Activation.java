package dev.latent.guest.runtime;

import dev.latent.generated.Bindings;
import dev.latent.guest.Option;
import dev.latent.guest.Unsigned64;
import java.util.IdentityHashMap;
import java.util.ArrayList;
import org.teavm.interop.Address;
import org.teavm.interop.Export;
import org.teavm.runtime.EventQueue;
import org.teavm.runtime.Fiber;

/** Activation entry and ownership beneath the maintained TeaVM logical threads.
 * The initial port is opt-in until the complete standard profile is qualified. */
public final class Activation {
    private static final IdentityHashMap<Thread, Work> threads = new IdentityHashMap<>();
    private static final ArrayList<ManagedPool> pools = new ArrayList<>();
    private static final ArrayList<TimerLease> timers = new ArrayList<>();
    private static boolean entered;
    private static boolean rootComplete;
    private static boolean closing;
    private static boolean retiringPools;
    private static boolean iteratingPoolRetirement;
    private static volatile boolean poisoned;
    private static Work failedStarts;
    private static Address result;
    private static Throwable failure;
    private static Work root;
    private static java.util.concurrent.Executor defaultAsyncExecutor;
    private static boolean queueClockCaptured;
    private static long queueClock;

    private Activation() { }

    private static final class Work {
        Bindings.LatentRuntimeActivationToken token;
        boolean complete;
        boolean prepared;
        boolean managed;
        ManagedPool pool;
        Thread failedThread;
        Work nextFailed;
        boolean rollbackPending;
        TimerLease timer;
        Work(Bindings.LatentRuntimeActivationToken token) { this.token = token; }
    }

    private static Work lookup(Thread thread) {
        for (Work work = failedStarts; work != null; work = work.nextFailed)
            if (work.failedThread == thread) return work;
        return threads.get(thread);
    }

    private static Bindings.LatentRuntimeActivationToken register(Bindings.LatentRuntimeActivationOwnerKind kind) {
        Work parent = lookup(Thread.currentThread());
        var token = Bindings.LatentRuntimeActivation.register(
            kind,
            parent == null || parent.complete ? Option.none() : Option.some(parent.token));
        if (token.isError()) throw new IllegalStateException("activation-runtime-register-" + token.error());
        return token.value();
    }

    /** Called before TeaVM allocates its event/continuation for Thread.start. */
    public static void starting(Thread thread) {
        if (!entered) throw new IllegalStateException("activation-runtime-entry-required");
        Work existing = lookup(thread);
        if (existing != null) {
            if (!existing.complete && !existing.rollbackPending && existing.prepared) { existing.prepared = false; return; }
            throw new IllegalThreadStateException();
        }
        // Allocate custody before admission so an OOM cannot lose a new token.
        Work work = new Work(null);
        work.token = register(Bindings.LatentRuntimeActivationOwnerKind.Task);
        try { threads.put(thread, work); }
        catch (Throwable error) { rollbackInsertion(thread, work); throw error; }
    }

    /** SDK-managed workers remain real independently scheduled Java threads. */
    public static void startManaged(Thread thread) { startManaged(thread, null); }

    public static void startManaged(Thread thread, ManagedPool pool) {
        if (thread == null || lookup(thread) != null) throw new IllegalThreadStateException();
        if (pool != null && !containsPool(pool)) throw new IllegalStateException("activation-runtime-pool-entry");
        Work work = new Work(null);
        work.token = register(Bindings.LatentRuntimeActivationOwnerKind.ManagedIdleWorker);
        work.prepared = true;
        work.managed = true;
        work.pool = pool;
        try { threads.put(thread, work); }
        catch (Throwable error) { rollbackInsertion(thread, work); throw error; }
        try { thread.start(); }
        catch (Throwable error) {
            // Keep accepted or rollback-uncertain work through a failed entry.
            if (!work.complete) retainFailedStart(thread, work);
            // Before the maintained start hook consumes this preparation, no
            // worker has been accepted. Later failures retain uncertain work.
            if (!work.complete && work.prepared) {
                work.rollbackPending = true;
                var settled = Bindings.LatentRuntimeActivation.settle(work.token);
                if (settled.isError()) throw new IllegalStateException("activation-runtime-start-rollback-" + settled.error(), error);
                if (threads.get(thread) == work) threads.remove(thread);
                work.token = null;
                work.complete = true;
                work.pool = null;
                unlinkFailedStart(work);
            }
            throw error;
        }
    }

    private static void retainFailedStart(Thread thread, Work work) {
        work.failedThread = thread;
        work.nextFailed = failedStarts;
        failedStarts = work;
    }

    private static void unlinkFailedStart(Work work) {
        Work previous = null;
        for (Work current = failedStarts; current != null; current = current.nextFailed) {
            if (current == work) {
                if (previous == null) failedStarts = current.nextFailed;
                else previous.nextFailed = current.nextFailed;
                break;
            }
            previous = current;
        }
        work.failedThread = null;
        work.nextFailed = null;
        work.rollbackPending = false;
    }

    // The Work was allocated before map insertion. Link it without allocating
    // before rollback so denied or throwing settlement cannot lose custody.
    private static void rollbackInsertion(Thread thread, Work work) {
        retainFailedStart(thread, work);
        work.rollbackPending = true;
        boolean settled = false;
        try { settled = !Bindings.LatentRuntimeActivation.settle(work.token).isError(); }
        catch (Throwable ignored) { } // Unknown settlement remains fail-closed.
        if (!settled) return;
        work.token = null;
        work.complete = true;
        work.pool = null;
        if (threads.get(thread) == work) threads.remove(thread);
        unlinkFailedStart(work);
    }

    public interface ManagedPool {
        boolean hasPendingWork();
        boolean isRetired();
        void closeAtRoot();
    }
    public static void manage(ManagedPool pool) {
        if (!entered || retiringPools || closing && !acceptedContinuation())
            throw new IllegalStateException("activation-runtime-pool-entry");
        pools.add(pool);
    }

    private static boolean containsPool(ManagedPool pool) {
        for (ManagedPool registered : pools) if (registered == pool) return true;
        return false;
    }

    /** Drop only a settled pool whose real workers have also settled. */
    public static void unmanageRetired(ManagedPool pool) {
        if (!pool.isRetired()) return;
        for (Work work : threads.values()) if (work.pool == pool && !work.complete) return;
        for (Work work = failedStarts; work != null; work = work.nextFailed)
            if (work.pool == pool && !work.complete) return;
        for (int index = pools.size() - 1; index >= 0; --index) {
            if (pools.get(index) == pool) {
                // closeAtRoot can retire itself or another pool reentrantly.
                if (iteratingPoolRetirement) pools.set(index, null);
                else pools.remove(index);
            }
        }
    }

    public static boolean acceptedContinuation() {
        Work work = lookup(Thread.currentThread());
        return work != null && work != root && !work.complete;
    }

    public static boolean closing() { return closing; }

    /** One activation-local default pool; accepted callbacks share no host worker. */
    public static synchronized java.util.concurrent.Executor defaultAsyncExecutor(
            java.util.function.Supplier<java.util.concurrent.Executor> factory) {
        if (!entered || retiringPools || closing && !acceptedContinuation())
            throw new IllegalStateException("activation-runtime-default-executor-closed");
        if (defaultAsyncExecutor == null) defaultAsyncExecutor = factory.get();
        return defaultAsyncExecutor;
    }

    /** Linear logical ownership; payloads remain in the accounted Java heap. */
    public static class Lease implements AutoCloseable {
        private Bindings.LatentRuntimeActivationToken token;
        private Lease(Bindings.LatentRuntimeActivationToken token) { this.token = token; }
        @Override public void close() {
            if (token == null) return;
            var settled = Bindings.LatentRuntimeActivation.settle(token);
            if (settled.isError()) throw new IllegalStateException("activation-runtime-owner-settle-" + settled.error());
            token = null;
        }
    }

    public static Lease owner(Bindings.LatentRuntimeActivationOwnerKind kind) {
        if (!entered) throw new IllegalStateException("activation-runtime-entry-required");
        return new Lease(register(kind));
    }

    /** No current or later invocation may succeed after an unknown Result settlement. */
    public static void fenceUncertainResultSettlement() { poisoned = true; }

    private static void requireHealthyCompletion() {
        if (poisoned) throw new IllegalStateException("activation-runtime-result-settlement-uncertain");
    }

    private static final class TimerLease extends Lease {
        final Work work;
        final long deadline;
        boolean fired;
        boolean closing;
        boolean rawFrame;
        TimerLease(Bindings.LatentRuntimeActivationToken token, Work work, long deadline) {
            super(token);
            this.work = work;
            this.deadline = deadline;
        }
        @Override public void close() {
            if (super.token == null) return;
            closing = true;
            var stopped = Bindings.LatentRuntimeActivation.timerStop(super.token);
            if (stopped.isError()) throw new IllegalStateException("activation-runtime-timer-stop-" + stopped.error());
            super.token = null;
            if (work.timer == this) work.timer = null;
            timers.remove(this);
        }
    }

    /** One host-owned timer also accounts the corresponding logical Java wait. */
    public static Lease timer(long deadline) {
        Work work = lookup(Thread.currentThread());
        if (!entered || work == null || work.complete || work.timer != null)
            throw new IllegalStateException("activation-runtime-timer-frame");
        long now = monotonicMillis();
        long remaining = deadline <= now ? 0 : deadline - now;
        long nanos = remaining < 0 || remaining > Long.MAX_VALUE / 1_000_000
            ? Long.MAX_VALUE : remaining * 1_000_000;
        var started = Bindings.LatentRuntimeActivation.timerStart(new Unsigned64(nanos), Option.none(), Option.some(work.token));
        if (started.isError()) throw new IllegalStateException("activation-runtime-timer-start-" + started.error());
        try {
            TimerLease timer = new TimerLease(started.value(), work, deadline);
            timers.add(timer);
            work.timer = timer;
            return timer;
        } catch (Throwable error) {
            var stopped = Bindings.LatentRuntimeActivation.timerStop(started.value());
            if (stopped.isError()) throw new IllegalStateException("activation-runtime-timer-start-rollback-" + stopped.error(), error);
            throw error;
        }
    }

    /** The retained raw TeaVM body schedules the already captured wait deadline. */
    public static long timerDeadline(long otherwise) {
        if (!entered) return otherwise;
        Work work = lookup(Thread.currentThread());
        return work != null && work.timer != null && work.timer.rawFrame && !work.timer.closing
            ? work.timer.deadline : otherwise;
    }

    public static void beginTimedFrame(Lease lease) {
        if (lease == null) return;
        TimerLease timer = (TimerLease)lease;
        if (lookup(Thread.currentThread()) != timer.work || timer.work.timer != timer || timer.closing || timer.rawFrame)
            throw new IllegalStateException("activation-runtime-timer-frame");
        timer.rawFrame = true;
    }

    public static void endTimedFrame(Lease lease) {
        if (lease == null) return;
        TimerLease timer = (TimerLease)lease;
        if (lookup(Thread.currentThread()) != timer.work || !timer.rawFrame)
            throw new IllegalStateException("activation-runtime-timer-frame");
        timer.rawFrame = false;
    }

    /** Runs after the original Thread finally block has restored identity. */
    public static void finished(Thread thread) {
        Work work = lookup(thread);
        if (work == null || work.complete || work.rollbackPending) throw new IllegalStateException("activation-runtime-thread-owner");
        var settled = Bindings.LatentRuntimeActivation.settle(work.token);
        if (settled.isError()) throw new IllegalStateException("activation-runtime-settle-" + settled.error());
        work.token = null;
        work.complete = true;
        ManagedPool pool = work.pool;
        work.pool = null;
        if (work.failedThread != null) unlinkFailedStart(work);
        if (pool != null) unmanageRetired(pool);
        synchronized (thread) { thread.notifyAll(); }
    }

    public static boolean alive(Thread thread) {
        Work work = lookup(thread);
        return work != null && !work.complete;
    }

    /** Ownership can remain uncertain even before the worker may run. */
    public static boolean ownsManaged(Thread thread, ManagedPool pool) {
        Work work = lookup(thread);
        return work != null && !work.complete && work.pool == pool;
    }

    /** The factory target may enter only its own admitted, started worker. */
    public static boolean runningManaged(Thread thread, ManagedPool pool) {
        Work work = lookup(thread);
        return work != null && !work.complete && !work.prepared && !work.rollbackPending && work.pool == pool;
    }

    /** A loop handles spurious notifications and preserves interrupt behavior. */
    public static void join(Thread thread, long millis, int nanos) throws InterruptedException {
        if (millis < 0 || nanos < 0 || nanos > 999999) throw new IllegalArgumentException();
        if (nanos > 0 && millis != Long.MAX_VALUE) millis++;
        long timeout = millis;
        long started = monotonicMillis();
        synchronized (thread) {
            while (alive(thread)) {
                if (timeout == 0) {
                    thread.wait();
                } else {
                    long remaining = timeout - (monotonicMillis() - started);
                    if (remaining <= 0) return;
                    thread.wait(remaining);
                }
            }
        }
    }

    /** Internal event deadlines use monotonic time; application wall time stays wall time. */
    public static long monotonicMillis() { return System.nanoTime() / 1_000_000; }

    /** processSingle subtracts its first sample, not its second due-time check. */
    public static long queueMonotonicMillis() {
        long now = monotonicMillis();
        if (!queueClockCaptured) { queueClock = now; queueClockCaptured = true; }
        return now;
    }

    /** TeaVM inserts this at verified application/dependency loop headers. */
    public static void checkpoint() {
        // Scheduling never starts from an unmanaged C call or class initializer.
        if (entered && Fiber.current() != null) Thread.yield();
    }

    private static boolean pending() {
        if (!rootComplete) return true;
        for (Work work = failedStarts; work != null; work = work.nextFailed)
            if (!work.complete) return true;
        for (Work work : threads.values()) {
            if (work != root && !work.complete) return true;
        }
        return false;
    }

    private static void closeCompletedRoot() {
        if (rootComplete && !closing) {
            closing = true;
            var close = Bindings.LatentRuntimeActivation.close();
            if (close.isError()) throw new IllegalStateException("activation-runtime-close-" + close.error());
        }
    }

    private static boolean retireIdlePools() {
        if (!closing || retiringPools) return false;
        // Idle pool workers cannot keep an activation alive. Keep their executor
        // available while accepted application threads/callbacks can still submit
        // necessary continuations, then drain the actual worker finally blocks.
        for (Work work : threads.values()) {
            if (work != root && !work.managed && !work.complete) return false;
        }
        for (Work work = failedStarts; work != null; work = work.nextFailed)
            if (!work.managed && !work.complete) return false;
        for (ManagedPool pool : pools) if (pool.hasPendingWork()) return false;
        retiringPools = true;
        iteratingPoolRetirement = true;
        try {
            for (int index = 0, count = pools.size(); index < count; index++) {
                ManagedPool pool = pools.get(index);
                if (pool != null) pool.closeAtRoot();
            }
        } finally {
            iteratingPoolRetirement = false;
            for (int index = pools.size() - 1; index >= 0; --index)
                if (pools.get(index) == null) pools.remove(index);
        }
        return true;
    }

    @Export(name = "lsf_java_runtime_wait")
    public static void waitFor(long millis) {
        if (!entered || root == null || root.complete) throw new IllegalStateException("activation-runtime-wait-owner");
        long nanos = millis < 0 || millis > Long.MAX_VALUE / 1_000_000
            ? Long.MAX_VALUE : millis * 1_000_000;
        var parked = Bindings.LatentRuntimeActivation.park(root.token);
        if (parked.isError()) throw new IllegalStateException("activation-runtime-park-" + parked.error());
        TimerLease selected = null;
        if (millis >= 0 && queueClockCaptured && queueClock <= Long.MAX_VALUE - millis) {
            long deadline = queueClock + millis;
            for (TimerLease timer : timers) {
                if (!timer.fired && !timer.closing && timer.deadline == deadline) { selected = timer; break; }
            }
        }
        if (selected != null) {
            if (HostCalls.enabled()) {
                var waited = Bindings.lsfRootTimerNext(((Lease)selected).token);
                if (waited.isSome() && waited.value().isError())
                    throw new IllegalStateException("activation-runtime-timer-next-" + waited.value().error());
                selected.fired = waited.isSome();
            } else {
                var waited = Bindings.LatentRuntimeActivation.timerNext(((Lease)selected).token);
                if (waited.isError()) throw new IllegalStateException("activation-runtime-timer-next-" + waited.error());
                selected.fired = true;
            }
        } else {
            if (HostCalls.enabled()) {
                if (!(millis < 0 && HostCalls.waitAny())) {
                    var waited = Bindings.lsfRootWaitFor(new Unsigned64(nanos), Option.some(root.token));
                    if (waited.isSome() && waited.value().isError())
                        throw new IllegalStateException("activation-runtime-wait-" + waited.value().error());
                }
            } else {
                var waited = Bindings.LatentRuntimeActivation.waitFor(new Unsigned64(nanos), Option.some(root.token));
                if (waited.isError()) throw new IllegalStateException("activation-runtime-wait-" + waited.error());
            }
        }
        var awake = Bindings.LatentRuntimeActivation.wake(root.token);
        if (awake.isError()) throw new IllegalStateException("activation-runtime-wake-" + awake.error());
    }

    /** Dispatch executes inside a real Fiber; the pump itself owns no logical stack. */
    public static Address invoke(int operation, Address data, int length) {
        if (poisoned) throw new IllegalStateException("activation-runtime-poisoned-store");
        if (entered) throw new IllegalStateException("activation-runtime-reentrant-entry");
        entered = true;
        // Keep the profile's actual wall-clock operation in its exact imported
        // surface. Relative event deadlines exclusively use monotonic time.
        if (System.currentTimeMillis() < 0) throw new IllegalStateException("activation-runtime-wall-range");
        rootComplete = closing = retiringPools = false;
        result = null;
        failure = null;
        root = new Work(register(Bindings.LatentRuntimeActivationOwnerKind.Task));
        threads.put(Thread.currentThread(), root);
        Fiber.userThreadCount++;
        // A linear-memory address must use the primitive coroutine stack;
        // TeaVM would otherwise spill this capture through Fiber.push(Object).
        int inputAddress = data.toInt();
        Fiber.start(() -> {
            try { result = Bindings.dispatchBody(operation, inputAddress, length); }
            catch (Throwable error) { failure = error; }
            finally { rootComplete = true; }
        }, false);
        try {
            while (true) {
                closeCompletedRoot();
                retireIdlePools();
                if (!pending()) break;
                queueClockCaptured = false;
                HostCalls.poll();
                long delay = EventQueue.processSingle();
                // The queue may become empty because that event completed the
                // last accepted task. Establish quiescence before parking.
                closeCompletedRoot();
                if (HostCalls.poll()) continue;
                // Interrupting idle workers can enqueue their ordinary finally
                // continuations after processSingle calculated its delay. Run
                // the guest queue again before using that now-stale delay.
                if (retireIdlePools()) continue;
                if (delay != 0 && pending()) waitFor(delay < 0 ? -1 : delay);
            }
            if (failure != null) throw new IllegalStateException("activation-runtime-root-failure", failure);
            requireHealthyCompletion();
            var settled = Bindings.LatentRuntimeActivation.settle(root.token);
            if (settled.isError()) throw new IllegalStateException("activation-runtime-root-settle-" + settled.error());
            root.complete = true;
            Address output = result;
            result = null;
            return output;
        } finally {
            finishInvocation();
        }
    }

    private static void finishInvocation() {
        if (failedStarts != null || poisoned) {
            // The host must destroy this Store; retain every original reference
            // and reject re-entry while registration settlement is uncertain.
            poisoned = true;
            entered = false;
            return;
        }
        // A trap may bypass Java finally; the host still destroys the entire
        // Store and keeps the original reservations until physical drop.
        threads.clear();
        pools.clear();
        timers.clear();
        queueClockCaptured = false;
        defaultAsyncExecutor = null;
        root = null;
        failure = null;
        entered = false;
    }
}
