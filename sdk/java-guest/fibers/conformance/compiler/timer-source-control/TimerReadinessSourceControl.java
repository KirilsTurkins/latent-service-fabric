import dev.latent.generated.Bindings;
import dev.latent.guest.Option;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.Monitors;
import java.lang.reflect.Field;
import java.util.Map;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

/** Execute the production timer registry with a private source-only host ledger. */
public final class TimerReadinessSourceControl {
    private static void require(boolean yes, String reason) { if (!yes) throw new AssertionError(reason); }
    private static Field field(Class<?> type, String name) throws ReflectiveOperationException { var field = type.getDeclaredField(name); field.setAccessible(true); return field; }
    private static Object get(String name) throws Exception { return field(Activation.class, name).get(null); }
    private static void set(String name, Object value) throws Exception { field(Activation.class, name).set(null, value); }
    @SuppressWarnings("unchecked")
    private static Object work(Thread thread) throws Exception {
        var token = Bindings.LatentRuntimeActivation.register(Bindings.LatentRuntimeActivationOwnerKind.Task, Option.none()).value();
        var type = Class.forName("dev.latent.guest.runtime.Activation$Work");
        var constructor = type.getDeclaredConstructor(Bindings.LatentRuntimeActivationToken.class); constructor.setAccessible(true);
        var work = constructor.newInstance(token);
        ((Map<Thread, Object>)get("threads")).put(thread, work); return work;
    }
    private static Activation.Lease otherTimer(long deadline) throws Exception {
        var value = new AtomicReference<Activation.Lease>(); var error = new AtomicReference<Throwable>();
        var thread = new Thread(() -> { try { value.set(Activation.timer(deadline)); } catch (Throwable caught) { error.set(caught); } });
        work(thread); thread.start(); thread.join();
        if (error.get() != null) throw new IllegalStateException("source-worker", error.get());
        return value.get();
    }
    private static void pair(long clock) throws Exception { set("queueClock", clock); set("queueClockCaptured", true); }
    private static void denied(Runnable operation) {
        try { operation.run(); throw new AssertionError("expected-source-denial"); }
        catch (IllegalStateException expected) { }
    }
    private static int owners() throws ReflectiveOperationException {
        return ((Map<?, ?>)field(Bindings.LatentRuntimeActivation.class, "owners").get(null)).size();
    }
    private static void managedStartRollback() throws Exception {
        Map<?, ?> threads = (Map<?, ?>)get("threads");
        int original = owners();
        var failure = new IllegalThreadStateException("source-start-rejected");
        Thread rejected = new Thread() { @Override public void start() { throw failure; } };
        for (int attempt = 0; attempt < 2; attempt++) {
            try { Activation.startManaged(rejected); throw new AssertionError("rejected-start-succeeded"); }
            catch (IllegalThreadStateException error) { require(error == failure, "original-start-error-preserved"); }
            require(!threads.containsKey(rejected) && owners() == original, "unaccepted-start-rolled-back");
        }
        Thread uncertain = new Thread() { @Override public void start() { Activation.starting(this); throw failure; } };
        try { Activation.startManaged(uncertain); throw new AssertionError("uncertain-start-succeeded"); }
        catch (IllegalThreadStateException error) { require(error == failure, "uncertain-start-original-error"); }
        require(threads.containsKey(uncertain) && owners() == original + 1, "accepted-start-keeps-physical-owner");
        Activation.finished(uncertain);
        require(owners() == original, "explicit-source-owner-settlement");

        Bindings.LatentRuntimeActivation.denySettle = true;
        try { Activation.startManaged(rejected); throw new AssertionError("rollback-denial-succeeded"); }
        catch (IllegalStateException error) { require(error.getCause() == failure, "rollback-denial-preserves-start-cause"); }
        finally { Bindings.LatentRuntimeActivation.denySettle = false; }
        require(threads.containsKey(rejected) && owners() == original + 1, "failed-rollback-retains-original-owner");
        Activation.finished(rejected);
        require(owners() == original, "failed-rollback-explicit-source-settlement");
    }
    private static final class Pool implements Activation.ManagedPool {
        Activation.Lease owner = Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.Executor);
        Runnable onClose;
        int closes;
        @Override public boolean hasPendingWork() { return false; }
        @Override public boolean isRetired() { return owner == null; }
        @Override public void closeAtRoot() { closes++; if (onClose != null) onClose.run(); }
        void retire() { owner.close(); owner = null; Activation.unmanageRetired(this); }
    }
    private static void poolRetirement() throws Exception {
        @SuppressWarnings("unchecked") List<Activation.ManagedPool> pools = (List<Activation.ManagedPool>)get("pools");
        require(pools.isEmpty(), "initial-pool-registry");
        for (int i = 0; i < 256; i++) {
            Pool pool = new Pool(); Activation.manage(pool);
            Activation.unmanageRetired(pool);
            require(pools.size() == 1, "live-executor-remains-registered");
            pool.retire();
            require(pools.isEmpty(), "sequential-settlement-compacts-registry");
        }
        Pool pool = new Pool(); Activation.manage(pool);
        Bindings.LatentRuntimeActivation.denySettle = true;
        try { denied(pool::retire); } finally { Bindings.LatentRuntimeActivation.denySettle = false; }
        Activation.unmanageRetired(pool);
        require(pools.contains(pool) && !pool.isRetired(), "failed-executor-settlement-remains-owned");
        var startFailure = new IllegalThreadStateException("uncertain-start");
        Thread first = new Thread() { @Override public void start() { Activation.starting(this); throw startFailure; } };
        Thread second = new Thread() { @Override public void start() { Activation.starting(this); throw startFailure; } };
        for (Thread thread : new Thread[]{first, second}) {
            try { Activation.startManaged(thread, pool); throw new AssertionError("expected-uncertain-start"); }
            catch (IllegalThreadStateException expected) { require(expected == startFailure, "uncertain-start-cause"); }
        }
        Thread rejected = new Thread() { @Override public void start() { throw startFailure; } };
        Bindings.LatentRuntimeActivation.denySettle = true;
        try {
            try { Activation.startManaged(rejected, pool); throw new AssertionError("expected-rollback-denial"); }
            catch (IllegalStateException expected) { require(expected.getCause() == startFailure, "rollback-preserves-start-error"); }
        } finally { Bindings.LatentRuntimeActivation.denySettle = false; }
        require(Activation.alive(rejected), "failed-start-rollback-remains-owned");
        pool.retire();
        require(pools.contains(pool), "uncertain-workers-retain-settled-pool");
        Bindings.LatentRuntimeActivation.denySettle = true;
        try { denied(() -> Activation.finished(first)); } finally { Bindings.LatentRuntimeActivation.denySettle = false; }
        require(pools.contains(pool) && Activation.alive(first), "failed-worker-settlement-retains-pool");
        Activation.finished(first);
        require(pools.contains(pool) && Activation.alive(second), "all-physical-workers-must-retire");
        Activation.finished(second);
        require(pools.contains(pool), "failed-rollback-still-retains-pool");
        Activation.finished(rejected);
        require(pools.isEmpty(), "last-physical-worker-releases-pool");
        require(field(workClass(), "pool").get(((Map<?, ?>)get("threads")).get(first)) == null,
            "finished-work-does-not-retain-pool");

        // The timer test creates a private worker outside the managed-start path.
        for (Thread thread : ((Map<Thread, ?>)get("threads")).keySet().toArray(new Thread[0]))
            if (thread != Thread.currentThread() && Activation.alive(thread)) Activation.finished(thread);
        Pool firstClose = new Pool(), removedByFirst = new Pool(), lastClose = new Pool();
        Activation.manage(firstClose); Activation.manage(removedByFirst); Activation.manage(lastClose);
        set("closing", true);
        firstClose.onClose = () -> {
            firstClose.retire(); removedByFirst.retire();
            denied(() -> Activation.manage(firstClose));
        };
        lastClose.onClose = lastClose::retire;
        var retire = Activation.class.getDeclaredMethod("retireIdlePools"); retire.setAccessible(true);
        require((boolean)retire.invoke(null), "root-retirement-started");
        require(firstClose.closes == 1 && removedByFirst.closes == 0 && lastClose.closes == 1 && pools.isEmpty(),
            "reentrant-removals-do-not-skip-live-pools-or-leave-tombstones");
        // Reset this private fixture to exercise an independent failing close.
        set("closing", false); set("retiringPools", false);
        Pool failing = new Pool(), retained = new Pool();
        Activation.manage(failing); Activation.manage(retained);
        set("closing", true);
        RuntimeException marker = new RuntimeException("root-close-failure");
        failing.onClose = () -> { failing.retire(); throw marker; };
        retained.onClose = retained::retire;
        try { retire.invoke(null); throw new AssertionError("expected-root-close-failure"); }
        catch (java.lang.reflect.InvocationTargetException error) { require(error.getCause() == marker, "root-close-error-preserved"); }
        require(pools.size() == 1 && pools.get(0) == retained && (boolean)get("retiringPools"),
            "exception-compacts-tombstones-and-retains-owner-without-retry");
        retained.retire(); // Isolated control cleanup, not a production retry.
        require(pools.isEmpty(), "isolated-control-cleanup");
    }
    private static Class<?> workClass() throws Exception { return Class.forName("dev.latent.guest.runtime.Activation$Work"); }
    public static void main(String[] arguments) throws Exception {
        set("entered", true); set("root", work(Thread.currentThread()));
        long deadline = Activation.monotonicMillis() + 200;
        var first = Activation.timer(deadline); var second = otherTimer(deadline);
        require(Bindings.LatentRuntimeActivation.timers() == 2 && ((List<?>)get("timers")).size() == 2, "two-original-timer-reservations");

        require(Monitors.absoluteSleepDeadline(99, 1) == 100, "pure-deadline-outside-raw-frame");
        Activation.beginTimedFrame(first);
        require(Monitors.absoluteSleepDeadline(999, 1) == deadline, "captured-raw-sleep-deadline");
        require(Monitors.absoluteWaitDeadline(999, 0, 1) == deadline, "captured-rounded-raw-wait-deadline");
        try { Monitors.absoluteWaitDeadline(1, 0, 1000000); throw new AssertionError("nanos-validation"); } catch (IllegalArgumentException expected) { }
        try { Monitors.absoluteSleepDeadline(1, -1); throw new AssertionError("millis-validation"); } catch (IllegalArgumentException expected) { }
        Activation.endTimedFrame(first);
        require(Monitors.absoluteWaitDeadline(99, 0, 1) == 100, "pure-rounded-deadline-after-frame");
        denied(() -> Activation.beginTimedFrame(second));

        set("queueClockCaptured", false);
        long captured = Activation.queueMonotonicMillis(); Thread.sleep(5); long fresh = Activation.queueMonotonicMillis();
        require(fresh > captured && ((Long)get("queueClock")) == captured, "millisecond-crossing-retains-first-clock");
        pair(deadline - 50); Activation.waitFor(50);
        require(Bindings.LatentRuntimeActivation.selected.size() == 1 && Bindings.LatentRuntimeActivation.waits == 0, "first-tie-reuses-existing-timer");
        require(Bindings.LatentRuntimeActivation.timers() == 2, "fired-timer-held-through-java-frame");
        Activation.waitFor(50);
        require(Bindings.LatentRuntimeActivation.selected.size() == 2
            && !Bindings.LatentRuntimeActivation.selected.get(0).equals(Bindings.LatentRuntimeActivation.selected.get(1)), "stable-tie-selects-unfired-owner");
        denied(() -> Activation.waitFor(50));
        require(Bindings.LatentRuntimeActivation.selected.size() == 2 && Bindings.LatentRuntimeActivation.waits == 1, "fired-timer-not-awaited-twice");
        first.close();
        Bindings.LatentRuntimeActivation.denyStop = true;
        Bindings.LatentRuntimeActivation.stopObservation = () -> {
            try { require((boolean)field(second.getClass(), "closing").get(second), "closing-before-stop-call"); }
            catch (ReflectiveOperationException error) { throw new IllegalStateException(error); }
            require(Bindings.LatentRuntimeActivation.timers() == 1, "charge-retained-until-stop-confirmation");
        };
        denied(second::close);
        require(((List<?>)get("timers")).size() == 1 && Bindings.LatentRuntimeActivation.timers() == 1, "cancelled-stop-retains-record");
        Bindings.LatentRuntimeActivation.denyStop = false; second.close(); Bindings.LatentRuntimeActivation.stopObservation = null;
        require(Bindings.LatentRuntimeActivation.timers() == 0 && ((List<?>)get("timers")).isEmpty(), "confirmed-stop-retires-both-owners");

        var immediate = Activation.timer(Activation.monotonicMillis() - 1);
        require(Bindings.LatentRuntimeActivation.lastNanos == 0, "already-due-zero-delay"); immediate.close();
        var huge = Activation.timer(Long.MAX_VALUE);
        require(Bindings.LatentRuntimeActivation.lastNanos == Long.MAX_VALUE, "huge-wait-preserves-saturation");
        pair(Long.MAX_VALUE - 1); Bindings.LatentRuntimeActivation.denyNext = true; denied(() -> Activation.waitFor(1));
        require(Bindings.LatentRuntimeActivation.timers() == 1, "cancelled-next-keeps-physical-owner");
        Bindings.LatentRuntimeActivation.denyNext = false; huge.close();
        pair(100); int waits = Bindings.LatentRuntimeActivation.waits; Activation.waitFor(1); Activation.waitFor(-1);
        require(Bindings.LatentRuntimeActivation.waits == waits + 2 && Bindings.LatentRuntimeActivation.timers() == 0, "unmatched-and-indefinite-waits-stay-charged");
        require(Monitors.absoluteSleepDeadline(Long.MAX_VALUE - 1, 2) == Long.MAX_VALUE, "pure-saturation-preserved");
        managedStartRollback();
        poolRetirement();
        System.out.println("TIMER_READINESS_SOURCE_CONTROL PASS two-timer-bound;captured-frame-deadline;first-clock-latch;stable-ties;fired-and-closing-exclusion;confirmed-stop;cancelled-ownership;zero-huge-and-fallback;managed-start-rollback");
    }
}
