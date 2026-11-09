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
    private static boolean finishingInvocation;
    private static boolean retiringPools;
    private static boolean iteratingPoolRetirement;
    private static volatile boolean poisoned;
    private static Work failedStarts;
    private static final java.util.concurrent.atomic.AtomicReference<Lease> failedQueuedOwners =
        new java.util.concurrent.atomic.AtomicReference<>();
    private static Address result;
    private static Throwable failure;
    private static Work root;
    private static java.util.concurrent.Executor defaultAsyncExecutor;
    private static boolean queueClockCaptured;
    private static long queueClock;
    private static int pendingTimerStops;
    private static int pendingTimerStarts;

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
        boolean finishing;
        boolean finishRefused;
        TimerLease timer;
        Work(Bindings.LatentRuntimeActivationToken token) { this.token = token; }
    }

    private static Work lookup(Thread thread) {
        for (Work work = failedStarts; work != null; work = work.nextFailed)
            if (work.failedThread == thread) return work;
        return threads.get(thread);
    }

    private static Bindings.LatentRuntimeActivationToken register(Bindings.LatentRuntimeActivationOwnerKind kind) {
        requireHealthyAdmission();
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
            if (!existing.complete && !existing.rollbackPending && !existing.finishing && existing.prepared) { existing.prepared = false; return; }
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
        private Lease nextFailedQueued;
        private Lease(Bindings.LatentRuntimeActivationToken token) { this.token = token; }
        @Override public void close() {
            if (token == null) return;
            var settled = Bindings.LatentRuntimeActivation.settle(token);
            if (settled.isError()) throw new IllegalStateException("activation-runtime-owner-settle-" + settled.error());
            token = null;
        }
    }

    public static Lease owner(Bindings.LatentRuntimeActivationOwnerKind kind) {
        requireHealthyAdmission();
        if (!entered) throw new IllegalStateException("activation-runtime-entry-required");
        return new Lease(register(kind));
    }

    /** No current or later invocation may succeed after ownership becomes uncertain. */
    public static void fenceUncertainCompletion() { poisoned = true; }
    public static void fenceUncertainResultSettlement() { fenceUncertainCompletion(); }

    /** Keep an admitted owner with uncertain settlement rooted until Store destruction.
     * This intrusive custody also covers executor and timer owners. */
    public static void fenceUncertainQueuedWorkSettlement(Lease owner) {
        poisoned = true;
        // The lease and list head were allocated before admission. Each failed
        // constructor links its own lease once; no failure-path allocation or
        // second settlement is needed, even when acknowledgement was lost.
        Lease previous;
        do {
            previous = failedQueuedOwners.get();
            owner.nextFailedQueued = previous;
        } while (!failedQueuedOwners.compareAndSet(previous, owner));
    }

    private static void requireHealthyAdmission() {
        if (poisoned) throw new IllegalStateException("activation-runtime-poisoned-store");
        if (finishingInvocation) {
            fenceUncertainCompletion();
            throw new IllegalStateException("activation-runtime-teardown");
        }
    }
    private static void fencePendingTimerStops() {
        // An accepted stop remains counted through host acknowledgement and
        // local cleanup, even if its timer leaves the mutable registry.
        if (pendingTimerStops != 0) poisoned = true;
    }
    private static void fencePendingTimerStarts() {
        if (pendingTimerStarts != 0) poisoned = true;
    }
    private static void requireHealthyCompletion() {
        fencePendingTimerStops();
        fencePendingTimerStarts();
        if (poisoned) throw new IllegalStateException("activation-runtime-owner-settlement-uncertain");
    }

    private static final class TimerLease extends Lease {
        final Work work;
        final long deadline;
        boolean fired;
        boolean closing;
        boolean stopPending;
        boolean startPending;
        boolean rawFrame;
        TimerLease(Bindings.LatentRuntimeActivationToken token, Work work, long deadline) {
            super(token);
            this.work = work;
            this.deadline = deadline;
        }
        @Override public void close() {
            if (super.token == null) return;
            if (!entered || finishingInvocation || work.complete || work.timer != this) {
                fenceUncertainCompletion();
                throw new IllegalStateException("activation-runtime-timer-stop-teardown");
            }
            if (stopPending) {
                fenceUncertainCompletion();
                throw new IllegalStateException("activation-runtime-timer-stop-unconfirmed");
            }
            if (pendingTimerStops == Integer.MAX_VALUE) {
                fenceUncertainCompletion();
                throw new IllegalStateException("activation-runtime-timer-stop-capacity");
            }
            closing = true;
            pendingTimerStops++;
            stopPending = true;
            boolean returned = false;
            try {
                // The first gate and counter publication are straight-line;
                // recheck teardown after publication before the host call.
                if (!entered || finishingInvocation || work.complete || work.timer != this) {
                    stopPending = false;
                    pendingTimerStops--;
                    returned = true;
                    fenceUncertainCompletion();
                    throw new IllegalStateException("activation-runtime-timer-stop-teardown");
                }
                var stopped = Bindings.LatentRuntimeActivation.timerStop(super.token);
                if (stopped.isError()) {
                    // A returned refusal has not removed the host timer and may
                    // be retried. A thrown call has no such acknowledgement.
                    stopPending = false;
                    pendingTimerStops--;
                    returned = true;
                    throw new IllegalStateException("activation-runtime-timer-stop-" + stopped.error());
                }
                timers.remove(this);
                if (work.timer == this) work.timer = null;
                super.token = null;
                stopPending = false;
                pendingTimerStops--;
                returned = true;
            } catch (Throwable failure) {
                if (!returned) fenceUncertainCompletion();
                throw failure;
            }
        }
    }

    // These straight-line state transitions do not call the host, allocate or
    // contain a scheduling checkpoint. Each start keeps its original count and
    // Work sentinel until a definite refusal or complete local publication.
    private static int beginTimerStart(Work work, TimerLease timer) {
        if (!entered || finishingInvocation || poisoned || work.complete || work.finishing || work.timer != null) return 0;
        if (pendingTimerStarts == Integer.MAX_VALUE) { poisoned = true; return 2; }
        pendingTimerStarts++;
        timer.startPending = true;
        timer.closing = true;
        work.timer = timer;
        return 1;
    }

    private static void abandonUnstartedTimer(Work work, TimerLease timer) {
        if (pendingTimerStarts <= 0 || work.timer != timer || !timer.startPending) { poisoned = true; return; }
        work.timer = null;
        timer.startPending = false;
        pendingTimerStarts--;
    }

    private static boolean publishStartedTimer(Work work, TimerLease timer) {
        if (!entered || finishingInvocation || poisoned || work.complete || work.finishing
                || pendingTimerStarts <= 0 || work.timer != timer || !timer.startPending) return false;
        timer.startPending = false;
        pendingTimerStarts--;
        timer.closing = false;
        return true;
    }

    /** One host-owned timer also accounts the corresponding logical Java wait. */
    public static Lease timer(long deadline) {
        requireHealthyAdmission();
        Work work = lookup(Thread.currentThread());
        if (!entered || work == null || work.complete || work.finishing || work.timer != null)
            throw new IllegalStateException("activation-runtime-timer-frame");
        // Allocation can fail before host admission, without leaving an owner.
        TimerLease timer = new TimerLease(null, work, deadline);
        boolean sameWork = lookup(Thread.currentThread()) == work;
        requireHealthyAdmission();
        if (!sameWork) throw new IllegalStateException("activation-runtime-timer-frame");
        int admission = beginTimerStart(work, timer);
        if (admission == 2) throw new IllegalStateException("activation-runtime-timer-start-capacity");
        if (admission != 1) throw new IllegalStateException("activation-runtime-timer-frame");
        boolean hostUncertain = false;
        try {
            // The Work sentinel and count precede every clock/argument operation
            // that can suspend, and are rechecked before the host call.
            long now = monotonicMillis();
            long remaining = deadline <= now ? 0 : deadline - now;
            long nanos = remaining < 0 || remaining > Long.MAX_VALUE / 1_000_000
                ? Long.MAX_VALUE : remaining * 1_000_000;
            var delay = new Unsigned64(nanos);
            var period = Option.<Unsigned64>none();
            var continuation = Option.some(work.token);
            boolean selected = lookup(Thread.currentThread()) == work && !work.complete
                && !work.finishing && work.timer == timer;
            requireHealthyAdmission();
            if (!entered || !selected) throw new IllegalStateException("activation-runtime-timer-frame");
            // A trap or lost reply can occur after host admission. Never retry
            // or release its original Work/count on an ambiguous result.
            hostUncertain = true;
            var started = Bindings.LatentRuntimeActivation.timerStart(delay, period, continuation);
            if (started.isError()) {
                // The typed error is returned only before host timer publication.
                hostUncertain = false;
                throw new IllegalStateException("activation-runtime-timer-start-" + started.error());
            }
            ((Lease)timer).token = started.value();
            if (((Lease)timer).token == null) throw new IllegalStateException("activation-runtime-timer-start-token");
            selected = lookup(Thread.currentThread()) == work && !work.complete
                && !work.finishing && work.timer == timer;
            requireHealthyAdmission();
            if (!entered || !selected) throw new IllegalStateException("activation-runtime-timer-frame");
            timers.add(timer);
            selected = lookup(Thread.currentThread()) == work && !work.complete
                && !work.finishing && work.timer == timer;
            requireHealthyAdmission();
            if (!selected || !publishStartedTimer(work, timer))
                throw new IllegalStateException("activation-runtime-timer-frame");
            return timer;
        } catch (Throwable error) {
            if (hostUncertain) {
                // The host Table remains the original admitted timer owner.
                // Keep the Work sentinel/count and refuse successful completion.
                fenceUncertainCompletion();
            } else {
                // No host owner was published, or it definitively refused.
                abandonUnstartedTimer(work, timer);
            }
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

    private static int beginWorkFinish(Work work) {
        if (work.complete || work.rollbackPending || work.finishing && !work.finishRefused) return 0;
        if (work.timer != null && work.timer.startPending) { poisoned = true; return 2; }
        work.finishing = true;
        work.finishRefused = false;
        return 1;
    }

    /** Runs after the original Thread finally block has restored identity. */
    public static void finished(Thread thread) {
        Work work = lookup(thread);
        if (work == null) throw new IllegalStateException("activation-runtime-thread-owner");
        int admission = beginWorkFinish(work);
        if (admission == 2) return; // Preserve a primary exception and the original owner.
        if (admission != 1) throw new IllegalStateException("activation-runtime-thread-owner");
        boolean refused = false;
        try {
            var settled = Bindings.LatentRuntimeActivation.settle(work.token);
            if (settled.isError()) {
                // Build the refusal while the Work remains closed to new
                // timers, including any reentry from exception allocation.
                var refusal = new IllegalStateException("activation-runtime-settle-" + settled.error());
                refused = true;
                work.finishRefused = true;
                throw refusal;
            }
            work.token = null;
            work.complete = true;
        } catch (Throwable error) {
            if (!refused) fenceUncertainCompletion();
            throw error;
        }
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
        requireHealthyAdmission();
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
        boolean returning = false;
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
            // Close start admission before observing pending starts and settling
            // the original root, so the two gates cannot pass in opposite order.
            finishingInvocation = true;
            requireHealthyCompletion();
            var settled = Bindings.LatentRuntimeActivation.settle(root.token);
            if (settled.isError()) throw new IllegalStateException("activation-runtime-root-settle-" + settled.error());
            root.complete = true;
            Address output = result;
            result = null;
            returning = true;
            return output;
        } finally {
            finishInvocation(returning);
        }
    }

    private static void finishInvocation(boolean returning) {
        // An exceptional invocation may still own accepted sibling work.
        // Keep the existing Store state while preserving its primary error.
        if (!returning) {
            finishingInvocation = true;
            fenceUncertainCompletion();
        }
        finishInvocation();
        // Teardown can discover a late in-flight stop after the earlier
        // health check. Refuse that return without masking an existing error.
        if (returning) requireHealthyCompletion();
    }

    private static void finishInvocation() {
        finishingInvocation = true;
        fencePendingTimerStops();
        fencePendingTimerStarts();
        boolean liveTimers = !timers.isEmpty();
        // A stop or start may change state while the registry was observed.
        fencePendingTimerStops();
        fencePendingTimerStarts();
        if (failedStarts != null || poisoned || liveTimers) {
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
        finishingInvocation = false;
    }
}
