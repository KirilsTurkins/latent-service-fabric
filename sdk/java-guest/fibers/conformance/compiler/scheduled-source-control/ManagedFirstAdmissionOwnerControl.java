import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.Executors;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Future;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Source-only first-task and private faulting-ledger controls. */
public final class ManagedFirstAdmissionOwnerControl {
    private static void require(boolean value, String message) { if (!value) throw new AssertionError(message); }
    private static void await(CountDownLatch latch, String message) throws InterruptedException {
        require(latch.await(5, TimeUnit.SECONDS), message);
    }
    private static void held(int queued, int result, int executor) {
        require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == queued
            && Activation.count(LatentRuntimeActivationOwnerKind.Result) == result
            && Activation.count(LatentRuntimeActivationOwnerKind.Executor) == executor, "owners");
    }
    private static Object worker(Runnable target) throws Exception {
        var field = target.getClass().getDeclaredFields()[0]; field.setAccessible(true); return field.get(target);
    }
    private static void inert(Runnable target) throws Exception {
        Object worker = worker(target);
        var pool = worker.getClass().getDeclaredField("pool"); pool.setAccessible(true);
        require(pool.get(worker) == null, "retained-worker-pool");
        for (var field : worker.getClass().getDeclaredFields()) {
            if (!field.getType().isPrimitive()) {
                field.setAccessible(true); require(field.get(worker) == null, "retained-worker-reference");
            }
        }
        target.run();
    }
    private static void beforeCommit(String mode) throws Exception {
        var entered = new CountDownLatch(1); var release = new CountDownLatch(1);
        var target = new AtomicReference<Runnable>(); var failure = new AtomicReference<Throwable>();
        var outer = new AtomicReference<Future<?>>(); var calls = new AtomicInteger();
        var pool = Executors.newFixedThreadPool(1, runnable -> {
            target.set(runnable); entered.countDown();
            try { await(release, "factory-release"); } catch (InterruptedException e) { throw new AssertionError(e); }
            return new Thread(runnable);
        });
        Thread caller = new Thread(() -> {
            try { outer.set(pool.submit(calls::incrementAndGet)); } catch (Throwable error) { failure.set(error); }
        });
        try {
            caller.start(); await(entered, "factory-not-entered"); held(1, 1, 1);
            var nested = pool.submit(calls::incrementAndGet); held(2, 2, 1);
            if (mode.equals("graceful")) pool.shutdown();
            else {
                List<Runnable> removed = pool.shutdownNow();
                require(removed.size() == 1 && removed.get(0) == nested, "reserved-first-exposed");
                held(1, 1, 1);
            }
            require(((Activation.ManagedPool)pool).hasPendingWork() && !pool.isTerminated(), "startup-not-fenced");
            if (mode.equals("denied")) Activation.denyCloseNext = "QueuedWork";
            if (mode.equals("lost")) Activation.loseCloseAckNext = "QueuedWork";
            release.countDown(); caller.join(5000);
            require(!caller.isAlive() && failure.get() instanceof RejectedExecutionException && outer.get() == null,
                "original-rejection");
            inert(target.get());
            if (mode.equals("graceful")) {
                held(1, 1, 1); require(((Activation.ManagedPool)pool).hasPendingWork(), "nested-not-fenced");
                var removed = pool.shutdownNow(); require(removed.size() == 1 && removed.get(0) == nested, "nested-withdrawal");
            } else if (mode.equals("denied") || mode.equals("lost")) {
                held(mode.equals("denied") ? 1 : 0, 1, 1);
                require(Activation.poisoned && Activation.retainsFailedQueued()
                    && Activation.failedLeaseAttempts() == 1 && !pool.isTerminated(), "failed-owner-not-retained");
                pool.shutdownNow(); require(Activation.failedLeaseAttempts() == 1, "settlement-retried");
                require(nested.cancel(false), "nested-cancel");
                return;
            }
            require(pool.awaitTermination(5, TimeUnit.SECONDS) && calls.get() == 0 && !nested.isDone(), "retirement");
            held(0, 0, 0); require(nested.cancel(false), "nested-cancel"); Activation.idle();
        } finally { release.countDown(); caller.join(5000); pool.shutdownNow(); }
    }
    private static void committed() throws Exception {
        var entered = new CountDownLatch(1); var release = new CountDownLatch(1);
        var target = new AtomicReference<Runnable>(); var calls = new AtomicInteger();
        var pool = Executors.newFixedThreadPool(1, runnable -> {
            target.set(runnable);
            return new Thread(() -> {
                entered.countDown();
                while (true) try { release.await(); break; } catch (InterruptedException ignored) { }
                runnable.run();
            });
        });
        try {
            Future<Integer> first = pool.submit(calls::incrementAndGet); await(entered, "worker-not-held");
            require(pool.shutdownNow().isEmpty() && !first.isDone() && !pool.isTerminated(), "committed-first-exposed");
            held(1, 1, 1); require(((Activation.ManagedPool)pool).hasPendingWork(), "committed-not-fenced");
            release.countDown(); require(first.get(5, TimeUnit.SECONDS) == 1, "committed-first-not-run");
            require(pool.awaitTermination(5, TimeUnit.SECONDS) && calls.get() == 1, "committed-not-retired");
            held(0, 0, 0); inert(target.get()); Activation.idle();
        } finally { release.countDown(); pool.shutdownNow(); }
    }
    private static void nullOrThrow(boolean throwsFailure) throws Exception {
        var entered = new CountDownLatch(1); var release = new CountDownLatch(1);
        var firstTarget = new AtomicReference<Runnable>(); var attempts = new AtomicInteger();
        var calls = new StringBuffer(); var marker = new IllegalStateException("factory-failure");
        var failure = new AtomicReference<Throwable>(); var outer = new AtomicReference<Future<?>>();
        var pool = Executors.newFixedThreadPool(1, target -> {
            if (attempts.incrementAndGet() == 1) {
                firstTarget.set(target); entered.countDown();
                try { await(release, "factory-release"); } catch (InterruptedException e) { throw new AssertionError(e); }
                if (throwsFailure) throw marker;
                return null;
            }
            return new Thread(target);
        });
        int before = Activation.admissions(LatentRuntimeActivationOwnerKind.QueuedWork);
        Thread caller = new Thread(() -> {
            try { outer.set(pool.submit(() -> calls.append('A'))); } catch (Throwable error) { failure.set(error); }
        });
        try {
            caller.start(); await(entered, "factory-not-entered");
            Future<?> nested = pool.submit(() -> calls.append('B')); held(2, 2, 1);
            require(Activation.admissions(LatentRuntimeActivationOwnerKind.QueuedWork) == before + 2, "unexpected-readmission");
            release.countDown(); caller.join(5000); require(!caller.isAlive(), "caller-stuck");
            inert(firstTarget.get());
            if (throwsFailure) {
                require(failure.get() == marker && outer.get() == null, "factory-failure-lost"); held(1, 1, 1);
                pool.submit(() -> calls.append('C')).get(5, TimeUnit.SECONDS); nested.get(5, TimeUnit.SECONDS);
                require(calls.toString().equals("CB"), "throw-recovery-order");
            } else {
                require(failure.get() == null && outer.get() != null, "null-factory-rejected");
                nested.get(5, TimeUnit.SECONDS); outer.get().get(5, TimeUnit.SECONDS);
                require(calls.toString().equals("BA"), "null-fallback-order");
            }
            require(attempts.get() == 2, "factory-count");
            pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS), "retirement");
            held(0, 0, 0); Activation.idle();
        } finally { release.countDown(); caller.join(5000); pool.shutdownNow(); }
    }
    private static void startFailure(boolean uncertain) throws Exception {
        var starts = new AtomicInteger(); var target = new AtomicReference<Runnable>();
        var selected = new AtomicReference<Thread>(); var calls = new AtomicInteger();
        var marker = new IllegalStateException("start-failure");
        var pool = Executors.newFixedThreadPool(1, runnable -> {
            target.set(runnable);
            Thread thread = new Thread(runnable) {
                @Override public synchronized void start() {
                    if (starts.incrementAndGet() == 1) throw marker;
                    super.start();
                }
            };
            selected.set(thread); return thread;
        });
        Activation.retainFailedStart = uncertain;
        try {
            try { pool.submit(calls::incrementAndGet); throw new AssertionError("missing-start-failure"); }
            catch (IllegalStateException error) { require(error == marker, "start-failure-lost"); }
            if (uncertain) {
                held(1, 1, 1);
                require(Activation.ownsManaged(selected.get(), (Activation.ManagedPool)pool)
                    && ((Activation.ManagedPool)pool).hasPendingWork(), "uncertain-start-not-fenced");
                require(pool.shutdownNow().isEmpty() && !pool.isTerminated(), "uncertain-first-exposed");
                selected.get().start(); selected.get().join(5000);
                require(!selected.get().isAlive() && calls.get() == 1 && pool.awaitTermination(5, TimeUnit.SECONDS),
                    "uncertain-first-not-settled");
            } else {
                held(0, 0, 1); inert(target.get());
                require(pool.shutdownNow().isEmpty() && pool.awaitTermination(5, TimeUnit.SECONDS), "definite-start-retirement");
                require(calls.get() == 0, "rejected-first-ran");
            }
            held(0, 0, 0); inert(target.get()); Activation.idle();
        } finally { Activation.retainFailedStart = false; pool.shutdownNow(); }
    }
    private static void transfer(String mode, boolean cached) throws Exception {
        var selected = new AtomicReference<ExecutorService>();
        var target = new AtomicReference<Runnable>();
        var removed = new AtomicReference<List<Runnable>>();
        var marker = new IllegalStateException("insertion-failure");
        var calls = new AtomicInteger();
        class FaultDeque extends java.util.ArrayDeque<Object> {
            @Override public void addLast(Object item) {
                if (!mode.equals("transfer-before")) super.addLast(item);
                if (mode.startsWith("transfer-withdraw")) {
                    if (mode.endsWith("denied") || mode.endsWith("swallow")) Activation.denyCloseNext = "QueuedWork";
                    if (mode.endsWith("lost")) Activation.loseCloseAckNext = "QueuedWork";
                    try { removed.set(selected.get().shutdownNow()); }
                    catch (IllegalStateException error) {
                        require(mode.endsWith("denied") || mode.endsWith("lost") || mode.endsWith("swallow"),
                            "unexpected-withdrawal-failure");
                        if (mode.endsWith("swallow")) return;
                    }
                }
                throw marker;
            }
        }
        java.util.concurrent.ThreadFactory factory = runnable -> { target.set(runnable); return null; };
        var pool = cached ? Executors.newCachedThreadPool(factory) : Executors.newFixedThreadPool(1, factory);
        selected.set(pool);
        var queue = pool.getClass().getDeclaredField("queue"); queue.setAccessible(true); queue.set(pool, new FaultDeque());
        var reserved = pool.getClass().getDeclaredField("reservedFirsts"); reserved.setAccessible(true);
        var future = new dev.latent.guest.runtime.concurrent.FutureTask<>(calls::incrementAndGet, null);
        try {
            try { pool.execute(future); throw new AssertionError("missing-transfer-failure"); }
            catch (IllegalStateException error) {
                if (mode.endsWith("swallow")) require(error.getMessage().equals("activation-executor-transfer-uncertain"), "uncertainty-not-reported");
                else require(error == marker, "insertion-failure-lost");
            }
            if (target.get() != null) inert(target.get());
            else require(cached, "missing-fixed-factory-target");
            boolean uncertain = mode.equals("transfer-before") || mode.endsWith("denied")
                || mode.endsWith("lost") || mode.endsWith("swallow");
            if (uncertain) {
                held(mode.endsWith("lost") ? 0 : 1, 1, 1);
                require(reserved.get(pool) != null && Activation.poisoned
                    && ((Activation.ManagedPool)pool).hasPendingWork(), "uncertain-item-not-rooted");
                int attempts = Activation.closeAttempts(LatentRuntimeActivationOwnerKind.QueuedWork);
                pool.shutdownNow();
                require(reserved.get(pool) != null && !pool.isTerminated()
                    && Activation.closeAttempts(LatentRuntimeActivationOwnerKind.QueuedWork) == attempts,
                    "uncertain-settlement-retried");
            } else {
                require(reserved.get(pool) == null, "settled-reservation-retained");
                if (mode.equals("transfer-withdraw"))
                    require(removed.get().size() == 1 && removed.get().get(0) == future, "withdrawn-item-changed");
                held(0, 0, mode.equals("transfer-after") ? 1 : 0);
                pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS), "transfer-not-retired");
                held(0, 0, 0); require(future.cancel(false), "future-not-cancellable"); Activation.idle();
            }
            require(calls.get() == 0, "unadmitted-item-ran");
        } finally { pool.shutdownNow(); }
    }
    private static void claimedDuringTransfer() throws Exception {
        var selected = new AtomicReference<ExecutorService>();
        var secondTarget = new AtomicReference<Runnable>();
        var attempts = new AtomicInteger(); var calls = new AtomicInteger();
        var entered = new CountDownLatch(1); var release = new CountDownLatch(1);
        var marker = new IllegalStateException("insertion-failure-after-claim");
        class FaultDeque extends java.util.ArrayDeque<Object> {
            @Override public void addLast(Object item) {
                super.addLast(item); release.countDown();
                try {
                    long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
                    while (calls.get() == 0 && System.nanoTime() < deadline) selected.get().wait(50);
                } catch (InterruptedException error) { throw new AssertionError(error); }
                require(calls.get() == 1, "item-not-claimed");
                throw marker;
            }
        }
        var pool = Executors.newFixedThreadPool(2, runnable -> {
            if (attempts.incrementAndGet() == 1) return new Thread(runnable);
            secondTarget.set(runnable); return null;
        });
        selected.set(pool);
        var field = pool.getClass().getDeclaredField("queue"); field.setAccessible(true); field.set(pool, new FaultDeque());
        var future = new dev.latent.guest.runtime.concurrent.FutureTask<>(calls::incrementAndGet, null);
        try {
            var first = pool.submit(() -> {
                entered.countDown();
                try { await(release, "first-release"); } catch (InterruptedException error) { throw new AssertionError(error); }
            });
            await(entered, "first-not-running");
            try { pool.execute(future); throw new AssertionError("missing-insertion-failure"); }
            catch (IllegalStateException error) { require(error == marker, "original-insertion-failure-lost"); }
            first.get(5, TimeUnit.SECONDS); future.get(5, TimeUnit.SECONDS);
            inert(secondTarget.get());
            var reserved = pool.getClass().getDeclaredField("reservedFirsts"); reserved.setAccessible(true);
            require(reserved.get(pool) == null && calls.get() == 1 && !Activation.poisoned, "claimed-item-retained-or-replayed");
            pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS), "claim-not-retired");
            held(0, 0, 0); Activation.idle();
        } finally { release.countDown(); pool.shutdownNow(); }
    }
    private static void duplicateUnstartedWorker() throws Exception {
        var entered = new CountDownLatch(1); var release = new CountDownLatch(1);
        var firstTarget = new AtomicReference<Runnable>(); var duplicateTarget = new AtomicReference<Runnable>();
        var chosen = new AtomicReference<Thread>(); var firstResult = new AtomicReference<Future<?>>();
        var firstError = new AtomicReference<Throwable>(); var attempts = new AtomicInteger(); var calls = new AtomicInteger();
        var pool = Executors.newFixedThreadPool(2, runnable -> {
            if (attempts.incrementAndGet() == 1) {
                firstTarget.set(runnable);
                var thread = new Thread(runnable) {
                    @Override public synchronized void start() {
                        entered.countDown();
                        try { await(release, "start-release"); } catch (InterruptedException error) { throw new AssertionError(error); }
                        super.start();
                    }
                };
                chosen.set(thread); return thread;
            }
            duplicateTarget.set(runnable); return chosen.get();
        });
        var caller = new Thread(() -> {
            try { firstResult.set(pool.submit(calls::incrementAndGet)); } catch (Throwable error) { firstError.set(error); }
        });
        try {
            caller.start(); await(entered, "first-start-not-held");
            require(chosen.get().getState() == Thread.State.NEW, "first-already-started"); held(1, 1, 1);
            try { pool.submit(calls::incrementAndGet); throw new AssertionError("duplicate-thread-accepted"); }
            catch (IllegalThreadStateException expected) { }
            inert(duplicateTarget.get()); held(1, 1, 1);
            require(pool.shutdownNow().isEmpty() && ((Activation.ManagedPool)pool).hasPendingWork(), "first-owner-lost");
            release.countDown(); caller.join(5000);
            require(!caller.isAlive() && firstError.get() == null && firstResult.get() != null, "first-start-failed");
            firstResult.get().get(5, TimeUnit.SECONDS);
            require(pool.awaitTermination(5, TimeUnit.SECONDS) && calls.get() == 1, "first-not-settled-once");
            held(0, 0, 0); inert(firstTarget.get()); Activation.idle();
        } finally { release.countDown(); caller.join(5000); pool.shutdownNow(); }
    }
    private static void admissionShutdown(boolean cached, String kind, String fault, boolean immediate) throws Exception {
        var pool = cached ? Executors.newCachedThreadPool() : Executors.newFixedThreadPool(1);
        var earlyTermination = new java.util.concurrent.atomic.AtomicBoolean();
        var calls = new AtomicInteger();
        Activation.admissionObservationKind = kind;
        Activation.admissionObservation = () -> {
            if (immediate) require(pool.shutdownNow().isEmpty(), "unpublished-task-exposed");
            else pool.shutdown();
            earlyTermination.set(pool.isTerminated());
            if (fault.equals("denied")) Activation.denyCloseNext = "QueuedWork";
            if (fault.equals("lost")) Activation.loseCloseAckNext = "QueuedWork";
        };
        try {
            try { pool.submit(calls::incrementAndGet); throw new AssertionError("admitted-after-reentrant-shutdown"); }
            catch (RejectedExecutionException expected) { }
            require(!earlyTermination.get() && calls.get() == 0, "executor-retired-during-admission");
            if (fault.equals("none")) {
                require(pool.awaitTermination(5, TimeUnit.SECONDS), "admission-not-retired"); held(0, 0, 0); Activation.idle();
            } else {
                held(fault.equals("denied") ? 1 : 0, kind.equals("Result") ? 1 : 0, 1);
                require(!pool.isTerminated() && ((Activation.ManagedPool)pool).hasPendingWork()
                    && Activation.poisoned && Activation.retainsFailedQueued() && Activation.failedLeaseAttempts() == 1,
                    "uncertain-admission-not-fenced");
                pool.shutdownNow(); require(Activation.failedLeaseAttempts() == 1, "admission-settlement-retried");
            }
        } finally { pool.shutdownNow(); }
    }
    private static void admissionCapacity(boolean cached) throws Exception {
        var pool = cached ? Executors.newCachedThreadPool() : Executors.newFixedThreadPool(1);
        var count = pool.getClass().getDeclaredField("pendingWork"); count.setAccessible(true);
        int admissions = Activation.admissions(LatentRuntimeActivationOwnerKind.QueuedWork);
        try {
            count.setInt(pool, Integer.MAX_VALUE);
            try { pool.submit(() -> { throw new AssertionError("capacity-task-ran"); }); throw new AssertionError("capacity-accepted"); }
            catch (RejectedExecutionException expected) { require(expected.getMessage().equals("activation-executor-pending-capacity"), "wrong-capacity"); }
            require(count.getInt(pool) == Integer.MAX_VALUE
                && Activation.admissions(LatentRuntimeActivationOwnerKind.QueuedWork) == admissions, "capacity-overflow-or-admission");
            held(0, 0, 1);
        } finally { count.setInt(pool, 0); pool.shutdownNow(); }
        require(pool.awaitTermination(5, TimeUnit.SECONDS), "capacity-not-retired"); held(0, 0, 0); Activation.idle();
    }
    private static void admissionRefusal(boolean cached, String kind) throws Exception {
        var pool = cached ? Executors.newCachedThreadPool() : Executors.newFixedThreadPool(1);
        var count = pool.getClass().getDeclaredField("pendingWork"); count.setAccessible(true);
        Activation.denyNext = kind;
        try {
            try { pool.submit(() -> { throw new AssertionError("refused-task-ran"); }); throw new AssertionError("admission-accepted"); }
            catch (IllegalStateException expected) { require(expected.getMessage().equals("source-owner-admission-denied"), "wrong-admission-refusal"); }
            require(count.getInt(pool) == 0 && !Activation.poisoned, "definite-refusal-left-pending"); held(0, 0, 1);
        } finally { pool.shutdownNow(); }
        require(pool.awaitTermination(5, TimeUnit.SECONDS), "refusal-not-retired"); held(0, 0, 0); Activation.idle();
    }
    private static void admissionUnknown(boolean cached, String kind) throws Exception {
        var pool = cached ? Executors.newCachedThreadPool() : Executors.newFixedThreadPool(1);
        var marker = new IllegalStateException("admission-outcome-unknown");
        Activation.admissionObservationKind = kind;
        Activation.admissionObservation = () -> { pool.shutdown(); Activation.poisoned = true; throw marker; };
        try {
            try { pool.submit(() -> { throw new AssertionError("unknown-task-ran"); }); throw new AssertionError("unknown-admission-accepted"); }
            catch (IllegalStateException error) { require(error == marker, "unknown-admission-error-lost"); }
            held(kind.equals("QueuedWork") ? 1 : 0, kind.equals("Result") ? 1 : 0, 1);
            require(Activation.poisoned && !pool.isTerminated() && ((Activation.ManagedPool)pool).hasPendingWork(),
                "unknown-admission-lost-custody");
            if (kind.equals("Result")) {
                var reserved = pool.getClass().getDeclaredField("reservedFirsts"); reserved.setAccessible(true);
                require(reserved.get(pool) != null, "unknown-result-command-not-rooted");
            }
            pool.shutdownNow(); require(!pool.isTerminated(), "unknown-admission-retired");
        } finally { pool.shutdownNow(); }
    }
    private static void prePoisonedAdmission(boolean cached) throws Exception {
        var pool = cached ? Executors.newCachedThreadPool() : Executors.newFixedThreadPool(1);
        var count = pool.getClass().getDeclaredField("pendingWork"); count.setAccessible(true);
        int admissions = Activation.admissions(LatentRuntimeActivationOwnerKind.QueuedWork);
        Activation.poisoned = true;
        try {
            try { pool.submit(() -> { throw new AssertionError("poisoned-task-ran"); }); throw new AssertionError("poisoned-admission-accepted"); }
            catch (IllegalStateException error) { require(error.getMessage().equals("activation-runtime-poisoned-store"), "wrong-poison-refusal"); }
            require(count.getInt(pool) == 0
                && Activation.admissions(LatentRuntimeActivationOwnerKind.QueuedWork) == admissions, "poisoned-admission-counted");
            held(0, 0, 1);
        } finally { pool.shutdownNow(); }
        require(pool.awaitTermination(5, TimeUnit.SECONDS), "poisoned-idle-pool-not-retired"); held(0, 0, 0);
    }
    public static void main(String[] args) throws Exception {
        switch (args[0]) {
            case "immediate" -> beforeCommit("immediate");
            case "graceful" -> beforeCommit("graceful");
            case "denied" -> beforeCommit("denied");
            case "lost" -> beforeCommit("lost");
            case "committed" -> committed();
            case "null" -> nullOrThrow(false);
            case "throw" -> nullOrThrow(true);
            case "definite-start" -> startFailure(false);
            case "uncertain-start" -> startFailure(true);
            case "transfer-before", "transfer-after", "transfer-withdraw", "transfer-withdraw-denied",
                 "transfer-withdraw-lost", "transfer-withdraw-swallow" -> transfer(args[0], false);
            case "cached-transfer-before", "cached-transfer-after", "cached-transfer-withdraw",
                 "cached-transfer-withdraw-denied", "cached-transfer-withdraw-lost", "cached-transfer-withdraw-swallow" ->
                transfer(args[0].substring("cached-".length()), true);
            case "transfer-claim" -> claimedDuringTransfer();
            case "duplicate-unstarted" -> duplicateUnstartedWorker();
            case "fixed-queue-admission" -> admissionShutdown(false, "QueuedWork", "none", false);
            case "fixed-result-admission" -> admissionShutdown(false, "Result", "none", false);
            case "fixed-admission-denied" -> admissionShutdown(false, "QueuedWork", "denied", false);
            case "fixed-admission-lost" -> admissionShutdown(false, "QueuedWork", "lost", false);
            case "fixed-result-denied" -> admissionShutdown(false, "Result", "denied", false);
            case "fixed-result-lost" -> admissionShutdown(false, "Result", "lost", false);
            case "fixed-admission-capacity" -> admissionCapacity(false);
            case "fixed-queue-refused" -> admissionRefusal(false, "QueuedWork");
            case "fixed-result-refused" -> admissionRefusal(false, "Result");
            case "fixed-queue-unknown" -> admissionUnknown(false, "QueuedWork");
            case "fixed-result-unknown" -> admissionUnknown(false, "Result");
            case "cached-queue-admission" -> admissionShutdown(true, "QueuedWork", "none", false);
            case "cached-result-admission" -> admissionShutdown(true, "Result", "none", false);
            case "cached-admission-denied" -> admissionShutdown(true, "QueuedWork", "denied", false);
            case "cached-admission-lost" -> admissionShutdown(true, "QueuedWork", "lost", false);
            case "cached-result-denied" -> admissionShutdown(true, "Result", "denied", false);
            case "cached-result-lost" -> admissionShutdown(true, "Result", "lost", false);
            case "cached-admission-capacity" -> admissionCapacity(true);
            case "cached-queue-refused" -> admissionRefusal(true, "QueuedWork");
            case "cached-result-refused" -> admissionRefusal(true, "Result");
            case "cached-queue-unknown" -> admissionUnknown(true, "QueuedWork");
            case "cached-result-unknown" -> admissionUnknown(true, "Result");
            case "fixed-queue-now" -> admissionShutdown(false, "QueuedWork", "none", true);
            case "fixed-result-now" -> admissionShutdown(false, "Result", "none", true);
            case "cached-queue-now" -> admissionShutdown(true, "QueuedWork", "none", true);
            case "cached-result-now" -> admissionShutdown(true, "Result", "none", true);
            case "fixed-prepoisoned" -> prePoisonedAdmission(false);
            case "cached-prepoisoned" -> prePoisonedAdmission(true);
            default -> throw new IllegalArgumentException("mode");
        }
        System.out.println("MANAGED_FIRST_ADMISSION_OWNER PASS " + args[0]);
    }
}
