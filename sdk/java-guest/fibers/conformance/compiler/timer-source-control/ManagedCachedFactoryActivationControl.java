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

/** Actual Activation and executor sources with private host bindings, not a guest. */
public final class ManagedCachedFactoryActivationControl {
    private static void require(boolean value, String reason) { if (!value) throw new AssertionError(reason); }
    private static void await(CountDownLatch latch, String reason) throws InterruptedException { require(latch.await(5, TimeUnit.SECONDS), reason); }
    private static Field field(String name) throws Exception { var f = Activation.class.getDeclaredField(name); f.setAccessible(true); return f; }
    private static Object invoke(String name) throws Exception { var m = Activation.class.getDeclaredMethod(name); m.setAccessible(true); return m.invoke(null); }
    @SuppressWarnings("unchecked") private static Object enter() throws Exception {
        field("entered").setBoolean(null, true);
        var token = Bindings.LatentRuntimeActivation.register(LatentRuntimeActivationOwnerKind.Task, Option.none()).value();
        var type = Class.forName("dev.latent.guest.runtime.Activation$Work");
        var constructor = type.getDeclaredConstructor(Bindings.LatentRuntimeActivationToken.class); constructor.setAccessible(true);
        Object root = constructor.newInstance(token); field("root").set(null, root);
        ((Map<Thread, Object>)field("threads").get(null)).put(Thread.currentThread(), root);
        return root;
    }
    private static void held(int tasks, int queue, int result, int executor, int workers) {
        require(Bindings.LatentRuntimeActivation.owners(LatentRuntimeActivationOwnerKind.Task) == tasks
            && Bindings.LatentRuntimeActivation.owners(LatentRuntimeActivationOwnerKind.QueuedWork) == queue
            && Bindings.LatentRuntimeActivation.owners(LatentRuntimeActivationOwnerKind.Result) == result
            && Bindings.LatentRuntimeActivation.owners(LatentRuntimeActivationOwnerKind.Executor) == executor
            && Bindings.LatentRuntimeActivation.owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == workers,
            "original-owners");
    }
    private static void closeRoot() throws Exception { field("rootComplete").setBoolean(null, true); invoke("closeCompletedRoot"); }
    private static void finish(Object root) throws Exception {
        require(!(boolean)invoke("pending"), "root-still-pending"); field("finishingInvocation").setBoolean(null, true);
        var finish = Activation.class.getDeclaredMethod("finishWork", Thread.class, root.getClass(), boolean.class);
        finish.setAccessible(true); finish.invoke(null, null, root, true); held(0, 0, 0, 0, 0); invoke("finishInvocation");
    }
    private static Thread managed(Runnable target) {
        return new Thread(() -> {
            try { Activation.starting(Thread.currentThread()); target.run(); }
            finally { Activation.finished(Thread.currentThread()); }
        });
    }
    private static void nested(String mode) throws Exception {
        Object root = enter();
        var entered = new CountDownLatch(1); var releaseFactory = new CountDownLatch(1);
        var nestedEntered = new CountDownLatch(1); var releaseNested = new CountDownLatch(1);
        var attempts = new AtomicInteger(); var outerCalls = new AtomicInteger(); var nestedCalls = new AtomicInteger();
        var failure = new AtomicReference<Throwable>(); var outer = new AtomicReference<Future<?>>();
        var nestedWorker = new AtomicReference<Thread>(); var marker = new IllegalStateException("factory-failure");
        var pool = Executors.newCachedThreadPool(target -> {
            if (attempts.incrementAndGet() == 1) {
                entered.countDown();
                try { await(releaseFactory, "factory-release"); } catch (InterruptedException error) { throw new AssertionError(error); }
                if (mode.equals("null")) return null;
                if (mode.equals("throw")) throw marker;
                return managed(target);
            }
            var worker = managed(target); nestedWorker.set(worker); return worker;
        });
        Thread caller = new Thread(() -> {
            try { outer.set(pool.submit(outerCalls::incrementAndGet)); }
            catch (Throwable error) { failure.set(error); if (mode.equals("denied")) Bindings.LatentRuntimeActivation.denySettle = false; }
            finally { Activation.finished(Thread.currentThread()); }
        });
        Activation.starting(caller);
        try {
            caller.start(); await(entered, "factory-not-entered"); held(2, 1, 1, 1, 0);
            Future<?> nested = pool.submit(() -> {
                nestedCalls.incrementAndGet(); nestedEntered.countDown();
                while (true) try { releaseNested.await(); return; } catch (InterruptedException ignored) { }
            });
            await(nestedEntered, "nested-not-running"); held(2, 1, 2, 1, 1);
            closeRoot();
            require(((Activation.ManagedPool)pool).hasPendingWork() && (int)invoke("scanPendingPools") == 1
                && (boolean)invoke("pending") && !(boolean)invoke("retireIdlePools"), "root-not-fenced");
            if (mode.equals("graceful")) pool.shutdown();
            if (mode.equals("immediate") || mode.equals("denied")) require(pool.shutdownNow().isEmpty(), "first-exposed");
            if (mode.equals("denied")) Bindings.LatentRuntimeActivation.denySettle = true;
            releaseFactory.countDown(); caller.join(5000); Bindings.LatentRuntimeActivation.denySettle = false;
            require(!caller.isAlive() && outer.get() == null
                && (mode.equals("throw") ? failure.get() == marker : failure.get() instanceof RejectedExecutionException),
                "outer-error-lost");
            if (mode.equals("denied")) {
                held(1, 1, 2, 1, 1);
                require(field("poisoned").getBoolean(null) && !pool.isTerminated()
                    && ((Activation.ManagedPool)pool).hasPendingWork(), "denied-first-not-rooted");
                releaseNested.countDown(); nested.get(5, TimeUnit.SECONDS); nestedWorker.get().join(5000);
                require(!nestedWorker.get().isAlive(), "nested-worker-not-retired"); held(1, 1, 1, 1, 0);
                int attemptsBefore = Bindings.LatentRuntimeActivation.settlementAttempts;
                pool.shutdownNow(); require(Bindings.LatentRuntimeActivation.settlementAttempts == attemptsBefore, "denied-first-retried");
                require((boolean)invoke("pending") && !(boolean)invoke("retireIdlePools"), "denied-root-not-fenced");
                invoke("finishInvocation"); require(field("root").get(null) == root, "denied-root-lost"); return;
            }
            held(1, 0, 1, 1, 1); require(!nested.isDone() && outerCalls.get() == 0 && nestedCalls.get() == 1, "nested-lost");
            pool.shutdown(); releaseNested.countDown(); nested.get(5, TimeUnit.SECONDS); nestedWorker.get().join(5000);
            require(!nestedWorker.get().isAlive() && pool.awaitTermination(5, TimeUnit.SECONDS), "nested-not-retired");
            held(1, 0, 0, 0, 0); invoke("retireIdlePools"); finish(root);
        } finally {
            Bindings.LatentRuntimeActivation.denySettle = false;
            releaseFactory.countDown(); releaseNested.countDown(); caller.join(5000); pool.shutdownNow();
        }
    }
    private static void registrationUnknown() throws Exception {
        Object root = enter(); var marker = new IllegalStateException("worker-registration-unknown");
        var target = new AtomicReference<Runnable>();
        var pool = Executors.newCachedThreadPool(command -> {
            target.set(command); Bindings.LatentRuntimeActivation.registrationFailure = marker; return managed(command);
        });
        try {
            try { pool.submit(() -> { throw new AssertionError("unregistered-work-ran"); }); throw new AssertionError("unknown-registration-accepted"); }
            catch (IllegalStateException error) { require(error == marker, "unknown-error-lost"); }
        } finally { Bindings.LatentRuntimeActivation.registrationFailure = null; }
        held(1, 0, 0, 1, 1); require(field("poisoned").getBoolean(null) && ((Activation.ManagedPool)pool).hasPendingWork(),
            "unknown-registration-not-fenced");
        var reserved = pool.getClass().getDeclaredField("reservedFirsts"); reserved.setAccessible(true);
        require(reserved.get(pool) != null && pool.shutdownNow().isEmpty() && !pool.isTerminated(), "unknown-first-lost");
        closeRoot(); require((boolean)invoke("pending") && !(boolean)invoke("retireIdlePools"), "unknown-root-not-fenced");
        invoke("finishInvocation"); require(field("root").get(null) == root, "unknown-root-lost");
    }
    private static void registrationDenied() throws Exception {
        Object root = enter();
        var pool = Executors.newCachedThreadPool(command -> { Bindings.LatentRuntimeActivation.denyRegistration = true; return managed(command); });
        try {
            try { pool.submit(() -> { throw new AssertionError("denied-work-ran"); }); throw new AssertionError("denied-worker-accepted"); }
            catch (IllegalStateException error) { require(error.getMessage().contains("activation-runtime-register-"), "wrong-registration-refusal"); }
        } finally { Bindings.LatentRuntimeActivation.denyRegistration = false; }
        held(1, 0, 0, 1, 0); require(!((Activation.ManagedPool)pool).hasPendingWork(), "denied-work-retained");
        pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS), "denied-pool-not-retired");
        held(1, 0, 0, 0, 0); closeRoot(); invoke("retireIdlePools"); finish(root);
    }
    private static void registrationHandoff() throws Exception {
        Object root = enter(); var entered = new CountDownLatch(1); var release = new CountDownLatch(1);
        class DeferredInterruptThread extends Thread {
            volatile boolean requested;
            DeferredInterruptThread(Runnable target) { super(target); }
            @Override public void interrupt() { requested = true; }
            void deliver() { super.interrupt(); }
        }
        var worker = new AtomicReference<DeferredInterruptThread>(); var failure = new AtomicReference<Throwable>();
        var result = new AtomicReference<Future<?>>(); var observation = new AtomicReference<Boolean>();
        var observationFailure = new AtomicReference<Throwable>(); var calls = new AtomicInteger();
        var pool = Executors.newCachedThreadPool(target -> {
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
            caller.start(); await(entered, "factory-not-entered"); held(2, 1, 1, 1, 0); closeRoot();
            Bindings.LatentRuntimeActivation.registrationObservation = () -> {
                try {
                    var entering = pool.getClass().getDeclaredField("enteringWorkers"); entering.setAccessible(true);
                    var starting = pool.getClass().getDeclaredField("startingWorkers"); starting.setAccessible(true);
                    observation.set(entering.getInt(pool) == 1 && starting.getInt(pool) == 0
                        && ((Activation.ManagedPool)pool).hasPendingWork() && (int)invoke("scanPendingPools") == 1
                        && (boolean)invoke("pending") && !(boolean)invoke("retireIdlePools"));
                } catch (Throwable error) { observationFailure.set(error); }
            };
            release.countDown(); caller.join(5000);
            require(!caller.isAlive() && failure.get() == null && result.get() != null && observationFailure.get() == null
                && Boolean.TRUE.equals(observation.get()), "registration-handoff-not-fenced");
            require(result.get().get(5, TimeUnit.SECONDS).equals(1) && calls.get() == 1, "first-not-run");
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
            while (((Activation.ManagedPool)pool).hasPendingWork()) {
                require(System.nanoTime() - deadline < 0, "pool-did-not-become-idle"); Thread.yield();
            }
            invoke("retireIdlePools"); require(worker.get().requested, "worker-interrupt-not-requested");
            worker.get().deliver(); worker.get().join(5000);
            require(!worker.get().isAlive() && ((Activation.ManagedPool)pool).isRetired(), "worker-not-retired");
            held(1, 0, 0, 0, 0); finish(root);
        } finally { release.countDown(); caller.join(5000); pool.shutdown(); }
    }
    private static void uncertainStart() throws Exception {
        Object root = enter(); var selected = new AtomicReference<Thread>(); var marker = new IllegalStateException("start-failure");
        var pool = Executors.newCachedThreadPool(target -> {
            Thread thread = new Thread(target) {
                @Override public synchronized void start() { Bindings.LatentRuntimeActivation.denySettle = true; throw marker; }
            };
            selected.set(thread); return thread;
        });
        try {
            try { pool.submit(() -> { throw new AssertionError("uncertain-work-ran"); }); throw new AssertionError("uncertain-start-accepted"); }
            catch (IllegalStateException error) {
                require(error.getCause() == marker && error.getMessage().contains("activation-runtime-start-rollback-"), "uncertain-error-lost");
            }
        } finally { Bindings.LatentRuntimeActivation.denySettle = false; }
        held(1, 1, 1, 1, 1); require(Activation.ownsManaged(selected.get(), (Activation.ManagedPool)pool)
            && pool.shutdownNow().isEmpty() && ((Activation.ManagedPool)pool).hasPendingWork(), "uncertain-work-lost");
        closeRoot(); require((boolean)invoke("pending") && !(boolean)invoke("retireIdlePools"), "uncertain-root-not-fenced");
        int attempts = Bindings.LatentRuntimeActivation.settlementAttempts;
        pool.shutdownNow(); require(Bindings.LatentRuntimeActivation.settlementAttempts == attempts, "uncertain-work-retried");
        invoke("finishInvocation"); require(field("root").get(null) == root, "uncertain-root-lost");
    }
    public static void main(String[] args) throws Exception {
        switch (args[0]) {
            case "graceful", "immediate", "denied", "null", "throw" -> nested(args[0]);
            case "registration-denied" -> registrationDenied();
            case "registration-unknown" -> registrationUnknown();
            case "registration-handoff" -> registrationHandoff();
            case "uncertain-start" -> uncertainStart();
            default -> throw new IllegalArgumentException("mode");
        }
        System.out.println("MANAGED_CACHED_FACTORY_ACTIVATION PASS " + args[0]);
    }
}
