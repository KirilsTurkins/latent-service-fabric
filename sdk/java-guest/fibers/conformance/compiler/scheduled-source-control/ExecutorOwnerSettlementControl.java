import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.Executors;
import dev.latent.guest.runtime.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Actual executor sources with a fault-injecting ledger, not a signed guest. */
public final class ExecutorOwnerSettlementControl {
    private static final LatentRuntimeActivationOwnerKind EXECUTOR = LatentRuntimeActivationOwnerKind.Executor;
    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    private static ExecutorService create(String kind) {
        return switch (kind) {
            case "managed" -> Executors.newSingleThreadExecutor();
            case "scheduled" -> new ScheduledThreadPoolExecutor(1);
            default -> throw new IllegalArgumentException(kind);
        };
    }
    private static Throwable retire(ExecutorService pool, boolean root) {
        try {
            if (root) ((Activation.ManagedPool)pool).closeAtRoot();
            else pool.shutdown();
            return null;
        } catch (Throwable error) { return error; }
    }
    private static void await(CountDownLatch latch) throws InterruptedException {
        require(latch.await(5, TimeUnit.SECONDS), "concurrent-control-timeout");
    }
    public static void main(String[] args) throws Exception {
        require(args.length == 2, "usage");
        String kind = args[0], mode = args[1];
        if (mode.equals("construct-reentry")) {
            IllegalStateException original = new IllegalStateException("source-manage-reentry");
            AtomicReference<Activation.ManagedPool> partial = new AtomicReference<>();
            Activation.manageObservation = pool -> { partial.set(pool); pool.closeAtRoot(); };
            Activation.closeObservationKind = "Executor";
            Activation.closeObservation = () -> { throw original; };
            Throwable observed = null;
            try { create(kind); } catch (Throwable error) { observed = error; }
            require(observed == original && Activation.poisoned, "reentrant-constructor-error-not-preserved");
            require(partial.get() != null, "missing-partial-pool");
            var ownerField = partial.get().getClass().getDeclaredField("owner"); ownerField.setAccessible(true);
            var held = (Activation.Lease)ownerField.get(partial.get());
            require(Activation.retainsOwner(held) && Activation.closeAttempts(EXECUTOR) == 1
                && Activation.count(EXECUTOR) == 1, "reentrant-constructor-original-owner-not-retained");
            System.out.println("EXECUTOR_OWNER_SETTLEMENT PASS " + kind + " " + mode);
            return;
        }
        if (mode.startsWith("construct-")) {
            String fault = mode.substring("construct-".length());
            boolean oom = fault.startsWith("oom-");
            if (oom) fault = fault.substring(4);
            require(fault.equals("normal") || fault.equals("denied") || fault.equals("lost"), "constructor-fault");
            Throwable original = oom ? new OutOfMemoryError("source-manage-oom") : new IllegalStateException("source-manage-failure");
            Activation.manageFailure = original;
            if (fault.equals("denied")) Activation.denyCloseNext = "Executor";
            if (fault.equals("lost")) Activation.loseCloseAckNext = "Executor";
            Throwable observed = null;
            try { create(kind); } catch (Throwable error) { observed = error; }
            require(observed == original, "constructor-original-failure-not-preserved");
            require(Activation.closeAttempts(EXECUTOR) == 1, "constructor-settlement-attempts");
            if (fault.equals("normal")) {
                require(!Activation.poisoned && Activation.count(EXECUTOR) == 0, "successful-rollback-not-retired");
            } else {
                require(Activation.poisoned && Activation.retainsFailedQueued(), "constructor-original-owner-not-rooted");
                require(Activation.failedLeaseAttempts() == 1 && Activation.count(EXECUTOR) == (fault.equals("denied") ? 1 : 0),
                    "constructor-host-outcome");
                try { Activation.owner(EXECUTOR); throw new AssertionError("constructor-admission-after-poison"); }
                catch (IllegalStateException expected) { }
                require(Activation.failedLeaseAttempts() == 1, "constructor-original-owner-retried");
            }
            System.out.println("EXECUTOR_OWNER_SETTLEMENT PASS " + kind + " " + mode);
            return;
        }
        boolean root = mode.startsWith("root-");
        String scenario = root ? mode.substring(5) : mode;
        ExecutorService pool = create(kind);
        require(Activation.count(EXECUTOR) == 1, "missing-original-executor-owner");
        if (scenario.equals("normal")) {
            require(retire(pool, root) == null && retire(pool, root) == null, "normal-retirement-error");
            require(pool.isTerminated(), "normal-retirement-not-terminated");
            require(Activation.closeAttempts(EXECUTOR) == 1 && Activation.count(EXECUTOR) == 0,
                "normal-owner-accounting");
        } else if (scenario.equals("denied") || scenario.equals("lost")) {
            if (scenario.equals("denied")) Activation.denyCloseNext = "Executor";
            else Activation.loseCloseAckNext = "Executor";
            Throwable first = retire(pool, root);
            require(first instanceof IllegalStateException, "missing-first-failure");
            require(Activation.poisoned && Activation.retainsFailedQueued(), "original-owner-not-rooted-and-fenced");
            require(Activation.closeAttempts(EXECUTOR) == 1, "first-attempt-count");
            Throwable repeated = retire(pool, !root);
            require(root ? repeated == null : repeated instanceof IllegalStateException, "repeat-path-semantics");
            require(Activation.closeAttempts(EXECUTOR) == 1 && !pool.isTerminated(), "owner-retried-or-retired");
            require(Activation.count(EXECUTOR) == (scenario.equals("denied") ? 1 : 0), "incorrect-host-outcome");
            try { Activation.owner(EXECUTOR); throw new AssertionError("admitted-after-poison"); }
            catch (IllegalStateException expected) { }
        } else if (scenario.equals("concurrent")) {
            CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
            AtomicReference<Throwable> firstResult = new AtomicReference<>();
            Activation.closeObservationKind = "Executor";
            Activation.closeObservation = () -> {
                entered.countDown();
                try { await(release); } catch (InterruptedException error) { throw new AssertionError(error); }
            };
            Thread first = new Thread(() -> firstResult.set(retire(pool, !root)));
            first.start();
            try {
                await(entered);
                Throwable second = retire(pool, root);
                require(root ? second instanceof IllegalStateException : second == null, "concurrent-attempt-semantics");
                require(!((Activation.ManagedPool)pool).isRetired(), "in-flight-owner-retired");
                require(Activation.poisoned == root, "root-collision-fence");
            } finally { release.countDown(); }
            first.join(5000);
            require(!first.isAlive() && firstResult.get() == null, "first-retirement-not-finished");
            require(Activation.closeAttempts(EXECUTOR) == 1 && Activation.count(EXECUTOR) == 0
                && pool.isTerminated() && Activation.poisoned == root, "concurrent-owner-accounting");
        } else if (scenario.equals("reenter-caught") || scenario.equals("reenter-throws")) {
            AtomicReference<Throwable> nested = new AtomicReference<>();
            Activation.closeObservationKind = "Executor";
            Activation.closeObservation = () -> {
                if (scenario.equals("reenter-throws")) {
                    if (root) ((Activation.ManagedPool)pool).closeAtRoot(); else pool.shutdown();
                } else nested.set(retire(pool, root));
            };
            Throwable outer = retire(pool, !root);
            int attempts = Activation.closeAttempts(EXECUTOR);
            int outstanding = Activation.count(EXECUTOR);
            if (!root) {
                require(outer == null && nested.get() == null && !Activation.poisoned,
                    "repeated-shutdown-was-not-idempotent");
                require(attempts == 1 && outstanding == 0 && pool.isTerminated(), "known-settlement-not-retired");
            } else if (scenario.equals("reenter-caught")) {
                require(nested.get() instanceof IllegalStateException && outer == null && Activation.poisoned,
                    "root-collision-not-fenced");
                require(attempts == 1 && outstanding == 0 && pool.isTerminated(), "known-settlement-not-retired");
            } else {
                require(outer instanceof IllegalStateException && Activation.poisoned, "nested-failure-not-fenced");
                require(attempts == 1 && outstanding == 1 && !pool.isTerminated(), "uncertain-original-not-retained");
                require(retire(pool, root) instanceof IllegalStateException && Activation.closeAttempts(EXECUTOR) == 1,
                    "uncertain-original-retried");
            }
        } else throw new IllegalArgumentException(mode);
        System.out.println("EXECUTOR_OWNER_SETTLEMENT PASS " + kind + " " + mode);
    }
}
