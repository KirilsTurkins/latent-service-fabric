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
    private static boolean entered;
    private static boolean rootComplete;
    private static boolean closing;
    private static boolean retiringPools;
    private static Address result;
    private static Throwable failure;
    private static Work root;

    private Activation() { }

    private static final class Work {
        Bindings.LatentRuntimeActivationToken token;
        boolean complete;
        boolean prepared;
        boolean managed;
        Work(Bindings.LatentRuntimeActivationToken token) { this.token = token; }
    }

    private static Bindings.LatentRuntimeActivationToken register(Bindings.LatentRuntimeActivationOwnerKind kind) {
        Work parent = threads.get(Thread.currentThread());
        var token = Bindings.LatentRuntimeActivation.register(
            kind,
            parent == null || parent.complete ? Option.none() : Option.some(parent.token));
        if (token.isError()) throw new IllegalStateException("activation-runtime-register-" + token.error());
        return token.value();
    }

    /** Called before TeaVM allocates its event/continuation for Thread.start. */
    public static void starting(Thread thread) {
        if (!entered) throw new IllegalStateException("activation-runtime-entry-required");
        Work existing = threads.get(thread);
        if (existing != null) {
            if (existing.prepared) { existing.prepared = false; return; }
            throw new IllegalThreadStateException();
        }
        var token = register(Bindings.LatentRuntimeActivationOwnerKind.Task);
        try { threads.put(thread, new Work(token)); }
        catch (Throwable error) {
            Bindings.LatentRuntimeActivation.settle(token);
            throw error;
        }
    }

    /** SDK-managed workers remain real independently scheduled Java threads. */
    public static void startManaged(Thread thread) {
        if (thread == null || threads.containsKey(thread)) throw new IllegalThreadStateException();
        Work work = new Work(register(Bindings.LatentRuntimeActivationOwnerKind.ManagedIdleWorker));
        work.prepared = true;
        work.managed = true;
        try { threads.put(thread, work); }
        catch (Throwable error) { Bindings.LatentRuntimeActivation.settle(work.token); throw error; }
        thread.start();
    }

    public interface ManagedPool {
        boolean hasPendingWork();
        void closeAtRoot();
    }
    public static void manage(ManagedPool pool) {
        if (!entered || closing && !acceptedContinuation()) throw new IllegalStateException("activation-runtime-pool-entry");
        pools.add(pool);
    }

    public static boolean acceptedContinuation() {
        Work work = threads.get(Thread.currentThread());
        return work != null && work != root && !work.complete;
    }

    public static boolean closing() { return closing; }

    /** Linear logical ownership; payloads remain in the accounted Java heap. */
    public static final class Lease implements AutoCloseable {
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

    /** Runs after the original Thread finally block has restored identity. */
    public static void finished(Thread thread) {
        Work work = threads.get(thread);
        if (work == null || work.complete) throw new IllegalStateException("activation-runtime-thread-owner");
        var settled = Bindings.LatentRuntimeActivation.settle(work.token);
        if (settled.isError()) throw new IllegalStateException("activation-runtime-settle-" + settled.error());
        work.token = null;
        work.complete = true;
        synchronized (thread) { thread.notifyAll(); }
    }

    public static boolean alive(Thread thread) {
        Work work = threads.get(thread);
        return work != null && !work.complete;
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

    /** TeaVM inserts this at verified application/dependency loop headers. */
    public static void checkpoint() {
        // Scheduling never starts from an unmanaged C call or class initializer.
        if (entered && Fiber.current() != null) Thread.yield();
    }

    private static boolean pending() {
        if (!rootComplete) return true;
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

    private static void retireIdlePools() {
        if (!closing || retiringPools) return;
        // Idle pool workers cannot keep an activation alive. Keep their executor
        // available while accepted application threads/callbacks can still submit
        // necessary continuations, then drain the actual worker finally blocks.
        for (Work work : threads.values()) {
            if (work != root && !work.managed && !work.complete) return;
        }
        for (ManagedPool pool : pools) if (pool.hasPendingWork()) return;
        retiringPools = true;
        for (int index = 0, count = pools.size(); index < count; index++) pools.get(index).closeAtRoot();
    }

    @Export(name = "lsf_java_runtime_wait")
    public static void waitFor(long millis) {
        if (!entered || root == null || root.complete) throw new IllegalStateException("activation-runtime-wait-owner");
        long nanos = millis < 0 || millis > Long.MAX_VALUE / 1_000_000
            ? Long.MAX_VALUE : millis * 1_000_000;
        var parked = Bindings.LatentRuntimeActivation.park(root.token);
        if (parked.isError()) throw new IllegalStateException("activation-runtime-park-" + parked.error());
        var waited = Bindings.LatentRuntimeActivation.waitFor(new Unsigned64(nanos), Option.some(root.token));
        if (waited.isError()) throw new IllegalStateException("activation-runtime-wait-" + waited.error());
        var awake = Bindings.LatentRuntimeActivation.wake(root.token);
        if (awake.isError()) throw new IllegalStateException("activation-runtime-wake-" + awake.error());
    }

    /** Dispatch executes inside a real Fiber; the pump itself owns no logical stack. */
    public static Address invoke(int operation, Address data, int length) {
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
        Fiber.start(() -> {
            try { result = Bindings.dispatchBody(operation, data, length); }
            catch (Throwable error) { failure = error; }
            finally { rootComplete = true; }
        }, false);
        try {
            while (true) {
                closeCompletedRoot();
                retireIdlePools();
                if (!pending()) break;
                long delay = EventQueue.processSingle();
                // The queue may become empty because that event completed the
                // last accepted task. Establish quiescence before parking.
                closeCompletedRoot();
                retireIdlePools();
                if (delay != 0 && pending()) waitFor(delay < 0 ? -1 : delay);
            }
            if (failure != null) throw new IllegalStateException("activation-runtime-root-failure", failure);
            var settled = Bindings.LatentRuntimeActivation.settle(root.token);
            if (settled.isError()) throw new IllegalStateException("activation-runtime-root-settle-" + settled.error());
            root.complete = true;
            Address output = result;
            result = null;
            return output;
        } finally {
            // A trap may bypass Java finally; the host still destroys the entire
            // Store and keeps the original reservations until physical drop.
            threads.clear();
            pools.clear();
            root = null;
            failure = null;
            entered = false;
        }
    }
}
