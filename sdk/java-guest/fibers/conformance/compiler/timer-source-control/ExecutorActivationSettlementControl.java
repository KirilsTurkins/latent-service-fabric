import dev.latent.generated.Bindings;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.Executors;
import dev.latent.guest.runtime.concurrent.ScheduledThreadPoolExecutor;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Actual Activation and pool sources with private Wasm/host stand-ins, not guest execution. */
public final class ExecutorActivationSettlementControl {
    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    private static Field field(Class<?> owner, String name) throws Exception {
        Field field = owner.getDeclaredField(name); field.setAccessible(true); return field;
    }
    private static Object get(String name) throws Exception { return field(Activation.class, name).get(null); }
    private static void set(String name, Object value) throws Exception { field(Activation.class, name).set(null, value); }
    private static Throwable retire(ExecutorService pool, boolean root) {
        try {
            if (root) ((Activation.ManagedPool)pool).closeAtRoot(); else pool.shutdown();
            return null;
        } catch (Throwable error) { return error; }
    }
    private static Throwable invoke(String name) throws Exception {
        var method = Activation.class.getDeclaredMethod(name); method.setAccessible(true);
        try { method.invoke(null); return null; }
        catch (InvocationTargetException expected) { return expected.getCause(); }
    }
    private static ExecutorService create(String kind) {
        return switch (kind) {
            case "managed" -> Executors.newSingleThreadExecutor();
            case "scheduled" -> new ScheduledThreadPoolExecutor(1);
            default -> throw new IllegalArgumentException(kind);
        };
    }
    private static void await(CountDownLatch latch) throws InterruptedException {
        require(latch.await(5, TimeUnit.SECONDS), "inflight-control-timeout");
    }
    @SuppressWarnings("unchecked")
    private static void inflightRoot(String kind, String mode) throws Exception {
        String outcome = mode.substring("inflight-root-".length());
        require(outcome.equals("success") || outcome.equals("denied") || outcome.equals("lost"), "inflight-outcome");
        ExecutorService pool = create(kind);
        Activation.Lease held = (Activation.Lease)field(pool.getClass(), "owner").get(pool);
        var token = (Bindings.LatentRuntimeActivationToken)field(Activation.Lease.class, "token").get(held);
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicReference<Throwable> firstResult = new AtomicReference<>();
        Bindings.LatentRuntimeActivation.settleObservation = () -> {
            entered.countDown();
            try { await(release); } catch (InterruptedException error) { throw new AssertionError(error); }
            if (outcome.equals("lost")) {
                require(!Bindings.LatentRuntimeActivation.settle(token).isError(), "inflight-fake-host-settlement");
                Bindings.LatentRuntimeActivation.settleFailure = new IllegalStateException("source-lost-settlement-ack");
            }
        };
        Thread first = new Thread(() -> firstResult.set(retire(pool, false)));
        first.start();
        AtomicReference<Activation.Lease> failed = (AtomicReference<Activation.Lease>)get("failedQueuedOwners");
        try {
            await(entered);
            AtomicInteger duplicate = new AtomicInteger();
            Bindings.LatentRuntimeActivation.settleObservation = duplicate::incrementAndGet;
            set("closing", true); set("rootComplete", true);
            require(invoke("retireIdlePools") instanceof IllegalStateException && duplicate.get() == 0,
                "inflight-root-collision-not-refused");
            require(retire(pool, true) instanceof IllegalStateException && duplicate.get() == 0 && failed.get() == null,
                "repeated-root-collision-linked-or-retried-owner");
            Bindings.LatentRuntimeActivation.settleObservation = null;
            require((boolean)get("poisoned") && !((Activation.ManagedPool)pool).isRetired()
                && field(pool.getClass(), "owner").get(pool) == held && failed.get() == null,
                "inflight-root-collision-linked-or-dropped-owner");
            require(invoke("requireHealthyCompletion") instanceof IllegalStateException,
                "inflight-root-completion-accepted");
            require(invoke("finishInvocation") == null && ((List<?>)get("pools")).contains(pool)
                && field(pool.getClass(), "owner").get(pool) == held && failed.get() == null,
                "inflight-finish-dropped-owner");
            Bindings.LatentRuntimeActivation.denySettle = outcome.equals("denied");
        } finally {
            release.countDown(); first.join(5000);
        }
        require(!first.isAlive(), "inflight-first-not-finished");
        Bindings.LatentRuntimeActivation.denySettle = false;
        Bindings.LatentRuntimeActivation.settleFailure = null;
        require((boolean)get("poisoned"), "inflight-poison-cleared");
        if (outcome.equals("success")) {
            require(firstResult.get() == null && ((Activation.ManagedPool)pool).isRetired() && failed.get() == null,
                "inflight-confirmed-settlement-not-retired");
        } else {
            require(firstResult.get() instanceof IllegalStateException && failed.get() == held
                && field(Activation.Lease.class, "nextFailedQueued").get(held) == null
                && !((Activation.ManagedPool)pool).isRetired(), "inflight-failure-double-linked-or-retired");
        }
        try { Activation.invoke(0, null, 0); throw new AssertionError("inflight-store-reentered"); }
        catch (IllegalStateException expected) {
            require(expected.getMessage().equals("activation-runtime-poisoned-store"), "inflight-reentry-error");
        }
    }

    @SuppressWarnings("unchecked")
    private static void constructor(String kind, String mode) throws Exception {
        String fault = mode.substring("construct-".length());
        require(fault.equals("normal") || fault.equals("denied") || fault.equals("lost"), "constructor-fault");
        // The actual management guard rejects new pools after retirement begins.
        set("retiringPools", true);
        Map<Bindings.LatentRuntimeActivationToken, ?> owners =
            (Map<Bindings.LatentRuntimeActivationToken, ?>)field(Bindings.LatentRuntimeActivation.class, "owners").get(null);
        AtomicReference<Bindings.LatentRuntimeActivationToken> admitted = new AtomicReference<>();
        Bindings.LatentRuntimeActivation.denySettle = fault.equals("denied");
        Bindings.LatentRuntimeActivation.settleObservation = () -> {
            require(owners.size() == 1, "constructor-owner-not-admitted");
            var token = owners.keySet().iterator().next(); admitted.set(token);
            if (fault.equals("lost")) {
                require(!Bindings.LatentRuntimeActivation.settle(token).isError(), "constructor-fake-host-settlement");
                Bindings.LatentRuntimeActivation.settleFailure = new IllegalStateException("source-lost-settlement-ack");
            }
        };
        Throwable failure = null;
        try {
            if (kind.equals("managed")) Executors.newSingleThreadExecutor();
            else if (kind.equals("scheduled")) new ScheduledThreadPoolExecutor(1);
            else throw new IllegalArgumentException(kind);
        } catch (Throwable error) { failure = error; }
        Bindings.LatentRuntimeActivation.denySettle = false;
        Bindings.LatentRuntimeActivation.settleFailure = null;
        require(failure instanceof IllegalStateException && failure.getMessage().equals("activation-runtime-pool-entry"),
            "constructor-original-failure-not-preserved");
        require(admitted.get() != null, "constructor-not-admitted-before-refusal");
        require(((List<?>)get("pools")).isEmpty(), "failed-constructor-was-registered");
        AtomicReference<Activation.Lease> failed = (AtomicReference<Activation.Lease>)get("failedQueuedOwners");
        if (fault.equals("normal")) {
            require(!(boolean)get("poisoned") && failed.get() == null && owners.isEmpty(), "confirmed-rollback-not-retired");
        } else {
            require((boolean)get("poisoned") && failed.get() != null, "constructor-uncertain-owner-not-rooted");
            require(field(Activation.Lease.class, "token").get(failed.get()).equals(admitted.get()),
                "constructor-original-token-not-rooted");
            require(owners.containsKey(admitted.get()) == fault.equals("denied"), "constructor-fake-host-outcome");
            Throwable completion = invoke("requireHealthyCompletion");
            require(completion instanceof IllegalStateException, "constructor-uncertain-completion-accepted");
            Activation.Lease held = failed.get();
            require(invoke("finishInvocation") == null && failed.get() == held && (boolean)get("poisoned"),
                "finish-dropped-constructor-owner");
            try { Activation.invoke(0, null, 0); throw new AssertionError("constructor-store-reentered"); }
            catch (IllegalStateException expected) {
                require(expected.getMessage().equals("activation-runtime-poisoned-store"), "constructor-reentry-error");
            }
        }
    }
    public static void main(String[] args) throws Exception {
        require(args.length == 2, "usage");
        String kind = args[0], mode = args[1];
        set("entered", true);
        if (mode.startsWith("inflight-root-")) {
            inflightRoot(kind, mode);
            System.out.println("EXECUTOR_ACTIVATION_SETTLEMENT PASS " + kind + " " + mode);
            return;
        }
        if (mode.startsWith("construct-")) {
            constructor(kind, mode);
            System.out.println("EXECUTOR_ACTIVATION_SETTLEMENT PASS " + kind + " " + mode);
            return;
        }
        boolean root = mode.startsWith("root-");
        String fault = root ? mode.substring(5) : mode;
        require(fault.equals("denied") || fault.equals("lost"), "fault");
        ExecutorService pool = create(kind);
        Activation.Lease held = (Activation.Lease)field(pool.getClass(), "owner").get(pool);
        var token = (Bindings.LatentRuntimeActivationToken)field(Activation.Lease.class, "token").get(held);
        if (fault.equals("denied")) Bindings.LatentRuntimeActivation.denySettle = true;
        else Bindings.LatentRuntimeActivation.settleObservation = () -> {
            require(!Bindings.LatentRuntimeActivation.settle(token).isError(), "fake-host-first-settlement");
            Bindings.LatentRuntimeActivation.settleFailure = new IllegalStateException("source-lost-settlement-ack");
        };
        require(retire(pool, root) instanceof IllegalStateException, "expected-original-failure");
        Bindings.LatentRuntimeActivation.denySettle = false;
        Bindings.LatentRuntimeActivation.settleFailure = null;
        require((boolean)get("poisoned"), "uncertain-settlement-not-poisoned");
        require(field(pool.getClass(), "owner").get(pool) == held && !pool.isTerminated()
            && !((Activation.ManagedPool)pool).isRetired(), "original-pool-owner-not-live");
        @SuppressWarnings("unchecked") AtomicReference<Activation.Lease> failed =
            (AtomicReference<Activation.Lease>)get("failedQueuedOwners");
        require(failed.get() == held, "same-original-lease-not-rooted");
        @SuppressWarnings("unchecked") Map<Bindings.LatentRuntimeActivationToken, ?> owners =
            (Map<Bindings.LatentRuntimeActivationToken, ?>)field(Bindings.LatentRuntimeActivation.class, "owners").get(null);
        require(owners.containsKey(token) == fault.equals("denied"), "fake-host-outcome");
        AtomicInteger retries = new AtomicInteger();
        Bindings.LatentRuntimeActivation.settleObservation = retries::incrementAndGet;
        Throwable repeat = retire(pool, !root);
        require((root ? repeat == null : repeat instanceof IllegalStateException) && retries.get() == 0,
            "repeat-reentered-host");
        set("closing", true);
        require(invoke("retireIdlePools") instanceof IllegalStateException && retries.get() == 0,
            "root-retried-uncertain-owner");
        Throwable completion = invoke("requireHealthyCompletion");
        require(completion instanceof IllegalStateException && completion.getMessage().equals("activation-runtime-owner-settlement-uncertain"),
            "poisoned-root-completion-accepted");
        require(invoke("finishInvocation") == null, "finish-failed");
        @SuppressWarnings("unchecked") List<Activation.ManagedPool> pools = (List<Activation.ManagedPool>)get("pools");
        require(!(boolean)get("entered") && (boolean)get("poisoned") && pools.contains(pool)
            && failed.get() == held && field(pool.getClass(), "owner").get(pool) == held,
            "finish-dropped-original-owner");
        try { Activation.invoke(0, null, 0); throw new AssertionError("poisoned-store-reentered"); }
        catch (IllegalStateException expected) {
            require(expected.getMessage().equals("activation-runtime-poisoned-store"), "wrong-reentry-error");
        }
        System.out.println("EXECUTOR_ACTIVATION_SETTLEMENT PASS " + kind + " " + mode);
    }
}
