import dev.latent.generated.Bindings;
import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.Option;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.ScheduledThreadPoolExecutor;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.util.Map;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
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
    public static void main(String[] args) throws Exception {
        String mode = args[0];
        if (mode.equals("scan-mutation") || mode.equals("retirement-scan-mutation"))
            scanMutation(mode.equals("retirement-scan-mutation"));
        else if (mode.equals("idle-scan-mutation") || mode.equals("repeated-idle-scan-mutation"))
            idleScanMutation(mode.equals("repeated-idle-scan-mutation"));
        else if (mode.equals("exhausted-scan-retry")) exhaustedScanRetry();
        else if (mode.equals("retry-with-live-work")) retryWithLiveWork();
        else if (mode.equals("worker-admission-denied")) workerAdmissionDenied();
        else if (mode.equals("recovery") || mode.equals("reentrant")) recovery(mode.equals("reentrant"));
        else if (mode.equals("cancel") || mode.equals("remove") || mode.equals("factory-throw") || mode.equals("wait-denied")
                || mode.equals("settle-result-denied") || mode.equals("settle-queue-denied")) noWorker(mode);
        else throw new IllegalArgumentException(mode);
        System.out.println("SCHEDULED_NULL_FACTORY_ACTIVATION PASS " + mode);
    }
}
