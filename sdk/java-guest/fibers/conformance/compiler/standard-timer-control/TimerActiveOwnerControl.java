import dev.latent.generated.Bindings;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.util.Timer;
import dev.latent.guest.runtime.util.TimerTask;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Finite host/source ledger; not a TeaVM or signed component execution. */
public final class TimerActiveOwnerControl {
    private static void require(boolean value, String reason) {
        if (!value) throw new AssertionError(reason);
    }
    private static void await(CountDownLatch latch, String reason) {
        try { require(latch.await(4, TimeUnit.SECONDS), reason); }
        catch (InterruptedException error) { throw new AssertionError(reason, error); }
    }
    private static void publicTaskMonitor() throws Exception {
        Timer timer = new Timer("task-public-monitor", true);
        TimerTask task = new TimerTask() {
            @Override public void run() { throw new AssertionError("cancelled-task-ran"); }
        };
        timer.schedule(task, 60_000);
        require(Activation.queued() == 1 && Activation.executors() == 1, "owner-not-admitted");
        CountDownLatch entered = new CountDownLatch(1), finished = new CountDownLatch(1);
        AtomicReference<Throwable> failure = new AtomicReference<>();
        Thread canceller = new Thread(() -> {
            entered.countDown();
            try { require(task.cancel(), "scheduled-cancel-failed"); }
            catch (Throwable error) { failure.set(error); }
            finally { finished.countDown(); }
        });
        try {
            // Holding the application-visible monitor must not stop cancellation
            // or the worker from retiring the original queued-work owner.
            synchronized (task) {
                canceller.start();
                await(entered, "canceller-not-started");
                await(finished, "cancel-blocked-on-public-monitor");
                require(failure.get() == null, "cancel-failed");
                long end = System.nanoTime() + TimeUnit.SECONDS.toNanos(4);
                while (Activation.queued() != 0 && System.nanoTime() < end) Thread.sleep(1);
                require(Activation.queued() == 0, "queued-owner-blocked-on-public-monitor");
            }
        } finally {
            canceller.join(5000);
            timer.cancel();
            Activation.cleanup();
        }
        require(!canceller.isAlive() && Activation.owners() == 0 && Activation.queuedAttempts() == 1,
                "monitor-control-cleanup");
    }
    private static void withdrawn(String mode) throws Exception {
        boolean periodic = !mode.startsWith("one-shot");
        boolean self = mode.startsWith("self-");
        boolean purge = mode.endsWith("purge");
        boolean throwCallback = mode.equals("one-shot-error");
        Timer timer = new Timer("withdrawn-" + mode, true);
        CountDownLatch entered = new CountDownLatch(1), withdrawn = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1), finished = new CountDownLatch(1), uncaught = new CountDownLatch(1);
        AtomicInteger before = new AtomicInteger(-1), after = new AtomicInteger(-1), purged = new AtomicInteger(-1);
        AtomicReference<Throwable> threadFailure = new AtomicReference<>();
        RuntimeException original = new IllegalStateException("original-callback");
        Thread main = Thread.currentThread();
        Thread.setDefaultUncaughtExceptionHandler((thread, error) -> {
            if (thread == main) error.printStackTrace();
            else { threadFailure.set(error); uncaught.countDown(); }
        });
        TimerTask task = new TimerTask() {
            @Override public void run() {
                try {
                    before.set(Activation.queued());
                    entered.countDown();
                    if (self) {
                        require(cancel(), "self-cancel-result");
                        if (purge) purged.set(timer.purge());
                        after.set(Activation.queued());
                        withdrawn.countDown();
                    }
                    await(release, "callback-release");
                    if (throwCallback) throw original;
                } finally { finished.countDown(); }
            }
        };
        if (periodic) timer.scheduleAtFixedRate(task, 0, 60_000);
        else timer.schedule(task, 0);
        await(entered, "callback-start");
        if (self) await(withdrawn, "self-withdrawal");
        else if (purge) {
            require(task.cancel(), "external-cancel-result");
            purged.set(timer.purge());
            after.set(Activation.queued());
        } else {
            timer.cancel();
            after.set(Activation.queued());
        }
        require(before.get() == 1 && after.get() == 1, "owner-not-held-through-callback");
        require(timer.hasPendingWork(), "running-callback-not-pending");
        require(!timer.isRetired(), "timer-retired-during-callback");
        if (purge) require(purged.get() == 1, "purge-did-not-withdraw-running-entry");
        timer.cancel();
        require(Activation.queued() == 1, "owner-lost-after-timer-cancel");
        release.countDown();
        await(finished, "callback-finish");
        if (throwCallback) { await(uncaught, "callback-exception"); require(threadFailure.get() == original, "callback-exception-replaced"); }
        Activation.cleanup();
        require(Activation.owners() == 0 && Activation.queuedAttempts() == 1, "owner-not-retired-once");
    }

    private static void recurring(boolean fixedRate) throws Exception {
        Timer timer = new Timer("recurring", true);
        CountDownLatch first = new CountDownLatch(1), next = new CountDownLatch(1);
        CountDownLatch firstRelease = new CountDownLatch(1), lastRelease = new CountDownLatch(1), done = new CountDownLatch(1);
        AtomicInteger calls = new AtomicInteger(), heldFirst = new AtomicInteger(-1), heldNext = new AtomicInteger(-1);
        TimerTask task = new TimerTask() {
            @Override public void run() {
                int call = calls.incrementAndGet();
                if (call == 1) { heldFirst.set(Activation.queued()); first.countDown(); await(firstRelease, "first-release"); }
                else if (call == 2) {
                    heldNext.set(Activation.queued()); next.countDown();
                    try { await(lastRelease, "last-release"); } finally { done.countDown(); }
                } else throw new AssertionError("unexpected-recurring-call");
            }
        };
        if (fixedRate) timer.scheduleAtFixedRate(task, 0, 10);
        else timer.schedule(task, 0, 10);
        await(first, "first-call");
        firstRelease.countDown();
        await(next, "rescheduled-call");
        timer.cancel();
        require(heldFirst.get() == 1 && heldNext.get() == 1 && Activation.queued() == 1,
                "recurring-owner-not-held");
        lastRelease.countDown();
        await(done, "rescheduled-finish");
        Activation.cleanup();
        require(calls.get() == 2 && Activation.owners() == 0 && Activation.queuedAttempts() == 1,
                "recurring-retirement");
    }

    private static void failedSettlement(String mode) throws Exception {
        boolean lost = mode.endsWith("lost"), periodic = mode.startsWith("periodic-");
        boolean callbackFails = mode.contains("callback-");
        Timer timer = new Timer("failed-settlement", true);
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1), uncaught = new CountDownLatch(1);
        AtomicReference<Throwable> threadFailure = new AtomicReference<>();
        RuntimeException original = new IllegalStateException("original-callback");
        Thread main = Thread.currentThread();
        Thread.setDefaultUncaughtExceptionHandler((thread, error) -> {
            if (thread == main) error.printStackTrace();
            else { threadFailure.set(error); uncaught.countDown(); }
        });
        TimerTask task = new TimerTask() {
            @Override public void run() {
                entered.countDown(); await(release, "settlement-release");
                if (callbackFails) throw original;
            }
        };
        if (periodic) timer.scheduleAtFixedRate(task, 0, 60_000);
        else timer.schedule(task, 0);
        await(entered, "settlement-callback-start");
        require(Activation.queued() == 1, "settlement-owner-not-held");
        Activation.failQueuedSettlement = lost ? "lost" : "refused";
        // Leave a periodic entry queued so work()'s final queue cleanup must
        // preserve the callback failure if this owner's settlement is refused.
        if (!periodic) timer.cancel();
        require(Activation.queued() == 1 && Activation.queuedAttempts() == 0, "settled-before-callback-exit");
        release.countDown();
        await(uncaught, "settlement-failure");
        require(!timer.isRetired() && timer.hasPendingWork(), "uncertain-cleanup-lost-timer-owner");
        require(Activation.poisoned() && Activation.retainedFailedQueued(), "uncertain-owner-not-retained");
        require(Activation.queuedAttempts() == 1 && Activation.queued() == (lost ? 0 : 1), "settlement-retried");
        if (callbackFails) require(threadFailure.get() == original, "original-callback-error-replaced");
        else require(threadFailure.get() instanceof IllegalStateException, "missing-settlement-error");
        timer.cancel(); timer.cancel();
        try {
            Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork);
            throw new AssertionError("poisoned-admission-accepted");
        } catch (IllegalStateException expected) { }
        require(Activation.queuedAttempts() == 1, "settlement-retried-after-poison");
    }

    private static void failedQueuedCancellation(boolean lost) throws Exception {
        Timer timer = new Timer("failed-queued-cancel", true);
        timer.schedule(new TimerTask() {
            @Override public void run() { throw new AssertionError("cancelled-task-ran"); }
        }, 60_000);
        Activation.failQueuedSettlement = lost ? "lost" : "refused";
        try { timer.cancel(); throw new AssertionError("missing-cancel-settlement-error"); }
        catch (IllegalStateException expected) { }
        Activation.joinWorkers();
        require(!timer.isRetired() && timer.hasPendingWork(), "cancel-uncertainty-not-pending");
        require(Activation.poisoned() && Activation.retainedFailedQueued(), "cancel-owner-not-retained");
        require(Activation.queuedAttempts() == 1 && Activation.queued() == (lost ? 0 : 1), "cancel-settlement-retried");
        timer.cancel(); timer.cancel();
        require(Activation.queuedAttempts() == 1, "cancel-retried-after-poison");
    }

    private static int pending(Timer timer) throws Exception {
        var field = Timer.class.getDeclaredField("pendingWork");
        field.setAccessible(true);
        return field.getInt(timer);
    }

    private static void settlementInFlight(String mode) throws Exception {
        Timer timer = new Timer("inflight-" + mode, true);
        CountDownLatch ackEntered = new CountDownLatch(1), ackRelease = new CountDownLatch(1);
        CountDownLatch activeStarted = new CountDownLatch(1), activeRelease = new CountDownLatch(1);
        AtomicBoolean earlyRetirement = new AtomicBoolean();
        AtomicReference<Throwable> actionFailure = new AtomicReference<>();
        TimerTask future = new TimerTask() { @Override public void run() { throw new AssertionError("future-ran"); } };
        Thread action = null;
        try {
            if (mode.equals("purge-ack")) {
                timer.schedule(new TimerTask() {
                    @Override public void run() { activeStarted.countDown(); await(activeRelease, "active-release"); }
                }, 0);
                await(activeStarted, "active-start");
                timer.schedule(future, 60_000);
                require(future.cancel(), "future-cancel");
            } else if (!mode.equals("callback-ack")) timer.schedule(future, 60_000);
            Activation.onQueuedSettlement = () -> {
                if (Activation.retireIfIdle(timer)) earlyRetirement.set(true);
            };
            Activation.queuedSettlementEntered = ackEntered;
            Activation.queuedSettlementRelease = ackRelease;
            if (mode.equals("callback-ack")) {
                timer.schedule(new TimerTask() { @Override public void run() { } }, 0);
            } else if (mode.equals("cancelled-head-ack")) require(future.cancel(), "head-cancel");
            else {
                action = new Thread(() -> {
                    try {
                        if (mode.equals("clear-queue-ack")) timer.cancel();
                        else require(timer.purge() == 1, "purge-not-withdrawn");
                    } catch (Throwable error) { actionFailure.set(error); }
                }, "timer-settlement-observer");
                action.start();
            }
            await(ackEntered, "ack-not-entered");
            require(timer.hasPendingWork() && !timer.isRetired() && !earlyRetirement.get(), "retired-before-ack");
            require(pending(timer) == (mode.equals("purge-ack") ? 2 : 1), "pending-count-before-ack");
        } finally {
            ackRelease.countDown();
            activeRelease.countDown();
        }
        if (action != null) {
            action.join(5000);
            require(!action.isAlive() && actionFailure.get() == null, "withdrawal-action-failed");
        }
        Activation.onQueuedSettlement = null;
        timer.cancel();
        Activation.cleanup();
        require(!earlyRetirement.get() && Activation.owners() == 0, "inflight-retirement");
    }

    private static void failedStart(String mode) throws Exception {
        Activation.failManagedStart = mode;
        IllegalStateException original = new IllegalStateException("source-start-" + mode);
        Activation.startFailure = original;
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        if (mode.equals("accepted")) {
            Activation.executorSettlementEntered = entered;
            Activation.executorSettlementRelease = release;
        }
        try {
            try { new Timer("failed-start-" + mode, true); throw new AssertionError("start-succeeded"); }
            catch (IllegalStateException actual) { require(actual == original, "start-error-replaced"); }
            Activation.ManagedPool pool = Activation.lastPool;
            require(pool != null, "failed-start-pool-missing");
            if (mode.equals("before")) {
                require(pool.isRetired() && Activation.executors() == 0 && Activation.executorAttempts() == 1,
                        "confirmed-start-refusal-must-retire-executor");
            } else if (mode.equals("uncertain")) {
                require(!pool.isRetired() && Activation.executors() == 1 && Activation.executorAttempts() == 0,
                        "uncertain-start-must-retain-executor");
                require(Activation.alive(Activation.lastWorker), "uncertain-start-owner-missing");
            } else {
                require(!pool.isRetired() && Activation.executors() == 1, "accepted-start-must-retain-executor");
                await(entered, "accepted-worker-not-woken-for-retirement");
                require(Activation.lastWorker.isAlive(), "accepted-worker-retired-before-settlement");
                release.countDown();
                Activation.joinWorkers();
                require(pool.isRetired() && Activation.executors() == 0 && Activation.executorAttempts() == 1,
                        "accepted-worker-must-retire-executor-once");
            }
        } finally {
            release.countDown();
            if (mode.equals("accepted") && Activation.lastWorker != null) {
                Activation.lastWorker.interrupt();
                Activation.lastWorker.join(5000);
            }
        }
    }

    private static void failedManage(String settlement) {
        Activation.failManage = true;
        IllegalStateException original = new IllegalStateException("source-manage-refused");
        Activation.startFailure = original;
        if (!settlement.equals("ok")) Activation.failExecutorSettlement = settlement;
        try { new Timer("failed-manage", true); throw new AssertionError("manage-succeeded"); }
        catch (IllegalStateException actual) { require(actual == original, "manage-error-replaced"); }
        Activation.ManagedPool pool = Activation.lastPool;
        require(pool != null && !Activation.poolRegistered(pool), "refused-pool-was-registered");
        if (settlement.equals("ok")) {
            require(pool.isRetired() && Activation.executors() == 0 && Activation.executorAttempts() == 1,
                    "unregistered-pool-owner-not-retired");
        } else {
            require(!pool.isRetired() && Activation.poisoned() && Activation.retainedFailedExecutor()
                    && Activation.failedOwnerLinks() == 1 && Activation.executorAttempts() == 1
                    && Activation.executors() == (settlement.equals("lost") ? 0 : 1),
                    "unregistered-pool-failed-owner-not-rooted");
            pool.closeAtRoot(); pool.closeAtRoot();
            require(Activation.failedOwnerLinks() == 1 && Activation.executorAttempts() == 1,
                    "unregistered-pool-settlement-retried");
        }
    }

    private static void failedStartSettlement(boolean lost) {
        Activation.failManagedStart = "before";
        IllegalStateException original = new IllegalStateException("source-start-before");
        Activation.startFailure = original;
        Activation.failExecutorSettlement = lost ? "lost" : "refused";
        try { new Timer("failed-start-settlement", true); throw new AssertionError("start-succeeded"); }
        catch (IllegalStateException actual) { require(actual == original, "start-error-replaced-by-settlement"); }
        Activation.ManagedPool pool = Activation.lastPool;
        require(pool != null && !pool.isRetired(), "uncertain-executor-owner-cleared");
        require(Activation.poisoned() && Activation.retainedFailedExecutor() && Activation.failedOwnerLinks() == 1,
                "failed-executor-not-rooted-once");
        require(Activation.executorAttempts() == 1 && Activation.executors() == (lost ? 0 : 1),
                "executor-settlement-retried-or-refunded");
        pool.closeAtRoot(); pool.closeAtRoot();
        try { Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.Executor);
              throw new AssertionError("poisoned-admission-accepted"); }
        catch (IllegalStateException expected) { }
        require(Activation.executorAttempts() == 1, "executor-settlement-retried-after-poison");
    }

    private static void completedWorkerBeforeStartFailure() {
        Activation.failManagedStart = "finished-ok";
        IllegalStateException original = new IllegalStateException("source-start-after-completed-worker");
        Activation.startFailure = original;
        try { new Timer("failed-start-completed-worker", true); throw new AssertionError("start-succeeded"); }
        catch (IllegalStateException actual) { require(actual == original, "start-error-replaced-after-completion"); }
        Activation.ManagedPool pool = Activation.lastPool;
        require(pool != null && pool.isRetired() && Activation.executors() == 0
                && Activation.executorAttempts() == 1 && !Activation.poisoned(),
                "completed-worker-owner-not-settled-once");
    }

    private static void failedStartAfterWorkerSettlement(boolean lost) {
        Activation.failManagedStart = lost ? "finished-lost" : "finished-refused";
        IllegalStateException original = new IllegalStateException("source-start-after-worker");
        Activation.startFailure = original;
        Activation.failExecutorSettlement = lost ? "lost" : "refused";
        try { new Timer("failed-start-finished-worker", true); throw new AssertionError("start-succeeded"); }
        catch (IllegalStateException actual) { require(actual == original, "start-error-replaced-after-worker"); }
        Activation.ManagedPool pool = Activation.lastPool;
        require(pool != null && !pool.isRetired(), "failed-worker-executor-owner-cleared");
        require(Activation.poisoned() && Activation.retainedFailedExecutor() && Activation.failedOwnerLinks() == 1,
                "failed-worker-executor-not-rooted-once");
        require(Activation.executorAttempts() == 1 && Activation.executors() == (lost ? 0 : 1),
                "failed-worker-executor-settlement-retried");
        pool.closeAtRoot(); pool.closeAtRoot();
        require(Activation.executorAttempts() == 1 && Activation.failedOwnerLinks() == 1,
                "failed-worker-settlement-retried-after-poison");
    }

    public static void main(String[] args) throws Exception {
        require(args.length == 1, "case-required");
        String mode = args[0];
        switch (mode) {
            case "public-task-monitor" -> publicTaskMonitor();
            case "one-shot-normal", "one-shot-error", "external-cancel", "external-purge",
                 "self-cancel", "self-purge" -> withdrawn(mode);
            case "fixed-rate-reschedule" -> recurring(true);
            case "fixed-delay-reschedule" -> recurring(false);
            case "refused", "lost", "callback-refused", "callback-lost",
                 "periodic-callback-refused", "periodic-callback-lost" -> failedSettlement(mode);
            case "cancel-refused" -> failedQueuedCancellation(false);
            case "cancel-lost" -> failedQueuedCancellation(true);
            case "callback-ack", "clear-queue-ack", "cancelled-head-ack", "purge-ack" -> settlementInFlight(mode);
            case "manage-before" -> failedManage("ok");
            case "manage-close-refused" -> failedManage("refused");
            case "manage-close-lost" -> failedManage("lost");
            case "start-before" -> failedStart("before");
            case "start-uncertain" -> failedStart("uncertain");
            case "start-accepted" -> failedStart("accepted");
            case "start-close-refused" -> failedStartSettlement(false);
            case "start-close-lost" -> failedStartSettlement(true);
            case "start-finished-ok" -> completedWorkerBeforeStartFailure();
            case "start-finished-refused" -> failedStartAfterWorkerSettlement(false);
            case "start-finished-lost" -> failedStartAfterWorkerSettlement(true);
            default -> throw new AssertionError("unknown-case");
        }
        System.out.println("TIMER_ACTIVE_OWNER_CONTROL PASS " + mode);
    }
}
