import dev.latent.generated.Bindings;
import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.Option;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.Executors;
import java.lang.reflect.Field;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Future;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Real Activation and pool sources with a private host stand-in, not a guest. */
public final class ManagedFirstAdmissionActivationControl {
    private static void require(boolean value, String message) { if (!value) throw new AssertionError(message); }
    private static void await(CountDownLatch latch, String message) throws InterruptedException {
        require(latch.await(5, TimeUnit.SECONDS), message);
    }
    private static void awaitIdle(Activation.ManagedPool pool) {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
        while (pool.hasPendingWork()) {
            require(System.nanoTime() - deadline < 0, "pool-did-not-become-idle");
            Thread.yield();
        }
    }
    private static Field field(String name) throws Exception {
        var field = Activation.class.getDeclaredField(name); field.setAccessible(true); return field;
    }
    private static Object invoke(String name) throws Exception {
        var method = Activation.class.getDeclaredMethod(name); method.setAccessible(true); return method.invoke(null);
    }
    @SuppressWarnings("unchecked") private static Object enter() throws Exception {
        field("entered").setBoolean(null, true);
        var token = Bindings.LatentRuntimeActivation.register(LatentRuntimeActivationOwnerKind.Task, Option.none()).value();
        var type = Class.forName("dev.latent.guest.runtime.Activation$Work");
        var constructor = type.getDeclaredConstructor(Bindings.LatentRuntimeActivationToken.class); constructor.setAccessible(true);
        Object root = constructor.newInstance(token); field("root").set(null, root);
        ((Map<Thread, Object>)field("threads").get(null)).put(Thread.currentThread(), root);
        return root;
    }
    private static void held(int tasks, int queue, int result, int executor) {
        require(Bindings.LatentRuntimeActivation.owners(LatentRuntimeActivationOwnerKind.Task) == tasks
            && Bindings.LatentRuntimeActivation.owners(LatentRuntimeActivationOwnerKind.QueuedWork) == queue
            && Bindings.LatentRuntimeActivation.owners(LatentRuntimeActivationOwnerKind.Result) == result
            && Bindings.LatentRuntimeActivation.owners(LatentRuntimeActivationOwnerKind.Executor) == executor, "original-owners");
    }
    private static void finish(Object root) throws Exception {
        require(!(boolean)invoke("pending"), "root-still-pending");
        field("finishingInvocation").setBoolean(null, true);
        var finish = Activation.class.getDeclaredMethod("finishWork", Thread.class, root.getClass(), boolean.class);
        finish.setAccessible(true); finish.invoke(null, null, root, true);
        held(0, 0, 0, 0); invoke("finishInvocation");
    }
    private static void withdrawn() throws Exception {
        Object root = enter(); var entered = new CountDownLatch(1); var release = new CountDownLatch(1);
        var created = new AtomicReference<Thread>(); var failure = new AtomicReference<Throwable>();
        var first = new AtomicReference<Future<?>>(); var calls = new AtomicInteger();
        var pool = Executors.newFixedThreadPool(1, target -> {
            entered.countDown();
            try { await(release, "factory-release"); } catch (InterruptedException error) { throw new AssertionError(error); }
            var worker = new Thread(target); created.set(worker); return worker;
        });
        Thread caller = new Thread(() -> {
            try { first.set(pool.submit(calls::incrementAndGet)); } catch (Throwable error) { failure.set(error); }
            finally { Activation.finished(Thread.currentThread()); }
        });
        Activation.starting(caller);
        try {
            caller.start(); await(entered, "factory-not-entered"); held(2, 1, 1, 1);
            var nested = pool.submit(calls::incrementAndGet); held(2, 2, 2, 1);
            field("rootComplete").setBoolean(null, true); invoke("closeCompletedRoot");
            var removed = pool.shutdownNow();
            require(removed.size() == 1 && removed.get(0) == nested && !pool.isTerminated()
                && ((Activation.ManagedPool)pool).hasPendingWork() && (int)invoke("scanPendingPools") == 1
                && (boolean)invoke("pending") && !(boolean)invoke("retireIdlePools"), "first-root-fence");
            held(2, 1, 1, 1);
            release.countDown(); caller.join(5000);
            require(!caller.isAlive() && failure.get() instanceof RejectedExecutionException && first.get() == null
                && created.get() != null && created.get().getState() == Thread.State.NEW
                && pool.isTerminated() && calls.get() == 0, "rejected-first-retirement");
            held(1, 0, 0, 0); require(nested.cancel(false), "nested-cancel"); invoke("retireIdlePools"); finish(root);
        } finally { release.countDown(); caller.join(5000); pool.shutdown(); }
    }
    private static void registering() throws Exception {
        Object root = enter(); var entered = new CountDownLatch(1); var release = new CountDownLatch(1);
        class DeferredInterruptThread extends Thread {
            volatile boolean requested;
            DeferredInterruptThread(Runnable target) { super(target); }
            @Override public void interrupt() { requested = true; }
            void deliver() { super.interrupt(); }
        }
        var worker = new AtomicReference<DeferredInterruptThread>(); var failure = new AtomicReference<Throwable>();
        var result = new AtomicReference<Future<?>>(); var observation = new AtomicReference<Boolean>();
        var observationError = new AtomicReference<Throwable>(); var calls = new AtomicInteger();
        var pool = Executors.newFixedThreadPool(1, target -> {
            entered.countDown();
            try { await(release, "factory-release"); } catch (InterruptedException error) { throw new AssertionError(error); }
            var thread = new DeferredInterruptThread(() -> {
                try { Activation.starting(Thread.currentThread()); target.run(); }
                finally { Activation.finished(Thread.currentThread()); }
            });
            worker.set(thread); return thread;
        });
        Thread caller = new Thread(() -> {
            try { result.set(pool.submit(calls::incrementAndGet)); } catch (Throwable error) { failure.set(error); }
            finally { Activation.finished(Thread.currentThread()); }
        });
        Activation.starting(caller);
        try {
            caller.start(); await(entered, "factory-not-entered"); held(2, 1, 1, 1);
            field("rootComplete").setBoolean(null, true); invoke("closeCompletedRoot");
            Bindings.LatentRuntimeActivation.registrationObservation = () -> {
                try {
                    var entering = pool.getClass().getDeclaredField("enteringWorkers"); entering.setAccessible(true);
                    var starting = pool.getClass().getDeclaredField("startingWorkers"); starting.setAccessible(true);
                    observation.set(entering.getInt(pool) == 1 && starting.getInt(pool) == 0
                        && ((Activation.ManagedPool)pool).hasPendingWork() && (int)invoke("scanPendingPools") == 1
                        && !((Activation.ManagedPool)pool).isRetired() && (boolean)invoke("pending")
                        && !(boolean)invoke("retireIdlePools"));
                } catch (Throwable error) { observationError.set(error); }
            };
            release.countDown(); caller.join(5000);
            require(!caller.isAlive() && failure.get() == null && result.get() != null && observationError.get() == null
                && Boolean.TRUE.equals(observation.get()), "worker-registration-root-fence");
            result.get().get(5, TimeUnit.SECONDS); require(calls.get() == 1, "first-not-run");
            awaitIdle((Activation.ManagedPool)pool);
            invoke("retireIdlePools"); require(worker.get().requested, "worker-interrupt-not-requested");
            worker.get().deliver(); worker.get().join(5000);
            require(!worker.get().isAlive() && ((Activation.ManagedPool)pool).isRetired()
                && Bindings.LatentRuntimeActivation.owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 0,
                "worker-retirement");
            held(1, 0, 0, 0); finish(root);
        } finally { release.countDown(); caller.join(5000); pool.shutdown(); }
    }
    private static void identityReentry(boolean concurrent) throws Exception {
        Object root = enter();
        class Pool implements Activation.ManagedPool {
            public boolean hasPendingWork() { return false; }
            public boolean isRetired() { return true; }
            public void closeAtRoot() { }
        }
        var firstPool = new Pool(); var secondPool = new Pool(); Activation.manage(firstPool); Activation.manage(secondPool);
        var nestedFailure = new AtomicReference<Throwable>(); var observation = new AtomicReference<Boolean>();
        var calls = new AtomicInteger();
        class DeferredThread extends Thread {
            int starts;
            DeferredThread() { super(() -> {
                try { Activation.starting(Thread.currentThread()); calls.incrementAndGet(); }
                finally { Activation.finished(Thread.currentThread()); }
            }); }
            @Override public synchronized void start() { starts++; }
            synchronized void physicalStart() { super.start(); }
        }
        var thread = new DeferredThread();
        Bindings.LatentRuntimeActivation.registrationObservation = () -> {
            Runnable duplicate = () -> {
                try { Activation.startManaged(thread, secondPool); }
                catch (Throwable error) { nestedFailure.set(error); }
            };
            if (concurrent) {
                var helper = new Thread(duplicate); helper.start();
                try { helper.join(5000); } catch (InterruptedException error) { throw new AssertionError(error); }
                require(!helper.isAlive(), "duplicate-admission-blocked");
            } else duplicate.run();
            try {
                field("rootComplete").setBoolean(null, true);
                observation.set(field("startingWorks").get(null) != null && (boolean)invoke("pending"));
            } catch (Exception error) { throw new AssertionError(error); }
            finally {
                try { field("rootComplete").setBoolean(null, false); }
                catch (Exception error) { throw new AssertionError(error); }
            }
        };
        Activation.startManaged(thread, firstPool);
        require(nestedFailure.get() instanceof IllegalThreadStateException && Boolean.TRUE.equals(observation.get())
            && field("startingWorks").get(null) == null && thread.starts == 1
            && Activation.ownsManaged(thread, firstPool) && !Activation.ownsManaged(thread, secondPool)
            && Bindings.LatentRuntimeActivation.owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 1,
            "cross-pool-identity-was-overwritten");
        thread.physicalStart(); thread.join(5000);
        require(!thread.isAlive() && calls.get() == 1
            && Bindings.LatentRuntimeActivation.owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 0,
            "original-managed-work-not-settled");
        Activation.unmanageRetired(firstPool); Activation.unmanageRetired(secondPool);
        field("rootComplete").setBoolean(null, true); invoke("closeCompletedRoot"); invoke("retireIdlePools");
        held(1, 0, 0, 0); finish(root);
    }
    private static void ordinaryIdentityReentry(boolean outerManaged) throws Exception {
        Object root = enter();
        class Pool implements Activation.ManagedPool {
            public boolean hasPendingWork() { return false; }
            public boolean isRetired() { return true; }
            public void closeAtRoot() { }
        }
        var pool = new Pool(); Activation.manage(pool);
        var thread = new Thread() { @Override public synchronized void start() { } };
        var nestedFailure = new AtomicReference<Throwable>();
        Bindings.LatentRuntimeActivation.registrationObservation = () -> {
            try {
                if (outerManaged) Activation.starting(thread); else Activation.startManaged(thread, pool);
            } catch (Throwable error) { nestedFailure.set(error); }
        };
        if (outerManaged) Activation.startManaged(thread, pool); else Activation.starting(thread);
        require(nestedFailure.get() instanceof IllegalThreadStateException && field("startingWorks").get(null) == null,
            "ordinary-identity-was-overwritten");
        if (outerManaged) {
            require(Activation.ownsManaged(thread, pool)
                && Bindings.LatentRuntimeActivation.owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 1,
                "managed-work-not-owned");
            Activation.starting(thread);
        } else require(Bindings.LatentRuntimeActivation.owners(LatentRuntimeActivationOwnerKind.Task) == 2,
            "ordinary-work-not-owned");
        Activation.finished(thread); Activation.unmanageRetired(pool);
        field("rootComplete").setBoolean(null, true); invoke("closeCompletedRoot"); invoke("retireIdlePools");
        held(1, 0, 0, 0); finish(root);
    }
    private static void crossPoolFactory() throws Exception {
        Object root = enter(); var calls = new AtomicInteger(); var otherCalls = new AtomicInteger();
        var nestedFailure = new AtomicReference<Throwable>();
        class DeferredThread extends Thread {
            int starts;
            volatile boolean requested;
            DeferredThread(Runnable target) { super(() -> {
                try { Activation.starting(Thread.currentThread()); target.run(); }
                finally { Activation.finished(Thread.currentThread()); }
            }); }
            @Override public synchronized void start() { starts++; }
            @Override public void interrupt() { requested = true; }
            synchronized void physicalStart() { super.start(); }
            void deliver() { super.interrupt(); }
        }
        var thread = new AtomicReference<DeferredThread>();
        var other = Executors.newFixedThreadPool(1, target -> thread.get());
        var first = Executors.newFixedThreadPool(1, target -> {
            var created = new DeferredThread(target); thread.set(created);
            Bindings.LatentRuntimeActivation.registrationObservation = () -> {
                try { other.submit(otherCalls::incrementAndGet); }
                catch (Throwable error) { nestedFailure.set(error); }
            };
            return created;
        });
        try {
            var result = first.submit(calls::incrementAndGet);
            require(nestedFailure.get() instanceof IllegalThreadStateException && thread.get().starts == 1
                && Activation.ownsManaged(thread.get(), (Activation.ManagedPool)first)
                && !Activation.ownsManaged(thread.get(), (Activation.ManagedPool)other), "factory-identity-replaced");
            held(1, 1, 1, 2);
            require(Bindings.LatentRuntimeActivation.owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 1,
                "factory-worker-owner-count");
            other.shutdownNow(); require(other.awaitTermination(5, TimeUnit.SECONDS), "other-pool-not-retired");
            field("rootComplete").setBoolean(null, true); invoke("closeCompletedRoot");
            require((boolean)invoke("pending") && !(boolean)invoke("retireIdlePools"), "factory-first-not-fenced");
            thread.get().physicalStart(); require(result.get(5, TimeUnit.SECONDS).equals(1), "first-not-run");
            awaitIdle((Activation.ManagedPool)first);
            invoke("retireIdlePools"); require(thread.get().requested, "factory-interrupt-not-requested");
            thread.get().deliver(); thread.get().join(5000);
            require(!thread.get().isAlive() && ((Activation.ManagedPool)first).isRetired()
                && calls.get() == 1 && otherCalls.get() == 0
                && Bindings.LatentRuntimeActivation.owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 0,
                "factory-owners-not-retired");
            held(1, 0, 0, 0); finish(root);
        } finally { first.shutdownNow(); other.shutdownNow(); }
    }
    private static void independentReentry() throws Exception {
        Object root = enter();
        class Pool implements Activation.ManagedPool {
            public boolean hasPendingWork() { return false; }
            public boolean isRetired() { return true; }
            public void closeAtRoot() { }
        }
        var firstPool = new Pool(); var secondPool = new Pool(); Activation.manage(firstPool); Activation.manage(secondPool);
        var first = new Thread() { @Override public synchronized void start() { } };
        var second = new Thread() { @Override public synchronized void start() { } };
        Bindings.LatentRuntimeActivation.registrationObservation = () -> Activation.startManaged(second, secondPool);
        Activation.startManaged(first, firstPool);
        require(field("startingWorks").get(null) == null && Activation.ownsManaged(first, firstPool)
            && Activation.ownsManaged(second, secondPool)
            && Bindings.LatentRuntimeActivation.owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 2,
            "independent-start-not-preserved");
        Activation.starting(first); Activation.starting(second); Activation.finished(first); Activation.finished(second);
        require(Bindings.LatentRuntimeActivation.owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 0,
            "independent-start-not-settled");
        Activation.unmanageRetired(firstPool); Activation.unmanageRetired(secondPool);
        field("rootComplete").setBoolean(null, true); invoke("closeCompletedRoot"); invoke("retireIdlePools");
        held(1, 0, 0, 0); finish(root);
    }
    private static void admissionHost(boolean cached, boolean resultOwner, String fault, boolean immediate) throws Exception {
        Object root = enter();
        var pool = cached ? Executors.newCachedThreadPool() : Executors.newFixedThreadPool(1);
        var observed = new AtomicReference<Boolean>(); var calls = new AtomicInteger();
        var marker = new IllegalStateException("host-admission-failure");
        Runnable shutdown = () -> {
            if (immediate) require(pool.shutdownNow().isEmpty(), "unpublished-task-exposed");
            else pool.shutdown();
            observed.set(!pool.isTerminated() && ((Activation.ManagedPool)pool).hasPendingWork()
                && Bindings.LatentRuntimeActivation.owners(LatentRuntimeActivationOwnerKind.Executor) == 1);
            if (fault.equals("denied")) Bindings.LatentRuntimeActivation.denySettle = true;
            if (fault.equals("lost")) Bindings.LatentRuntimeActivation.settleAcknowledgementFailure = marker;
            if (fault.equals("unknown")) Bindings.LatentRuntimeActivation.registrationFailure = marker;
        };
        if (resultOwner) Bindings.LatentRuntimeActivation.registrationObservation =
            () -> Bindings.LatentRuntimeActivation.registrationObservation = shutdown;
        else Bindings.LatentRuntimeActivation.registrationObservation = shutdown;
        try {
            try { pool.submit(calls::incrementAndGet); throw new AssertionError("admitted-after-shutdown"); }
            catch (RuntimeException error) {
                require(fault.equals("unknown") ? error == marker : error instanceof RejectedExecutionException,
                    "admission-primary-error-lost");
            }
        } finally {
            Bindings.LatentRuntimeActivation.denySettle = false;
            Bindings.LatentRuntimeActivation.settleAcknowledgementFailure = null;
            Bindings.LatentRuntimeActivation.registrationFailure = null;
        }
        require(Boolean.TRUE.equals(observed.get()) && calls.get() == 0, "admission-executor-retired-early");
        field("rootComplete").setBoolean(null, true); invoke("closeCompletedRoot");
        if (fault.equals("none")) {
            require(pool.awaitTermination(5, TimeUnit.SECONDS), "admission-pool-not-retired"); held(1, 0, 0, 0);
            invoke("retireIdlePools"); finish(root); return;
        }
        int queue = fault.equals("denied") || fault.equals("unknown") && !resultOwner ? 1 : 0;
        int result = resultOwner ? 1 : 0;
        held(1, queue, result, 1);
        require(field("poisoned").getBoolean(null) && !pool.isTerminated()
            && ((Activation.ManagedPool)pool).hasPendingWork() && (boolean)invoke("pending")
            && !(boolean)invoke("retireIdlePools"), "uncertain-admission-not-rooted");
        if (resultOwner) {
            var reserved = pool.getClass().getDeclaredField("reservedFirsts"); reserved.setAccessible(true);
            require(reserved.get(pool) != null, "uncertain-result-command-not-rooted");
        }
        int attempts = Bindings.LatentRuntimeActivation.settlementAttempts;
        pool.shutdownNow(); require(Bindings.LatentRuntimeActivation.settlementAttempts == attempts, "admission-settlement-retried");
        invoke("finishInvocation");
        require(field("root").get(null) == root
            && Bindings.LatentRuntimeActivation.owners(LatentRuntimeActivationOwnerKind.Executor) == 1,
            "uncertain-admission-teardown-lost-owner");
    }
    private static void identityRegistration(boolean uncertain) throws Exception {
        Object root = enter();
        class Pool implements Activation.ManagedPool {
            public boolean hasPendingWork() { return false; }
            public boolean isRetired() { return true; }
            public void closeAtRoot() { }
        }
        var pool = new Pool(); Activation.manage(pool);
        var thread = new Thread() { @Override public synchronized void start() { } };
        var marker = new IllegalStateException("registration-response-lost");
        if (uncertain) Bindings.LatentRuntimeActivation.registrationFailure = marker;
        else Bindings.LatentRuntimeActivation.denyRegistration = true;
        try {
            try { Activation.startManaged(thread, pool); throw new AssertionError("registration-not-refused"); }
            catch (IllegalStateException error) {
                require(uncertain ? error == marker : error.getMessage().contains("activation-runtime-register-"),
                    "wrong-registration-failure");
            }
        } finally {
            Bindings.LatentRuntimeActivation.registrationFailure = null;
            Bindings.LatentRuntimeActivation.denyRegistration = false;
        }
        require(field("startingWorks").get(null) == null && !Activation.ownsManaged(thread, pool), "identity-claim-leaked");
        if (uncertain) {
            require(field("poisoned").getBoolean(null) && field("pendingRegistrations").getInt(null) == 1
                && Bindings.LatentRuntimeActivation.owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 1,
                "unknown-host-owner-not-fenced");
            try { Activation.startManaged(thread, pool); throw new AssertionError("poisoned-admission"); }
            catch (IllegalStateException expected) { }
            invoke("finishInvocation");
            require(field("root").get(null) == root
                && Bindings.LatentRuntimeActivation.owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 1,
                "unknown-host-owner-refunded");
            return;
        }
        require(!field("poisoned").getBoolean(null) && field("pendingRegistrations").getInt(null) == 0,
            "definite-refusal-poisoned");
        Activation.startManaged(thread, pool); Activation.starting(thread); Activation.finished(thread);
        Activation.unmanageRetired(pool);
        field("rootComplete").setBoolean(null, true); invoke("closeCompletedRoot"); invoke("retireIdlePools");
        held(1, 0, 0, 0); finish(root);
    }
    public static void main(String[] args) throws Exception {
        switch (args[0]) {
            case "withdrawn" -> withdrawn(); case "registering" -> registering(); case "identity-reentry" -> identityReentry(false);
            case "identity-concurrent" -> identityReentry(true);
            case "identity-ordinary" -> ordinaryIdentityReentry(true);
            case "identity-task" -> ordinaryIdentityReentry(false);
            case "identity-refused" -> identityRegistration(false);
            case "identity-unknown" -> identityRegistration(true);
            case "identity-factory" -> crossPoolFactory();
            case "identity-independent" -> independentReentry();
            case "fixed-queue-admission" -> admissionHost(false, false, "none", false);
            case "fixed-result-admission" -> admissionHost(false, true, "none", false);
            case "fixed-queue-denied" -> admissionHost(false, false, "denied", false);
            case "fixed-result-denied" -> admissionHost(false, true, "denied", false);
            case "fixed-queue-lost" -> admissionHost(false, false, "lost", false);
            case "fixed-result-lost" -> admissionHost(false, true, "lost", false);
            case "fixed-queue-unknown" -> admissionHost(false, false, "unknown", false);
            case "fixed-result-unknown" -> admissionHost(false, true, "unknown", false);
            case "cached-queue-admission" -> admissionHost(true, false, "none", false);
            case "cached-result-admission" -> admissionHost(true, true, "none", false);
            case "cached-queue-denied" -> admissionHost(true, false, "denied", false);
            case "cached-result-denied" -> admissionHost(true, true, "denied", false);
            case "cached-queue-lost" -> admissionHost(true, false, "lost", false);
            case "cached-result-lost" -> admissionHost(true, true, "lost", false);
            case "cached-queue-unknown" -> admissionHost(true, false, "unknown", false);
            case "cached-result-unknown" -> admissionHost(true, true, "unknown", false);
            case "fixed-queue-now" -> admissionHost(false, false, "none", true);
            case "fixed-result-now" -> admissionHost(false, true, "none", true);
            case "cached-queue-now" -> admissionHost(true, false, "none", true);
            case "cached-result-now" -> admissionHost(true, true, "none", true);
            default -> throw new IllegalArgumentException("mode");
        }
        System.out.println("MANAGED_FIRST_ADMISSION_ACTIVATION PASS " + args[0]);
    }
}
