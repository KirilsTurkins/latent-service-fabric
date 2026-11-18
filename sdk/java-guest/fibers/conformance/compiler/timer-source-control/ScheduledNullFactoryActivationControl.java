import dev.latent.generated.Bindings;
import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.Option;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.AbstractExecutorService;
import dev.latent.guest.runtime.concurrent.CompletableFuture;
import dev.latent.guest.runtime.concurrent.Executors;
import dev.latent.guest.runtime.concurrent.ScheduledThreadPoolExecutor;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.util.Map;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executor;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Future;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.RunnableFuture;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Actual Activation and scheduled pool with a private host stand-in, not a guest. */
public final class ScheduledNullFactoryActivationControl {
    private static void require(boolean value, String detail) { if (!value) throw new AssertionError(detail); }
    private static Field field(String name) throws Exception {
        Field field = Activation.class.getDeclaredField(name); field.setAccessible(true); return field;
    }
    private static Object invoke(String name) throws Exception {
        var method = Activation.class.getDeclaredMethod(name); method.setAccessible(true); return method.invoke(null);
    }
    @SuppressWarnings("unchecked")
    private static Object enter() throws Exception {
        field("entered").setBoolean(null, true);
        var token = Bindings.LatentRuntimeActivation.register(LatentRuntimeActivationOwnerKind.Task, Option.none()).value();
        var type = Class.forName("dev.latent.guest.runtime.Activation$Work");
        var constructor = type.getDeclaredConstructor(Bindings.LatentRuntimeActivationToken.class);
        constructor.setAccessible(true);
        Object root = constructor.newInstance(token);
        field("root").set(null, root);
        ((Map<Thread, Object>)field("threads").get(null)).put(Thread.currentThread(), root);
        return root;
    }
    private static int owners(LatentRuntimeActivationOwnerKind kind) {
        return Bindings.LatentRuntimeActivation.owners(kind);
    }
    private static void held(int queue, int result, int executor) {
        require(owners(LatentRuntimeActivationOwnerKind.Task) == 1
            && owners(LatentRuntimeActivationOwnerKind.QueuedWork) == queue
            && owners(LatentRuntimeActivationOwnerKind.Result) == result
            && owners(LatentRuntimeActivationOwnerKind.Executor) == executor, "original-owner-custody");
    }
    private static void closeRoot() throws Exception {
        field("rootComplete").setBoolean(null, true);
        invoke("closeCompletedRoot");
        require(field("closing").getBoolean(null), "root-did-not-close");
    }
    private static void finishRoot(Object root) throws Exception {
        require(!(boolean)invoke("pending"), "root-still-pending");
        field("finishingInvocation").setBoolean(null, true);
        var finish = Activation.class.getDeclaredMethod("finishWork", Thread.class, root.getClass(), boolean.class);
        finish.setAccessible(true); finish.invoke(null, null, root, true);
        require(owners(LatentRuntimeActivationOwnerKind.Task) == 0, "root-owner-not-settled");
        invoke("finishInvocation");
    }
    private static void noWorker(String mode) throws Exception {
        Object root = enter();
        var failure = new IllegalStateException("factory-failed");
        var pool = new ScheduledThreadPoolExecutor(1, target -> {
            if (mode.equals("factory-throw")) throw failure;
            return null;
        });
        ScheduledFuture<?> future = null;
        try { future = pool.schedule(() -> { throw new AssertionError("no-worker-task-ran"); }, 0, TimeUnit.NANOSECONDS); }
        catch (IllegalStateException error) { require(mode.equals("factory-throw") && error == failure, "wrong-factory-failure"); }
        require((mode.equals("factory-throw") ? future == null : future != null && !future.isDone())
            && pool.hasPendingWork(), "accepted-work-not-pending");
        held(1, 1, 1);
        closeRoot();
        require((boolean)invoke("pending") && !(boolean)invoke("retireIdlePools") && !pool.isRetired(),
                "root-did-not-fence-no-worker");
        if (mode.equals("wait-denied")) {
            Bindings.LatentRuntimeActivation.denyRegistration = true;
            try { Activation.waitFor(-1); throw new AssertionError("wait-refusal-lost"); }
            catch (IllegalStateException expected) {
                require(expected.getMessage().contains("activation-runtime-wait-"), "wrong-wait-refusal");
            } finally { Bindings.LatentRuntimeActivation.denyRegistration = false; }
            held(1, 1, 1);
            require((boolean)invoke("pending") && !pool.isRetired(), "wait-refusal-lost-original-owners");
        } else {
            Activation.waitFor(-1);
            var token = root.getClass().getDeclaredField("token"); token.setAccessible(true);
            require(Bindings.LatentRuntimeActivation.lastWaitNanos == Long.MAX_VALUE
                && Bindings.LatentRuntimeActivation.lastWaitContinuation.isSome()
                && Bindings.LatentRuntimeActivation.lastWaitContinuation.value().equals(token.get(root))
                && owners(LatentRuntimeActivationOwnerKind.Timer) == 0, "root-wait-shape");
            held(1, 1, 1);
            require((boolean)invoke("pending"), "fake-wait-settled-original-work");
        }
        if (mode.equals("settle-result-denied") || mode.equals("settle-queue-denied")) {
            if (mode.equals("settle-result-denied")) Bindings.LatentRuntimeActivation.denySettle = true;
            else Bindings.LatentRuntimeActivation.settleObservation = () ->
                Bindings.LatentRuntimeActivation.settleObservation = () -> Bindings.LatentRuntimeActivation.denySettle = true;
            try { future.cancel(false); throw new AssertionError("settlement-refusal-lost"); }
            catch (IllegalStateException expected) { }
            held(1, mode.equals("settle-result-denied") ? 1 : 0, 1);
            require((boolean)invoke("pending") && !(boolean)invoke("retireIdlePools") && !pool.isRetired()
                && field("poisoned").getBoolean(null), "settlement-refusal-lost-fence");
            if (mode.equals("settle-result-denied")) {
                var owner = future.getClass().getSuperclass().getDeclaredField("owner"); owner.setAccessible(true);
                require(owner.get(future) != null, "refused-result-owner-not-retained");
            } else {
                require(((AtomicReference<?>)field("failedQueuedOwners").get(null)).get() != null,
                    "refused-queue-owner-not-retained");
            }
            try { invoke("requireHealthyCompletion"); throw new AssertionError("uncertain-root-completed"); }
            catch (InvocationTargetException expected) {
                require(expected.getCause() instanceof IllegalStateException, "wrong-completion-refusal");
            }
            return; // The deliberately uncertain owner is retained for Store teardown.
        }
        if (mode.equals("remove") || mode.equals("factory-throw")) {
            var removed = pool.shutdownNow();
            if (mode.equals("factory-throw")) {
                require(removed.size() == 1 && removed.get(0) instanceof ScheduledFuture<?>, "factory-throw-lost-future");
                future = (ScheduledFuture<?>)removed.get(0);
            }
            require(removed.contains(future) && !future.isDone(), "shutdown-now-lost-future");
            require(future.cancel(false), "removed-future-not-cancellable");
        } else require(future.cancel(false), "queued-future-not-cancellable");
        held(0, 0, mode.equals("remove") || mode.equals("factory-throw") ? 0 : 1);
        if (!pool.isRetired()) require((boolean)invoke("retireIdlePools"), "idle-pool-not-retired");
        else invoke("retireIdlePools"); // Clear the prior pending-pool retirement retry.
        require(!(boolean)invoke("pending"), "settled-work-remained-pending");
        held(0, 0, 0);
        require(pool.isRetired(), "executor-owner-not-settled");
        finishRoot(root);
    }
    private static void recovery(boolean reentrant) throws Exception {
        Object root = enter();
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        AtomicReference<ScheduledThreadPoolExecutor> selected = new AtomicReference<>();
        AtomicReference<ScheduledFuture<?>> nested = new AtomicReference<>();
        AtomicReference<Thread> worker = new AtomicReference<>();
        var pool = new ScheduledThreadPoolExecutor(1, target -> {
            if (attempts.incrementAndGet() == 1) {
                if (reentrant) nested.set(selected.get().schedule(calls::incrementAndGet, 0, TimeUnit.NANOSECONDS));
                return null;
            }
            // A host JVM does not install the TeaVM Thread hooks itself.
            Thread thread = new Thread(() -> {
                try { Activation.starting(Thread.currentThread()); target.run(); }
                finally { Activation.finished(Thread.currentThread()); }
            });
            worker.set(thread); return thread;
        });
        selected.set(pool);
        var first = pool.schedule(calls::incrementAndGet, 0, TimeUnit.NANOSECONDS);
        held(reentrant ? 2 : 1, reentrant ? 2 : 1, 1);
        require(!first.isDone() && pool.hasPendingWork(), "null-factory-rejected-work");
        var second = pool.schedule(calls::incrementAndGet, 0, TimeUnit.NANOSECONDS);
        first.get(5, TimeUnit.SECONDS); second.get(5, TimeUnit.SECONDS);
        if (reentrant) nested.get().get(5, TimeUnit.SECONDS);
        require(attempts.get() == 2 && calls.get() == (reentrant ? 3 : 2), "later-worker-did-not-recover");
        pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS), "worker-pool-did-not-terminate");
        worker.get().join(5000);
        require(!worker.get().isAlive() && owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 0,
                "worker-owner-not-retired");
        held(0, 0, 0);
        closeRoot();
        require(!(boolean)invoke("pending"), "recovered-work-remained-pending");
        finishRoot(root);
    }
    private static final class ScanPool implements Activation.ManagedPool {
        Runnable onCheck;
        int checks;
        @Override public boolean hasPendingWork() {
            checks++;
            Runnable action = onCheck; onCheck = null;
            if (action != null) action.run();
            return false;
        }
        @Override public boolean isRetired() { return true; }
        @Override public void closeAtRoot() { Activation.unmanageRetired(this); }
    }
    private static void scanMutation(boolean retirement) throws Exception {
        Object root = enter();
        var earlier = new ScanPool();
        var mutator = new ScanPool();
        Activation.manage(earlier); Activation.manage(mutator);
        var later = new ScheduledThreadPoolExecutor(1, target -> null);
        var future = later.schedule(() -> { throw new AssertionError("no-worker-task-ran"); }, 0, TimeUnit.NANOSECONDS);
        held(1, 1, 1); closeRoot();
        mutator.onCheck = () -> Activation.unmanageRetired(earlier);
        if (retirement)
            require(!(boolean)invoke("retireIdlePools") && !field("retiringPools").getBoolean(null)
                && !later.isShutdown(), "mutation-advanced-pool-retirement");
        else require((boolean)invoke("pending"), "mutation-skipped-later-work");
        require(mutator.checks == 1 && later.hasPendingWork(), "mutation-not-exercised");
        held(1, 1, 1);
        require((boolean)invoke("pending"), "later-work-not-scanned-after-mutation");
        Activation.unmanageRetired(mutator);
        require(future.cancel(false), "mutation-control-work-not-cancelled");
        held(0, 0, 1);
        require((boolean)invoke("retireIdlePools") && later.isRetired(), "mutation-control-pool-not-retired");
        held(0, 0, 0); finishRoot(root);
    }
    private static final class IdleOwnedPool implements Activation.ManagedPool {
        Activation.Lease owner = Activation.owner(LatentRuntimeActivationOwnerKind.Executor);
        Runnable onCheck;
        int checks, closes;
        @Override public boolean hasPendingWork() {
            checks++;
            if (onCheck != null) onCheck.run();
            return false;
        }
        @Override public boolean isRetired() { return owner == null; }
        void retire() {
            if (owner != null) { owner.close(); owner = null; }
            Activation.unmanageRetired(this);
        }
        @Override public void closeAtRoot() { closes++; retire(); }
    }
    private static void idleScanMutation(boolean repeated) throws Exception {
        Object root = enter();
        var victims = new IdleOwnedPool[repeated ? 3 : 1];
        for (int i = 0; i < victims.length; i++) {
            victims[i] = new IdleOwnedPool(); Activation.manage(victims[i]);
        }
        var mutator = new IdleOwnedPool();
        var last = new IdleOwnedPool();
        Activation.manage(mutator); Activation.manage(last);
        mutator.onCheck = () -> {
            int index = mutator.checks - 1;
            if (index < victims.length) victims[index].retire();
        };
        held(0, 0, victims.length + 2); closeRoot();
        for (int i = 0; i < victims.length; i++) {
            require(!(boolean)invoke("retireIdlePools") && !(boolean)field("retiringPools").get(null),
                "unstable-retirement-was-started");
            require((boolean)invoke("pending") && mutator.checks == i + 1
                && field("poolRetirementUnstable").getBoolean(null)
                && field("poolRetirementRescan").getBoolean(null),
                "unstable-idle-scan-did-not-request-retry");
            held(0, 0, victims.length - i + 1);
        }
        require((boolean)invoke("retireIdlePools") && mutator.closes == 1 && last.closes == 1,
            "stable-idle-pools-were-not-retired");
        held(0, 0, 0); finishRoot(root);
    }
    private static void exhaustedScanRetry() throws Exception {
        enter();
        var mutator = new IdleOwnedPool();
        var last = new IdleOwnedPool();
        Activation.manage(mutator); Activation.manage(last);
        mutator.onCheck = () -> {
            try { require(!(boolean)invoke("retireIdlePools"), "nested-retirement-started"); }
            catch (Exception error) { throw new AssertionError(error); }
        };
        held(0, 0, 2); closeRoot();
        for (int i = 0; i < 2; i++) {
            require(!(boolean)invoke("retireIdlePools") && (boolean)invoke("pending")
                && field("poolRetirementUnstable").getBoolean(null)
                && field("poolRetirementRescan").getBoolean(null), "retry-did-not-stay-pending");
            held(0, 0, 2);
        }
        try { invoke("retireIdlePools"); throw new AssertionError("unbounded-unstable-scan"); }
        catch (InvocationTargetException expected) {
            require(expected.getCause() instanceof IllegalStateException
                && expected.getCause().getMessage().equals("activation-runtime-pool-scan-unstable"),
                "wrong-unstable-scan-refusal");
        }
        require(!(boolean)field("retiringPools").get(null) && field("poisoned").getBoolean(null)
            && (boolean)invoke("pending") && mutator.checks == 3, "exhausted-scan-lost-fence");
        held(0, 0, 2);
        try { invoke("requireHealthyCompletion"); throw new AssertionError("unstable-root-completed"); }
        catch (InvocationTargetException expected) {
            require(expected.getCause() instanceof IllegalStateException, "wrong-completion-refusal");
        }
        // The remaining owners stay charged until Store teardown.
    }
    private static void retryWithLiveWork() throws Exception {
        Object root = enter();
        var victim = new IdleOwnedPool();
        var mutator = new IdleOwnedPool();
        var last = new IdleOwnedPool();
        Activation.manage(victim); Activation.manage(mutator); Activation.manage(last);
        mutator.onCheck = () -> { mutator.onCheck = null; victim.retire(); };
        closeRoot();
        require(!(boolean)invoke("retireIdlePools") && field("poolRetirementRescan").getBoolean(null),
            "initial-scan-did-not-request-retry");
        Thread live = new Thread();
        Activation.starting(live);
        require(!(boolean)invoke("retireIdlePools") && !field("poolRetirementRescan").getBoolean(null)
            && (boolean)invoke("pending"), "live-work-caused-immediate-retry-loop");
        require(owners(LatentRuntimeActivationOwnerKind.Task) == 2
            && owners(LatentRuntimeActivationOwnerKind.Executor) == 2, "live-work-lost-owner");
        Activation.finished(live);
        require((boolean)invoke("retireIdlePools") && mutator.closes == 1 && last.closes == 1,
            "idle-retirement-did-not-resume");
        held(0, 0, 0); finishRoot(root);
    }
    private static void workerAdmissionDenied() throws Exception {
        Object root = enter();
        var pool = new ScheduledThreadPoolExecutor(1, target -> {
            Bindings.LatentRuntimeActivation.denyRegistration = true;
            return new Thread(target);
        });
        try {
            try { pool.schedule(() -> { throw new AssertionError("unadmitted-worker-ran"); }, 0, TimeUnit.NANOSECONDS);
                throw new AssertionError("worker-admission-was-not-denied"); }
            catch (IllegalStateException error) {
                require(error.getMessage().contains("activation-runtime-register-"), "wrong-worker-admission-refusal");
            }
        } finally { Bindings.LatentRuntimeActivation.denyRegistration = false; }
        held(0, 0, 1);
        require(!pool.hasPendingWork(), "worker-admission-refusal-kept-queue");
        closeRoot();
        require((boolean)invoke("retireIdlePools") && pool.isRetired(), "denied-worker-pool-not-retired");
        held(0, 0, 0); finishRoot(root);
    }
    private static void manualFactoryFailure(boolean denyWorker) throws Exception {
        Object root = enter();
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        var failure = new IllegalStateException("manual-factory-failed");
        var pool = new ScheduledThreadPoolExecutor(1, target -> {
            if (attempts.incrementAndGet() == 1) return null;
            if (denyWorker) {
                Bindings.LatentRuntimeActivation.denyRegistration = true;
                return new Thread(target);
            }
            throw failure;
        });
        var future = pool.scheduleAtFixedRate(calls::incrementAndGet, 1, 1, TimeUnit.DAYS);
        long before = future.getDelay(TimeUnit.HOURS);
        try {
            try { ((Runnable)future).run(); throw new AssertionError("manual-failure-missing"); }
            catch (IllegalStateException error) {
                require(denyWorker ? error.getMessage().contains("activation-runtime-register-") : error == failure,
                    "wrong-manual-failure");
            }
        } finally { Bindings.LatentRuntimeActivation.denyRegistration = false; }
        require(calls.get() == 1 && attempts.get() == 2 && !future.isDone() && pool.hasPendingWork(),
            "manual-work-not-retained");
        long after = future.getDelay(TimeUnit.HOURS);
        require(denyWorker ? after <= before + 1 : after >= before + 23, "wrong-manual-deadline");
        held(denyWorker ? 1 : 2, 1, 1);
        closeRoot();
        require((boolean)invoke("pending") && !(boolean)invoke("retireIdlePools") && !pool.isRetired(),
            "manual-root-not-fenced");
        Activation.waitFor(-1);
        held(denyWorker ? 1 : 2, 1, 1);
        var removed = pool.shutdownNow();
        require(removed.size() == (denyWorker ? 1 : 2), "manual-copy-count");
        for (Runnable entry : removed) require(entry == future, "manual-copy-identity");
        require(!future.isDone() && future.cancel(false), "manual-future-not-cancelled");
        held(0, 0, 0);
        invoke("retireIdlePools");
        finishRoot(root);
    }
    private static void managedFactoryRetirement(String mode) throws Exception {
        Object root = enter();
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        AtomicReference<List<Runnable>> removed = new AtomicReference<>();
        AtomicReference<Thread> worker = new AtomicReference<>();
        var failure = new IllegalStateException("managed-factory-after-shutdown");
        var pool = Executors.newFixedThreadPool(1, target -> {
            var current = selected.get(); removed.set(current.shutdownNow());
            require(removed.get().isEmpty(), "uncommitted-first-exposed"); held(1, 1, 1);
            try {
                closeRoot();
                require((boolean)invoke("pending") && !(boolean)invoke("retireIdlePools")
                    && ((Activation.ManagedPool)current).hasPendingWork()
                    && !((Activation.ManagedPool)current).isRetired(), "managed-start-not-fenced");
            } catch (Exception error) { throw new AssertionError(error); }
            if (mode.equals("throw")) throw failure;
            if (mode.equals("null")) return null;
            Thread thread = new Thread(target); worker.set(thread); return thread;
        });
        selected.set(pool);
        try { pool.submit(() -> { throw new AssertionError("rejected-managed-ran"); });
            throw new AssertionError("managed-factory-rejection-missing"); }
        catch (RuntimeException error) {
            require(mode.equals("throw") ? error == failure : error instanceof RejectedExecutionException,
                "wrong-managed-factory-failure");
        }
        require(pool.awaitTermination(5, TimeUnit.SECONDS), "managed-pool-not-retired");
        if (worker.get() != null)
            require(worker.get().getState() == Thread.State.NEW
                && owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 0, "rejected-worker-started");
        held(0, 0, 0); invoke("retireIdlePools"); finishRoot(root);
    }
    private static void managedNullRoot(String mode) throws Exception {
        Object root = enter();
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        var failure = new IllegalStateException("managed-fallback-factory-failed");
        var pool = Executors.newFixedThreadPool(1, target -> {
            int attempt = attempts.incrementAndGet();
            if (attempt == 1 || mode.equals("pending")) return null;
            if (mode.equals("fallback-throw")) throw failure;
            Bindings.LatentRuntimeActivation.denyRegistration = true;
            return new Thread(target);
        });
        Future<?> future = null;
        try {
            try { future = pool.submit(calls::incrementAndGet); }
            catch (IllegalStateException error) {
                require(mode.equals("fallback-throw") ? error == failure
                    : mode.equals("worker-denied") && error.getMessage().contains("activation-runtime-register-"),
                    "wrong-managed-null-failure");
            }
        } finally { Bindings.LatentRuntimeActivation.denyRegistration = false; }
        require(attempts.get() == 2 && calls.get() == 0, "managed-null-attempts");
        require(mode.equals("pending") ? future != null && !future.isDone() : future == null,
            "wrong-managed-null-result");
        held(1, 1, 1); closeRoot();
        require((boolean)invoke("pending") && !(boolean)invoke("retireIdlePools")
            && !((Activation.ManagedPool)pool).isRetired(), "managed-null-root-not-fenced");
        Activation.waitFor(-1);
        var rootToken = root.getClass().getDeclaredField("token"); rootToken.setAccessible(true);
        require(Bindings.LatentRuntimeActivation.lastWaitContinuation.isSome()
            && Bindings.LatentRuntimeActivation.lastWaitContinuation.value().equals(rootToken.get(root)),
            "managed-null-wait-lost-root");
        held(1, 1, 1);
        List<Runnable> removed = pool.shutdownNow();
        require(removed.size() == 1 && removed.get(0) instanceof Future<?>, "managed-null-withdrawal");
        if (future == null) future = (Future<?>)removed.get(0);
        require(removed.get(0) == future && !future.isDone() && future.cancel(false), "managed-null-cancel");
        require(pool.awaitTermination(5, TimeUnit.SECONDS), "managed-null-pool-not-retired"); held(0, 0, 0);
        invoke("retireIdlePools"); finishRoot(root);
    }
    private static void managedNullUncertainWorker() throws Exception {
        enter();
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        AtomicReference<Thread> selected = new AtomicReference<>();
        var failure = new IllegalStateException("worker-start-failed");
        var pool = Executors.newFixedThreadPool(1, target -> {
            if (attempts.incrementAndGet() == 1) return null;
            Thread thread = new Thread(target) {
                @Override public synchronized void start() {
                    Bindings.LatentRuntimeActivation.denySettle = true;
                    throw failure;
                }
            };
            selected.set(thread); return thread;
        });
        try {
            try { pool.submit(calls::incrementAndGet); throw new AssertionError("uncertain-start-was-accepted"); }
            catch (IllegalStateException error) {
                require(error.getCause() == failure && error.getMessage().contains("activation-runtime-start-rollback-"),
                    "wrong-uncertain-start-failure");
            }
        } finally { Bindings.LatentRuntimeActivation.denySettle = false; }
        require(attempts.get() == 2 && calls.get() == 0 && Activation.alive(selected.get())
            && owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 1, "uncertain-worker-not-owned");
        held(1, 1, 1); closeRoot();
        require((boolean)invoke("pending") && !(boolean)invoke("retireIdlePools"), "uncertain-root-not-fenced");
        int before = Bindings.LatentRuntimeActivation.settlementAttempts;
        List<Runnable> removed = pool.shutdownNow();
        require(removed.size() == 1 && removed.get(0) instanceof Future<?>, "uncertain-queue-withdrawal");
        var future = (Future<?>)removed.get(0);
        require(!future.isDone() && future.cancel(false), "uncertain-future-not-cancelled");
        held(0, 0, 1);
        require(owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 1 && Activation.alive(selected.get())
            && (boolean)invoke("pending") && !pool.isTerminated()
            && Bindings.LatentRuntimeActivation.settlementAttempts == before + 2, "uncertain-worker-refunded");
        pool.shutdownNow();
        require(Bindings.LatentRuntimeActivation.settlementAttempts == before + 2, "uncertain-worker-retried");
        // The original worker and executor remain owned until Store teardown.
    }
    private static void managedPreferredRoot() throws Exception {
        Object root = enter();
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        AtomicReference<Thread> selected = new AtomicReference<>();
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        var pool = Executors.newFixedThreadPool(1, target -> {
            if (attempts.incrementAndGet() <= 2) return null;
            Thread thread = new Thread(() -> {
                try { Activation.starting(Thread.currentThread()); target.run(); }
                finally { Activation.finished(Thread.currentThread()); }
            });
            selected.set(thread); return thread;
        });
        try {
            var older = pool.submit(() -> { throw new AssertionError("withdrawn-older-ran"); });
            held(1, 1, 1);
            var preferred = pool.submit(() -> {
                calls.incrementAndGet(); entered.countDown();
                while (true) try { release.await(); return; } catch (InterruptedException ignored) { }
            });
            require(entered.await(5, TimeUnit.SECONDS), "preferred-work-not-started");
            held(1, 2, 1);
            require(owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 1, "preferred-worker-not-owned");
            closeRoot();
            require((boolean)invoke("pending") && !(boolean)invoke("retireIdlePools"), "preferred-root-not-fenced");
            List<Runnable> removed = pool.shutdownNow();
            require(removed.size() == 1 && removed.get(0) == older && !older.isDone(), "older-not-withdrawn");
            held(0, 1, 1);
            require((boolean)invoke("pending") && owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 1,
                "running-preferred-owner-lost");
            release.countDown(); preferred.get(5, TimeUnit.SECONDS);
            require(pool.awaitTermination(5, TimeUnit.SECONDS), "preferred-pool-not-retired");
            selected.get().join(5000);
            require(!selected.get().isAlive() && owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 0
                && calls.get() == 1 && older.cancel(false), "preferred-work-not-retired");
            held(0, 0, 0); invoke("retireIdlePools"); finishRoot(root);
        } finally { release.countDown(); }
    }
    private static void managedNestedNullRoot() throws Exception {
        Object root = enter();
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        AtomicReference<Future<?>> first = new AtomicReference<>(), second = new AtomicReference<>();
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        var pool = Executors.newFixedThreadPool(1, target -> {
            if (attempts.incrementAndGet() == 1) {
                first.set(selected.get().submit(calls::incrementAndGet));
                second.set(selected.get().submit(calls::incrementAndGet));
            }
            return null;
        });
        selected.set(pool);
        var outer = pool.submit(calls::incrementAndGet);
        require(attempts.get() == 2 && calls.get() == 0, "nested-null-unexpected-callback");
        held(3, 3, 1); closeRoot();
        require((boolean)invoke("pending") && !(boolean)invoke("retireIdlePools"), "nested-null-root-not-fenced");
        List<Runnable> removed = pool.shutdownNow();
        require(removed.size() == 3 && removed.get(0) == first.get() && removed.get(1) == second.get()
            && removed.get(2) == outer && calls.get() == 0, "nested-null-queue-order");
        held(0, 0, 0);
        require(first.get().cancel(false) && second.get().cancel(false) && outer.cancel(false), "nested-null-cancel");
        invoke("retireIdlePools"); finishRoot(root);
    }
    private static void managedGracefulSoleRoot(String mode) throws Exception {
        Object root = enter();
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        AtomicReference<Thread> offered = new AtomicReference<>();
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        var pool = Executors.newFixedThreadPool(1, target -> {
            attempts.incrementAndGet(); selected.get().shutdown(); held(1, 1, 1);
            if (mode.equals("executor-denied")) {
                Bindings.LatentRuntimeActivation.settleObservation = () -> {
                    Bindings.LatentRuntimeActivation.settleObservation = () -> {
                        Bindings.LatentRuntimeActivation.settleObservation = () -> Bindings.LatentRuntimeActivation.denySettle = true;
                    };
                };
            }
            if (!mode.equals("thread")) return null;
            var thread = new Thread(target); offered.set(thread); return thread;
        });
        selected.set(pool);
        try { pool.submit(calls::incrementAndGet); throw new AssertionError("graceful-sole-accepted"); }
        catch (RejectedExecutionException expected) {
            require(expected.getMessage().equals("activation-executor-closed"), "wrong-graceful-rejection");
        }
        require(attempts.get() == 1 && calls.get() == 0
            && (offered.get() == null || offered.get().getState() == Thread.State.NEW), "graceful-worker-started");
        closeRoot();
        if (mode.equals("executor-denied")) {
            Bindings.LatentRuntimeActivation.denySettle = false;
            held(0, 0, 1);
            require(field("poisoned").getBoolean(null) && !pool.isTerminated(), "graceful-owner-not-fenced");
            int attemptsBefore = Bindings.LatentRuntimeActivation.settlementAttempts;
            pool.shutdownNow();
            require(Bindings.LatentRuntimeActivation.settlementAttempts == attemptsBefore, "graceful-owner-retried");
            try { invoke("requireHealthyCompletion"); throw new AssertionError("graceful-root-succeeded"); }
            catch (InvocationTargetException error) {
                require(error.getCause() instanceof IllegalStateException, "wrong-graceful-root-failure");
            }
            // The original Executor owner remains fenced until Store teardown.
        } else {
            held(0, 0, 0);
            require(pool.isTerminated() && !(boolean)invoke("pending"), "graceful-pool-not-retired");
            invoke("retireIdlePools"); finishRoot(root);
        }
    }
    private static void managedObtrudeRoot() throws Exception {
        Object root = enter();
        AtomicReference<Thread> selected = new AtomicReference<>();
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicInteger calls = new AtomicInteger();
        var pool = Executors.newFixedThreadPool(1, target -> {
            Thread thread = new Thread(() -> {
                try { Activation.starting(Thread.currentThread()); target.run(); }
                finally { Activation.finished(Thread.currentThread()); }
            });
            selected.set(thread); return thread;
        });
        var result = new CompletableFuture<Integer>();
        try {
            result.completeAsync(() -> {
                calls.incrementAndGet(); entered.countDown();
                while (true) try { release.await(); return 42; } catch (InterruptedException ignored) { }
            }, pool);
            require(entered.await(5, TimeUnit.SECONDS), "obtrude-producer-not-started");
            held(1, 1, 1);
            require(owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 1, "obtrude-worker-not-owned");
            result.obtrudeValue(7);
            require(result.join() == 7, "obtrude-result-not-visible"); held(1, 1, 1);
            pool.shutdown(); closeRoot();
            require((boolean)invoke("pending") && !(boolean)invoke("retireIdlePools"), "obtrude-root-not-fenced");
            release.countDown(); selected.get().join(5000);
            require(!selected.get().isAlive() && calls.get() == 1 && result.join() == 7
                && owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 0, "obtrude-producer-not-retired");
            held(0, 0, 0); invoke("retireIdlePools"); finishRoot(root);
        } finally { release.countDown(); }
    }
    private static void managedDefaultAsyncRoot() throws Exception {
        Object root = enter();
        AtomicReference<Thread> selected = new AtomicReference<>();
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicInteger calls = new AtomicInteger();
        var pool = Executors.newFixedThreadPool(1, target -> {
            Thread thread = new Thread(() -> {
                try { Activation.starting(Thread.currentThread()); target.run(); }
                finally { Activation.finished(Thread.currentThread()); }
            });
            selected.set(thread); return thread;
        });
        class Source extends CompletableFuture<Integer> {
            int defaults, overloads;
            @Override public Executor defaultExecutor() { defaults++; return pool; }
            @Override public CompletableFuture<Void> thenRunAsync(Runnable action, Executor executor) {
                overloads++; throw new AssertionError("unexpected-explicit-overload");
            }
        }
        var source = new Source(); source.complete(5);
        try {
            var child = source.thenRunAsync(() -> {
                calls.incrementAndGet(); entered.countDown();
                while (true) try { release.await(); return; } catch (InterruptedException ignored) { }
            });
            require(entered.await(5, TimeUnit.SECONDS) && source.defaults == 1 && source.overloads == 0,
                "default-async-not-dispatched");
            held(1, 1, 1);
            require(owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 1, "default-async-worker-not-owned");
            pool.shutdown(); closeRoot();
            require((boolean)invoke("pending") && !(boolean)invoke("retireIdlePools"), "default-async-root-not-fenced");
            release.countDown(); selected.get().join(5000);
            require(!selected.get().isAlive() && calls.get() == 1 && child.join() == null
                && owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 0, "default-async-not-retired");
            held(0, 0, 0); invoke("retireIdlePools"); finishRoot(root);
        } finally { release.countDown(); }
    }
    private static void managedInvokeAnyFactoryRoot(boolean wrapped) throws Exception {
        Object root = enter();
        var workers = new java.util.concurrent.CopyOnWriteArrayList<Thread>();
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicInteger interrupts = new AtomicInteger(), calls = new AtomicInteger();
        var pool = Executors.newFixedThreadPool(2, target -> {
            Thread thread = new Thread(() -> {
                try { Activation.starting(Thread.currentThread()); target.run(); }
                finally { Activation.finished(Thread.currentThread()); }
            });
            workers.add(thread); return thread;
        });
        class Factory extends AbstractExecutorService {
            @Override protected <T> RunnableFuture<T> newTaskFor(Callable<T> task) {
                RunnableFuture<T> inner = super.newTaskFor(task);
                if (!wrapped) return inner;
                return new RunnableFuture<>() {
                    @Override public void run() { inner.run(); }
                    @Override public boolean cancel(boolean interrupt) { return inner.cancel(interrupt); }
                    @Override public boolean isCancelled() { return inner.isCancelled(); }
                    @Override public boolean isDone() { return inner.isDone(); }
                    @Override public T get() throws InterruptedException, ExecutionException { return inner.get(); }
                    @Override public T get(long n, TimeUnit unit) throws InterruptedException, ExecutionException, TimeoutException {
                        return inner.get(n, unit);
                    }
                };
            }
            @Override public void execute(Runnable task) { pool.execute(task); }
            @Override public void shutdown() { pool.shutdown(); }
            @Override public List<Runnable> shutdownNow() { return pool.shutdownNow(); }
            @Override public boolean isShutdown() { return pool.isShutdown(); }
            @Override public boolean isTerminated() { return pool.isTerminated(); }
            @Override public boolean awaitTermination(long n, TimeUnit unit) throws InterruptedException {
                return pool.awaitTermination(n, unit);
            }
        }
        try {
            Callable<Integer> held = () -> {
                calls.incrementAndGet(); entered.countDown();
                while (true) try { release.await(); return 1; } catch (InterruptedException ignored) { interrupts.incrementAndGet(); }
            };
            Callable<Integer> winner = () -> {
                require(entered.await(5, TimeUnit.SECONDS), "invoke-any-loser-not-started"); return 42;
            };
            require(new Factory().invokeAny(List.of(held, winner)) == 42, "invoke-any-winner");
            long deadline = System.nanoTime() + 5_000_000_000L;
            while (owners(LatentRuntimeActivationOwnerKind.Result) != 2 || interrupts.get() == 0) {
                require(System.nanoTime() - deadline < 0, "invoke-any-original-owners-not-held"); Thread.sleep(1);
            }
            held(0, 2, 1); pool.shutdown(); closeRoot();
            require((boolean)invoke("pending") && !(boolean)invoke("retireIdlePools"), "invoke-any-root-not-fenced");
            release.countDown();
            for (Thread worker : workers) { worker.join(5000); require(!worker.isAlive(), "invoke-any-worker-not-retired"); }
            require(calls.get() == 1 && owners(LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 0,
                    "invoke-any-worker-ownership");
            held(0, 0, 0); invoke("retireIdlePools"); finishRoot(root);
        } finally { release.countDown(); }
    }
    private static void pendingInvokeAnyRoot(boolean scheduled) throws Exception {
        Object root = enter();
        ExecutorService pool = scheduled ? new ScheduledThreadPoolExecutor(1, target -> null)
                                         : Executors.newFixedThreadPool(1, target -> null);
        AtomicInteger calls = new AtomicInteger();
        Callable<Integer> task = () -> { calls.incrementAndGet(); return 42; };
        try {
            try { pool.invokeAny(List.of(task, task), 0, TimeUnit.NANOSECONDS); throw new AssertionError("invoke-any-not-timed-out"); }
            catch (TimeoutException expected) { }
            held(2, scheduled ? 4 : 2, 1);
            closeRoot();
            require((boolean)invoke("pending") && !(boolean)invoke("retireIdlePools"), "invoke-any-queued-root-not-fenced");
            require(pool.shutdownNow().size() == 2 && calls.get() == 0, "invoke-any-queued-withdrawal");
            held(0, 0, 0); invoke("retireIdlePools"); finishRoot(root);
        } finally { pool.shutdownNow(); }
    }
    public static void main(String[] args) throws Exception {
        String mode = args[0];
        if (mode.equals("scan-mutation") || mode.equals("retirement-scan-mutation"))
            scanMutation(mode.equals("retirement-scan-mutation"));
        else if (mode.equals("idle-scan-mutation") || mode.equals("repeated-idle-scan-mutation"))
            idleScanMutation(mode.equals("repeated-idle-scan-mutation"));
        else if (mode.equals("exhausted-scan-retry")) exhaustedScanRetry();
        else if (mode.equals("retry-with-live-work")) retryWithLiveWork();
        else if (mode.equals("worker-admission-denied")) workerAdmissionDenied();
        else if (mode.equals("manual-factory-throw") || mode.equals("manual-worker-admission-denied"))
            manualFactoryFailure(mode.equals("manual-worker-admission-denied"));
        else if (mode.equals("managed-factory-thread") || mode.equals("managed-factory-null")
                || mode.equals("managed-factory-throw"))
            managedFactoryRetirement(mode.substring("managed-factory-".length()));
        else if (mode.equals("managed-null-pending") || mode.equals("managed-null-fallback-throw")
                || mode.equals("managed-null-worker-denied"))
            managedNullRoot(mode.substring("managed-null-".length()));
        else if (mode.equals("managed-null-worker-uncertain")) managedNullUncertainWorker();
        else if (mode.equals("managed-preferred-root")) managedPreferredRoot();
        else if (mode.equals("managed-nested-null-root")) managedNestedNullRoot();
        else if (mode.equals("managed-graceful-null-root") || mode.equals("managed-graceful-thread-root")
                || mode.equals("managed-graceful-executor-denied-root"))
            managedGracefulSoleRoot(mode.substring("managed-graceful-".length(), mode.length() - "-root".length()));
        else if (mode.equals("managed-obtrude-root")) managedObtrudeRoot();
        else if (mode.equals("managed-default-async-root")) managedDefaultAsyncRoot();
        else if (mode.equals("managed-invoke-any-factory-root") || mode.equals("managed-invoke-any-default-root"))
            managedInvokeAnyFactoryRoot(mode.equals("managed-invoke-any-factory-root"));
        else if (mode.equals("managed-invoke-any-pending-root") || mode.equals("scheduled-invoke-any-pending-root"))
            pendingInvokeAnyRoot(mode.equals("scheduled-invoke-any-pending-root"));
        else if (mode.equals("recovery") || mode.equals("reentrant")) recovery(mode.equals("reentrant"));
        else if (mode.equals("cancel") || mode.equals("remove") || mode.equals("factory-throw") || mode.equals("wait-denied")
                || mode.equals("settle-result-denied") || mode.equals("settle-queue-denied")) noWorker(mode);
        else throw new IllegalArgumentException(mode);
        System.out.println("SCHEDULED_NULL_FACTORY_ACTIVATION PASS " + mode);
    }
}
