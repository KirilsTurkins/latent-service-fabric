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
    private static void resetFinishingModel() throws Exception {
        try { set("finishingInvocation", false); } catch (NoSuchFieldException oldSource) { }
    }
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
        Thread ordinary = new Thread();
        Activation.starting(ordinary);
        require(Activation.alive(ordinary) && owners() == original + 1, "ordinary-start-admitted");
        Activation.finished(ordinary);
        require(owners() == original, "ordinary-start-settled");
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
        require(threads.containsKey(uncertain) && owners() == original + 1 && get("failedStarts") != null,
            "accepted-start-keeps-physical-owner");
        Bindings.LatentRuntimeActivation.denySettle = true;
        try { denied(() -> Activation.finished(uncertain)); }
        finally { Bindings.LatentRuntimeActivation.denySettle = false; }
        require(Activation.alive(uncertain) && get("failedStarts") != null,
            "failed-physical-settlement-keeps-uncertain-record");
        Activation.finished(uncertain);
        require(owners() == original && get("failedStarts") == null,
            "confirmed-physical-settlement-unlinks-uncertain-record");

        Bindings.LatentRuntimeActivation.denySettle = true;
        try { Activation.startManaged(rejected); throw new AssertionError("rollback-denial-succeeded"); }
        catch (IllegalStateException error) { require(error.getCause() == failure, "rollback-denial-preserves-start-cause"); }
        finally { Bindings.LatentRuntimeActivation.denySettle = false; }
        require(threads.containsKey(rejected) && owners() == original + 1, "failed-rollback-retains-original-owner");
        denied(() -> Activation.finished(rejected));
        // Private fake teardown only: production waits for Store destruction.
        Object failed = threads.get(rejected);
        var token = (Bindings.LatentRuntimeActivationToken)field(workClass(), "token").get(failed);
        require(!Bindings.LatentRuntimeActivation.settle(token).isError(), "fake-host-teardown");
        var unlink = Activation.class.getDeclaredMethod("unlinkFailedStart", workClass()); unlink.setAccessible(true); unlink.invoke(null, failed);
        ((Map<?, ?>)get("threads")).remove(rejected);
        require(owners() == original, "failed-rollback-private-fake-teardown");
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
        denied(() -> Activation.finished(rejected));
        // Private fake teardown, never a production settlement shortcut.
        Object failed = ((Map<?, ?>)get("threads")).get(rejected);
        var token = (Bindings.LatentRuntimeActivationToken)field(workClass(), "token").get(failed);
        require(!Bindings.LatentRuntimeActivation.settle(token).isError(), "fake-host-failed-start-teardown");
        var unlink = Activation.class.getDeclaredMethod("unlinkFailedStart", workClass()); unlink.setAccessible(true); unlink.invoke(null, failed);
        ((Map<?, ?>)get("threads")).remove(rejected);
        Activation.unmanageRetired(pool);
        require(pools.isEmpty(), "private-fake-teardown-releases-pool");
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
    private static Object failedWork(Pool pool) throws Exception {
        var token = Bindings.LatentRuntimeActivation.register(Bindings.LatentRuntimeActivationOwnerKind.ManagedIdleWorker, Option.none()).value();
        var constructor = workClass().getDeclaredConstructor(Bindings.LatentRuntimeActivationToken.class); constructor.setAccessible(true);
        Object work = constructor.newInstance(token);
        field(workClass(), "managed").set(work, true);
        field(workClass(), "prepared").set(work, true);
        field(workClass(), "pool").set(work, pool);
        return work;
    }
    private static Object failedOrdinaryWork() throws Exception {
        var token = Bindings.LatentRuntimeActivation.register(Bindings.LatentRuntimeActivationOwnerKind.Task, Option.none()).value();
        var constructor = workClass().getDeclaredConstructor(Bindings.LatentRuntimeActivationToken.class); constructor.setAccessible(true);
        return constructor.newInstance(token);
    }
    private static void rollbackInsertion(Thread thread, Object work) throws Exception {
        var rollback = Activation.class.getDeclaredMethod("rollbackInsertion", Thread.class, workClass());
        rollback.setAccessible(true); rollback.invoke(null, thread, work);
    }
    private static void failedStartedWorkerPoisons() throws Exception {
        set("closing", false); set("retiringPools", false); set("rootComplete", false);
        Pool pool = new Pool(); Activation.manage(pool);
        var failure = new IllegalThreadStateException("source-accepted-start-failed");
        Thread thread = new Thread() { @Override public void start() { Activation.starting(this); throw failure; } };
        try { Activation.startManaged(thread, pool); throw new AssertionError("expected-accepted-start-failure"); }
        catch (IllegalThreadStateException expected) { require(expected == failure, "accepted-start-original-error"); }
        var finish = Activation.class.getDeclaredMethod("finishInvocation"); finish.setAccessible(true);
        finish.invoke(null);
        require((boolean)get("poisoned") && !(boolean)get("entered") && Activation.alive(thread),
            "failed-start-poisons-and-preserves-owner");
        try { Activation.invoke(0, null, 0); throw new AssertionError("failed-start-store-reentered"); }
        catch (IllegalStateException expected) { require(expected.getMessage().equals("activation-runtime-poisoned-store"), "failed-start-reentry-error"); }
        // Test-only simulation of physical completion and a fresh Store.
        Activation.finished(thread);
        require(get("failedStarts") == null, "physical-completion-unlinks-before-fresh-store");
        set("poisoned", false); set("entered", true); resetFinishingModel();
        pool.retire();
    }
    private static void uncertainQueuedOwnersPoison() throws Exception {
        int original = owners(), count = 16;
        Activation.Lease[] leases = new Activation.Lease[count];
        for (int i = 0; i < count; i++)
            leases[i] = Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork);
        require(owners() == original + count, "queued-retention-admitted-before-failure");
        var ready = new java.util.concurrent.CountDownLatch(count);
        var start = new java.util.concurrent.CountDownLatch(1);
        Thread[] workers = new Thread[count];
        for (int i = 0; i < count; i++) {
            Activation.Lease lease = leases[i];
            workers[i] = new Thread(() -> {
                ready.countDown();
                try { start.await(); } catch (InterruptedException error) { throw new AssertionError(error); }
                Activation.fenceUncertainQueuedWorkSettlement(lease);
            });
            workers[i].start();
        }
        require(ready.await(5, java.util.concurrent.TimeUnit.SECONDS), "queued-retention-ready");
        start.countDown();
        for (Thread worker : workers) { worker.join(5000); require(!worker.isAlive(), "queued-retention-joined"); }
        @SuppressWarnings("unchecked") AtomicReference<Activation.Lease> head =
            (AtomicReference<Activation.Lease>)get("failedQueuedOwners");
        var next = field(Activation.Lease.class, "nextFailedQueued");
        var seen = java.util.Collections.newSetFromMap(new java.util.IdentityHashMap<Activation.Lease, Boolean>());
        for (Activation.Lease cursor = head.get(); cursor != null; cursor = (Activation.Lease)next.get(cursor))
            require(seen.add(cursor) && seen.size() <= count, "queued-retention-distinct-acyclic");
        for (Activation.Lease lease : leases) require(seen.contains(lease), "queued-retention-original-owner-rooted");
        require(seen.size() == count && (boolean)get("poisoned"), "queued-retention-all-preexisting-owners");
        for (int i = 0; i < 8; i++) {
            try { Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork); throw new AssertionError("queued-owner-after-poison"); }
            catch (IllegalStateException expected) { require(expected.getMessage().equals("activation-runtime-poisoned-store"), "queued-admission-refused"); }
        }
        try { Activation.starting(new Thread()); throw new AssertionError("task-owner-after-poison"); }
        catch (IllegalStateException expected) { require(expected.getMessage().equals("activation-runtime-poisoned-store"), "task-admission-refused"); }
        try { Activation.timer(1); throw new AssertionError("timer-owner-after-poison"); }
        catch (IllegalStateException expected) { require(expected.getMessage().equals("activation-runtime-poisoned-store"), "timer-admission-refused"); }
        try { Activation.waitFor(1); throw new AssertionError("wait-owner-after-poison"); }
        catch (IllegalStateException expected) { require(expected.getMessage().equals("activation-runtime-poisoned-store"), "wait-admission-refused"); }
        require(owners() == original + count && head.get() != null, "poison-does-not-admit-or-settle-owners");
        var completion = Activation.class.getDeclaredMethod("requireHealthyCompletion"); completion.setAccessible(true);
        try { completion.invoke(null); throw new AssertionError("uncertain-queued-completed"); }
        catch (java.lang.reflect.InvocationTargetException expected) {
            require(expected.getCause() instanceof IllegalStateException
                && expected.getCause().getMessage().equals("activation-runtime-owner-settlement-uncertain"), "uncertain-queued-completion-refused");
        }
        var finish = Activation.class.getDeclaredMethod("finishInvocation"); finish.setAccessible(true); finish.invoke(null);
        require(!(boolean)get("entered") && head.get() != null && owners() == original + count,
            "uncertain-queued-store-retains-owners");
        try { Activation.invoke(0, null, 0); throw new AssertionError("uncertain-queued-store-reentered"); }
        catch (IllegalStateException expected) { require(expected.getMessage().equals("activation-runtime-poisoned-store"), "uncertain-queued-reentry-refused"); }
        // Private source-control teardown simulates destroying the poisoned Store.
        head.set(null);
        for (Activation.Lease lease : leases) lease.close();
        set("poisoned", false); set("entered", true); resetFinishingModel();
        require(owners() == original, "queued-retention-control-cleanup");
    }
    private static void uncertainResultPoisons() throws Exception {
        Object root = get("root"), threads = get("threads"), pools = get("pools");
        int originalOwners = owners();
        int originalThreads = ((Map<?, ?>)threads).size(), originalPools = ((List<?>)pools).size();
        require(root != null && originalThreads > 0 && !(boolean)get("poisoned"), "initial-result-fence-clear");
        Activation.fenceUncertainResultSettlement();
        var completion = Activation.class.getDeclaredMethod("requireHealthyCompletion"); completion.setAccessible(true);
        try { completion.invoke(null); throw new AssertionError("uncertain-result-completed"); }
        catch (java.lang.reflect.InvocationTargetException expected) {
            require(expected.getCause() instanceof IllegalStateException
                && expected.getCause().getMessage().equals("activation-runtime-owner-settlement-uncertain"), "uncertain-result-completion-refused");
        }
        var finish = Activation.class.getDeclaredMethod("finishInvocation"); finish.setAccessible(true); finish.invoke(null);
        require((boolean)get("poisoned") && !(boolean)get("entered") && get("root") == root
            && get("threads") == threads && ((Map<?, ?>)threads).size() == originalThreads
            && get("pools") == pools && ((List<?>)pools).size() == originalPools && owners() == originalOwners,
            "uncertain-result-poisons-and-preserves-store");
        try { Activation.invoke(0, null, 0); throw new AssertionError("uncertain-result-store-reentered"); }
        catch (IllegalStateException expected) { require(expected.getMessage().equals("activation-runtime-poisoned-store"), "uncertain-result-reentry-refused"); }
        // Private control only: simulate a fresh Store for the remaining cases.
        set("poisoned", false); set("entered", true); resetFinishingModel();
    }
    private static void failedInsertionsAndPoison() throws Exception {
        set("closing", false); set("retiringPools", false); set("rootComplete", false);
        @SuppressWarnings("unchecked") Map<Thread, Object> threads = (Map<Thread, Object>)get("threads");
        @SuppressWarnings("unchecked") List<Activation.ManagedPool> pools = (List<Activation.ManagedPool>)get("pools");
        Pool pool = new Pool(); Activation.manage(pool);
        int original = owners();
        Thread partial = new Thread(), nested = new Thread();
        Object recovered = failedWork(pool), denied = failedWork(pool);
        threads.put(partial, recovered); // Model a put that threw after insertion.
        Bindings.LatentRuntimeActivation.settleObservation = () -> {
            Bindings.LatentRuntimeActivation.denySettle = true;
            try { rollbackInsertion(nested, denied); }
            catch (Exception error) { throw new IllegalStateException(error); }
            finally { Bindings.LatentRuntimeActivation.denySettle = false; }
        };
        rollbackInsertion(partial, recovered);
        require(!threads.containsKey(partial) && !Activation.alive(partial)
            && field(workClass(), "pool").get(recovered) == null && (boolean)field(workClass(), "complete").get(recovered),
            "confirmed-partial-insertion-releases-pool");
        require(Activation.alive(nested) && Activation.ownsManaged(nested, pool)
            && !Activation.runningManaged(nested, pool), "reentrant-denial-retains-exact-other-record");
        Thread thrown = new Thread(); Object uncertain = failedWork(pool);
        RuntimeException failure = new RuntimeException("source-settlement-threw");
        Bindings.LatentRuntimeActivation.settleFailure = failure;
        try { rollbackInsertion(thrown, uncertain); }
        finally { Bindings.LatentRuntimeActivation.settleFailure = null; }
        require(Activation.alive(thrown) && Activation.ownsManaged(thrown, pool), "throwing-settlement-retains-owner");
        Thread ordinaryDenied = new Thread(), ordinaryThrown = new Thread();
        Object deniedTask = failedOrdinaryWork(), thrownTask = failedOrdinaryWork();
        Bindings.LatentRuntimeActivation.denySettle = true;
        try { rollbackInsertion(ordinaryDenied, deniedTask); }
        finally { Bindings.LatentRuntimeActivation.denySettle = false; }
        Bindings.LatentRuntimeActivation.settleFailure = failure;
        try { rollbackInsertion(ordinaryThrown, thrownTask); }
        finally { Bindings.LatentRuntimeActivation.settleFailure = null; }
        require(Activation.alive(ordinaryDenied) && Activation.alive(ordinaryThrown), "ordinary-failed-insertion-retains-both-owners");
        try { Activation.starting(ordinaryDenied); throw new AssertionError("ordinary-uncertain-start"); }
        catch (IllegalThreadStateException expected) { }
        require(owners() == original + 4, "only-confirmed-insertion-owner-settled");
        try { Activation.startManaged(nested, pool); throw new AssertionError("duplicate-failed-insertion-start"); }
        catch (IllegalThreadStateException expected) { }
        try { Activation.starting(thrown); throw new AssertionError("uncertain-insertion-start"); }
        catch (IllegalThreadStateException expected) { }
        denied(() -> Activation.finished(nested));
        pool.retire();
        require(pools.contains(pool), "failed-insertion-retains-retired-pool");
        set("rootComplete", true); set("closing", true);
        var pending = Activation.class.getDeclaredMethod("pending"); pending.setAccessible(true);
        require((boolean)pending.invoke(null), "unindexed-owner-keeps-activation-pending");
        var retire = Activation.class.getDeclaredMethod("retireIdlePools"); retire.setAccessible(true);
        require(!(boolean)retire.invoke(null), "ordinary-unindexed-owner-prevents-pool-retirement");
        var finish = Activation.class.getDeclaredMethod("finishInvocation"); finish.setAccessible(true);
        finish.invoke(null);
        require((boolean)get("poisoned") && !(boolean)get("entered") && pools.contains(pool)
            && Activation.alive(nested) && Activation.alive(thrown)
            && Activation.alive(ordinaryDenied) && Activation.alive(ordinaryThrown), "failed-insertion-poisons-and-retains-store");
        try { Activation.invoke(0, null, 0); throw new AssertionError("poisoned-store-reentered"); }
        catch (IllegalStateException expected) { require(expected.getMessage().equals("activation-runtime-poisoned-store"), "poisoned-reentry-error"); }
        require(owners() == original + 3, "poisoned-reentry-does-not-change-host-custody");
    }
    // Every scenario gets a fresh private ledger; this is not guest retirement.
    @SuppressWarnings("unchecked")
    private static void resetTimerStopModel() throws Exception {
        ((Map<?, ?>)get("threads")).clear();
        ((List<?>)get("timers")).clear();
        ((Map<?, ?>)field(Bindings.LatentRuntimeActivation.class, "owners").get(null)).clear();
        set("root", null); set("entered", false); set("poisoned", false); resetFinishingModel();
        try { set("pendingTimerStops", 0); } catch (NoSuchFieldException oldSource) { }
        Bindings.LatentRuntimeActivation.stopObservation = null;
        Bindings.LatentRuntimeActivation.denyStop = false;
        Bindings.LatentRuntimeActivation.stops = 0;
    }
    private static void startTimerStopModel() throws Exception {
        resetTimerStopModel();
        set("entered", true); set("root", work(Thread.currentThread()));
    }
    private static Bindings.LatentRuntimeActivationToken timerToken(Activation.Lease timer) throws Exception {
        return (Bindings.LatentRuntimeActivationToken)field(Activation.Lease.class, "token").get(timer);
    }
    private static void finishTimerStopModel() throws Exception {
        var finish = Activation.class.getDeclaredMethod("finishInvocation"); finish.setAccessible(true); finish.invoke(null);
    }
    private static void timerStopNormal() throws Exception {
        var normal = Activation.timer(Activation.monotonicMillis() + 1000);
        normal.close(); normal.close();
        require(Bindings.LatentRuntimeActivation.stops == 1 && Bindings.LatentRuntimeActivation.timers() == 0,
            "normal-stop-is-idempotent");
        var refused = Activation.timer(Activation.monotonicMillis() + 1000);
        Bindings.LatentRuntimeActivation.denyStop = true;
        try { refused.close(); throw new AssertionError("returned-refusal-was-accepted"); }
        catch (IllegalStateException failure) {
            require(failure.getMessage().equals("activation-runtime-timer-stop-Cancelled"), "returned-refusal-error-preserved");
        }
        require(!(boolean)get("poisoned") && Bindings.LatentRuntimeActivation.timers() == 1,
            "returned-refusal-retains-original-owner");
        Bindings.LatentRuntimeActivation.denyStop = false;
        refused.close();
        require(Bindings.LatentRuntimeActivation.stops == 3 && Bindings.LatentRuntimeActivation.timers() == 0,
            "returned-refusal-can-retry-successfully");
    }
    private static void timerStopReentry() throws Exception {
        var timer = Activation.timer(Activation.monotonicMillis() + 1000);
        var nested = new AtomicReference<Throwable>();
        Bindings.LatentRuntimeActivation.stopObservation = () -> {
            Bindings.LatentRuntimeActivation.stopObservation = null;
            try { timer.close(); } catch (Throwable failure) { nested.set(failure); }
        };
        try { timer.close(); }
        catch (Throwable failure) { throw new AssertionError("reentrant-stop-submitted-twice", failure); }
        require(nested.get() instanceof IllegalStateException && Bindings.LatentRuntimeActivation.stops == 1,
            "reentrant-stop-rejected-before-host-call");
        require((boolean)get("poisoned"), "reentrant-stop-fences-completion");
    }
    private static void timerStopReentryUncaught() throws Exception {
        var timer = Activation.timer(Activation.monotonicMillis() + 1000);
        var token = timerToken(timer);
        Bindings.LatentRuntimeActivation.stopObservation = () -> {
            Bindings.LatentRuntimeActivation.stopObservation = null;
            timer.close();
        };
        denied(timer::close);
        require(Bindings.LatentRuntimeActivation.stops == 1 && (boolean)get("poisoned")
            && timerToken(timer).equals(token) && ((List<?>)get("timers")).contains(timer),
            "uncaught-reentry-retains-original-and-fences");
    }
    private static void timerStopNested() throws Exception {
        long deadline = Activation.monotonicMillis() + 1000;
        var first = Activation.timer(deadline);
        var second = otherTimer(deadline);
        var nested = new AtomicReference<Throwable>();
        Bindings.LatentRuntimeActivation.stopObservation = () -> {
            Bindings.LatentRuntimeActivation.stopObservation = null;
            try {
                first.close();
                require((int)get("pendingTimerStops") == 1, "one-stop-remains-after-nested-cleanup");
                var completion = Activation.class.getDeclaredMethod("requireHealthyCompletion"); completion.setAccessible(true);
                try { completion.invoke(null); throw new AssertionError("nested-stop-completion-was-allowed"); }
                catch (java.lang.reflect.InvocationTargetException failure) {
                    require(failure.getCause() instanceof IllegalStateException, "nested-stop-completion-refused");
                }
            } catch (Throwable failure) { nested.set(failure); }
        };
        second.close();
        if (nested.get() != null) throw new AssertionError("nested-stop", nested.get());
        require(Bindings.LatentRuntimeActivation.stops == 2 && (int)get("pendingTimerStops") == 0
            && (boolean)get("poisoned"), "nested-stops-counted-through-cleanup");
    }
    private static void timerStopOverflow() throws Exception {
        var timer = Activation.timer(Activation.monotonicMillis() + 1000);
        var token = timerToken(timer);
        set("pendingTimerStops", Integer.MAX_VALUE);
        denied(timer::close);
        require(Bindings.LatentRuntimeActivation.stops == 0 && (boolean)get("poisoned")
            && timerToken(timer).equals(token), "counter-overflow-fails-closed-before-stop");
    }
    private static void timerStopRootCollision(boolean checkCompletionFirst) throws Exception {
        var timer = Activation.timer(Activation.monotonicMillis() + 1000);
        var collision = new AtomicReference<Throwable>();
        Bindings.LatentRuntimeActivation.stopObservation = () -> {
            Bindings.LatentRuntimeActivation.stopObservation = null;
            try {
                if (checkCompletionFirst) {
                    var completion = Activation.class.getDeclaredMethod("requireHealthyCompletion"); completion.setAccessible(true);
                    try { completion.invoke(null); throw new AssertionError("root-inflight-completion-was-allowed"); }
                    catch (java.lang.reflect.InvocationTargetException failure) {
                        require(failure.getCause() instanceof IllegalStateException, "root-inflight-completion-refused");
                    }
                }
                finishTimerStopModel();
                require((boolean)get("poisoned") && !(boolean)get("entered") && ((List<?>)get("timers")).contains(timer),
                    "root-inflight-teardown-retains-record");
            } catch (Throwable failure) { collision.set(failure); }
        };
        timer.close();
        if (collision.get() != null) throw new AssertionError("root-collision", collision.get());
        require(Bindings.LatentRuntimeActivation.stops == 1 && (boolean)get("poisoned"), "root-collision-fenced");
    }
    private static void timerStopLateFinally(boolean returning) throws Exception {
        var timer = Activation.timer(Activation.monotonicMillis() + 1000);
        var original = new IllegalStateException("original-root-failure");
        var callbackFailure = new AtomicReference<Throwable>();
        Object root = get("root");
        Bindings.LatentRuntimeActivation.stopObservation = () -> {
            Bindings.LatentRuntimeActivation.stopObservation = null;
            try {
                var finish = Activation.class.getDeclaredMethod("finishInvocation", boolean.class); finish.setAccessible(true);
                if (returning) {
                    try { finish.invoke(null, true); throw new AssertionError("late-success-return-was-allowed"); }
                    catch (java.lang.reflect.InvocationTargetException failure) {
                        require(failure.getCause() instanceof IllegalStateException, "late-success-refused");
                    }
                } else {
                    Throwable observed = null;
                    try { try { throw original; } finally { finish.invoke(null, false); } }
                    catch (Throwable failure) { observed = failure; }
                    require(observed == original, "finally-masked-original-error");
                }
                require((boolean)get("poisoned") && !(boolean)get("entered")
                    && ((List<?>)get("timers")).contains(timer) && field(root.getClass(), "timer").get(root) == timer,
                    "late-finally-did-not-retain-timer");
            } catch (Throwable failure) { callbackFailure.set(failure); }
        };
        timer.close();
        if (callbackFailure.get() != null) throw new AssertionError("late-finally", callbackFailure.get());
        require((boolean)get("poisoned") && Bindings.LatentRuntimeActivation.stops == 1,
            "late-finally-completion-not-fenced");
    }
    private static void timerTeardownRegistered() throws Exception {
        var timer = Activation.timer(Activation.monotonicMillis() + 1000);
        var original = timerToken(timer); Object root = get("root");
        var finish = Activation.class.getDeclaredMethod("finishInvocation", boolean.class); finish.setAccessible(true);
        try { finish.invoke(null, true); throw new AssertionError("live-timer-teardown-succeeded"); }
        catch (java.lang.reflect.InvocationTargetException failure) {
            require(failure.getCause() instanceof IllegalStateException, "live-timer-completion-refused");
        }
        denied(timer::close);
        require((boolean)get("poisoned") && !(boolean)get("entered") && ((List<?>)get("timers")).contains(timer)
            && field(root.getClass(), "timer").get(root) == timer && timerToken(timer).equals(original)
            && Bindings.LatentRuntimeActivation.stops == 0, "teardown-retains-and-does-not-stop-timer");
    }
    private static void timerTeardownExceptional() throws Exception {
        var timer = Activation.timer(Activation.monotonicMillis() + 1000);
        var original = new IllegalStateException("original-teardown-failure"); Throwable observed = null;
        var finish = Activation.class.getDeclaredMethod("finishInvocation", boolean.class); finish.setAccessible(true);
        try { try { throw original; } finally { finish.invoke(null, false); } }
        catch (Throwable failure) { observed = failure; }
        require(observed == original && (boolean)get("poisoned") && ((List<?>)get("timers")).contains(timer),
            "exceptional-teardown-preserves-primary-and-timer");
    }
    private static void timerTeardownClean(boolean closeTimer) throws Exception {
        if (closeTimer) Activation.timer(Activation.monotonicMillis() + 1000).close();
        var finish = Activation.class.getDeclaredMethod("finishInvocation", boolean.class); finish.setAccessible(true);
        finish.invoke(null, true);
        require(!(boolean)get("poisoned") && !(boolean)get("entered") && !(boolean)get("finishingInvocation")
            && get("root") == null && ((List<?>)get("timers")).isEmpty(), "clean-teardown-changed");
    }
    private static void timerStopThrow(boolean loseAcknowledgement) throws Exception {
        var timer = Activation.timer(Activation.monotonicMillis() + 1000);
        var token = timerToken(timer);
        var marker = new IllegalStateException(loseAcknowledgement ? "stop-lost-ack" : "stop-threw-before-result");
        Bindings.LatentRuntimeActivation.stopObservation = () -> {
            Bindings.LatentRuntimeActivation.stopObservation = null;
            if (loseAcknowledgement)
                require(!Bindings.LatentRuntimeActivation.settle(token).isError(), "fake-host-stop-before-lost-ack");
            throw marker;
        };
        try { timer.close(); throw new AssertionError("throwing-stop-returned"); }
        catch (IllegalStateException failure) { require(failure == marker, "original-stop-error-preserved"); }
        require((boolean)get("poisoned") && ((List<?>)get("timers")).contains(timer), "throwing-stop-retains-and-poisons");
        require(Bindings.LatentRuntimeActivation.timers() == (loseAcknowledgement ? 0 : 1), "fake-host-outcome-distinguished");
        denied(timer::close);
        require(Bindings.LatentRuntimeActivation.stops == 1 && timerToken(timer).equals(token), "uncertain-stop-not-retried");
        finishTimerStopModel();
        require((boolean)get("poisoned") && !(boolean)get("entered") && ((List<?>)get("timers")).contains(timer),
            "throwing-stop-retained-through-teardown");
        denied(() -> Activation.invoke(0, null, 0));
    }
    private static void timerStopCase(String mode) throws Exception {
        startTimerStopModel();
        switch (mode) {
            case "normal" -> timerStopNormal();
            case "reentry" -> timerStopReentry();
            case "reentry-uncaught" -> timerStopReentryUncaught();
            case "nested" -> timerStopNested();
            case "overflow" -> timerStopOverflow();
            case "root-collision" -> timerStopRootCollision(true);
            case "root-finally-only" -> timerStopRootCollision(false);
            case "late-return" -> timerStopLateFinally(true);
            case "primary-error" -> timerStopLateFinally(false);
            case "teardown-registered" -> timerTeardownRegistered();
            case "teardown-exception" -> timerTeardownExceptional();
            case "teardown-empty" -> timerTeardownClean(false);
            case "teardown-confirmed" -> timerTeardownClean(true);
            case "thrown" -> timerStopThrow(false);
            case "lost-ack" -> timerStopThrow(true);
            default -> throw new IllegalArgumentException("unknown timer stop control");
        }
    }

    public static void main(String[] arguments) throws Exception {
        if (arguments.length == 1) {
            timerStopCase(arguments[0]);
            System.out.println("TIMER_STOP_CONTROL PASS " + arguments[0]);
            return;
        }
        for (String mode : new String[]{"normal", "reentry", "reentry-uncaught", "nested", "overflow", "root-collision", "root-finally-only", "late-return", "primary-error", "teardown-registered", "teardown-exception", "teardown-empty", "teardown-confirmed", "thrown", "lost-ack"})
            timerStopCase(mode);
        resetTimerStopModel(); // private fake teardown; production never resets uncertainty.
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
        uncertainQueuedOwnersPoison();
        uncertainResultPoisons();
        failedStartedWorkerPoisons();
        failedInsertionsAndPoison();
        System.out.println("TIMER_READINESS_SOURCE_CONTROL PASS two-timer-bound;captured-frame-deadline;first-clock-latch;stable-ties;fired-and-closing-exclusion;confirmed-stop;cancelled-ownership;zero-huge-and-fallback;managed-start-rollback;uncertain-result-fence;uncertain-queued-owner-fence;timer-stop-uncertain-completion-fence;nested-stop-count-guard;timer-finally-return-fence;timer-teardown-admission-fence");
    }
}
