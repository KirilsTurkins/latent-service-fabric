import dev.latent.generated.Bindings;
import dev.latent.generated.Bindings.LatentRuntimeActivation;
import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.Option;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.Monitors;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.util.IdentityHashMap;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Actual owner cleanup with a private host ledger; never a Wasm trap simulation. */
public final class OwnerSettlementSourceControl {
    private static final LatentRuntimeActivationOwnerKind WAIT = LatentRuntimeActivationOwnerKind.Wait;
    private static Object root;

    private static Field field(Class<?> type, String name) throws Exception {
        Field result = type.getDeclaredField(name);
        result.setAccessible(true);
        return result;
    }
    private static Object get(String name) throws Exception { return field(Activation.class, name).get(null); }
    private static void set(String name, Object value) throws Exception { field(Activation.class, name).set(null, value); }
    private static Object lease(Activation.Lease owner, String name) throws Exception {
        return field(Activation.Lease.class, name).get(owner);
    }
    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    private static void finish() throws Exception {
        var method = Activation.class.getDeclaredMethod("finishInvocation", boolean.class);
        method.setAccessible(true);
        try { method.invoke(null, true); }
        catch (InvocationTargetException error) {
            if (error.getCause() instanceof Exception cause) throw cause;
            if (error.getCause() instanceof java.lang.Error cause) throw cause;
            throw error;
        }
    }
    private static Throwable closing(Activation.Lease owner) {
        try { owner.close(); return null; } catch (Throwable error) { return error; }
    }
    private static void clean() throws Exception {
        require(!(boolean)get("poisoned"), "healthy-settlement-poisoned");
        require((int)get("pendingOwnerSettlements") == 0 && get("settlingOwners") == null,
            "settled-owner-still-pending");
    }
    private static void fenced() throws Exception {
        require((boolean)get("poisoned"), "uncertain-settlement-not-fenced");
        int attempts = LatentRuntimeActivation.registrationAttempts;
        try { Activation.owner(WAIT); throw new AssertionError("later-owner-admitted"); }
        catch (IllegalStateException expected) {
            require("activation-runtime-poisoned-store".equals(expected.getMessage()), "later-admission-error");
        }
        require(attempts == LatentRuntimeActivation.registrationAttempts, "later-host-registration");
        try { finish(); throw new AssertionError("uncertain-completion-accepted"); }
        catch (IllegalStateException expected) { }
        require(get("root") == root && ((Map<?, ?>)get("threads")).get(Thread.currentThread()) == root,
            "teardown-dropped-original-work");
    }
    private static void retained(Activation.Lease owner, Object token, int pending) throws Exception {
        require((boolean)get("poisoned"), "uncertain-settlement-not-fenced");
        require(lease(owner, "token") == token, "uncertain-token-discarded");
        require((int)get("pendingOwnerSettlements") == pending, "uncertain-settlement-count");
        if (pending == 1) require(get("settlingOwners") == owner, "inflight-owner-not-rooted");
        @SuppressWarnings("unchecked")
        var failed = (AtomicReference<Activation.Lease>)get("failedQueuedOwners");
        require(failed.get() == owner && lease(owner, "nextFailedQueued") == null, "failed-owner-not-rooted-once");
        // The executor/future callers also retain after close throws. Duplicate
        // reports must neither retry the host nor turn the intrusive list cyclic.
        Activation.fenceUncertainQueuedWorkSettlement(owner);
        Activation.fenceUncertainQueuedWorkSettlement(owner);
        int attempts = LatentRuntimeActivation.settlementAttempts;
        require(closing(owner) instanceof IllegalStateException, "uncertain-owner-retry-accepted");
        require(attempts == LatentRuntimeActivation.settlementAttempts, "uncertain-owner-retried-host");
        require(failed.get() == owner && lease(owner, "nextFailedQueued") == null, "duplicate-owner-link");
        fenced();
        require(failed.get() == owner && lease(owner, "token") == token, "teardown-dropped-failed-owner");
    }
    private static Runnable observe(RunnableWithException action) {
        return () -> {
            try { action.run(); }
            catch (Exception error) { throw new AssertionError("source-observation", error); }
        };
    }
    private interface RunnableWithException { void run() throws Exception; }

    @SuppressWarnings("unchecked")
    public static void main(String[] args) throws Exception {
        require(args.length == 1, "usage");
        var rootToken = LatentRuntimeActivation.register(LatentRuntimeActivationOwnerKind.Task, Option.none()).value();
        Class<?> work = Class.forName("dev.latent.guest.runtime.Activation$Work");
        var constructor = work.getDeclaredConstructor(Bindings.LatentRuntimeActivationToken.class);
        constructor.setAccessible(true);
        root = constructor.newInstance(rootToken);
        ((Map<Thread, Object>)get("threads")).put(Thread.currentThread(), root);
        set("root", root); set("entered", true);
        switch (args[0]) {
            case "normal", "refused" -> {
                for (var kind : new LatentRuntimeActivationOwnerKind[] { WAIT,
                        LatentRuntimeActivationOwnerKind.Result, LatentRuntimeActivationOwnerKind.QueuedWork,
                        LatentRuntimeActivationOwnerKind.Executor }) {
                    var owner = Activation.owner(kind);
                    Object token = lease(owner, "token");
                    if (args[0].equals("refused")) {
                        LatentRuntimeActivation.denySettle = true;
                        Throwable error = closing(owner);
                        require(error instanceof IllegalStateException
                            && "activation-runtime-owner-settle-Cancelled".equals(error.getMessage()), "typed-refusal-error");
                        require(lease(owner, "token") == token && LatentRuntimeActivation.owners(kind) == 1,
                            "typed-refusal-dropped-owner");
                        clean();
                        LatentRuntimeActivation.denySettle = false;
                    }
                    int attempts = LatentRuntimeActivation.settlementAttempts;
                    owner.close(); owner.close();
                    require(LatentRuntimeActivation.settlementAttempts == attempts + 1, "settled-owner-retried");
                    require(lease(owner, "token") == null && LatentRuntimeActivation.owners(kind) == 0, "owner-not-settled");
                    clean();
                }
                Activation.finished(Thread.currentThread()); finish();
                require(get("root") == null, "healthy-teardown-retained-root");
            }
            case "lost-before", "lost-after", "error-after", "null" -> {
                var owner = Activation.owner(WAIT);
                Object token = lease(owner, "token");
                Throwable original = null;
                switch (args[0]) {
                    case "lost-before" -> original = LatentRuntimeActivation.settleFailure = new IllegalStateException("before-settle");
                    case "lost-after" -> original = LatentRuntimeActivation.settleAcknowledgementFailure = new IllegalStateException("lost-settle-ack");
                    case "error-after" -> original = LatentRuntimeActivation.settleAcknowledgementError = new OutOfMemoryError("lost-settle-ack");
                    case "null" -> LatentRuntimeActivation.nullSettlement = true;
                }
                Throwable error = closing(owner);
                require(original == null ? error instanceof NullPointerException : error == original, "settlement-primary-error");
                require(LatentRuntimeActivation.owners(WAIT) == (args[0].equals("lost-before") ? 1 : 0), "host-outcome");
                retained(owner, token, 1);
            }
            case "reentry", "post-ack-reentry" -> {
                var owner = Activation.owner(WAIT);
                Object token = lease(owner, "token");
                Runnable observation = observe(() -> {
                    try { finish(); throw new AssertionError("inflight-completion-accepted"); }
                    catch (IllegalStateException expected) { }
                    require(get("settlingOwners") == owner && lease(owner, "token") == token,
                        "inflight-original-owner-not-rooted");
                    require((int)get("pendingOwnerSettlements") == 1, "inflight-owner-not-counted");
                    require(get("root") == root, "inflight-teardown-dropped-work");
                });
                if (args[0].equals("reentry")) LatentRuntimeActivation.settleObservation = observation;
                else LatentRuntimeActivation.settledObservation = observation;
                owner.close(); // A definite acknowledgement can finish cleanup, but cannot clear poison.
                require(lease(owner, "token") == null && get("settlingOwners") == null
                    && (int)get("pendingOwnerSettlements") == 0, "acknowledged-cleanup-not-complete");
                fenced();
            }
            case "duplicate", "duplicate-throws" -> {
                var owner = Activation.owner(WAIT);
                Object token = lease(owner, "token");
                var nested = new AtomicReference<Throwable>();
                LatentRuntimeActivation.settleObservation = () -> {
                    nested.set(closing(owner));
                    if (args[0].equals("duplicate-throws")) throw (RuntimeException)nested.get();
                };
                int attempts = LatentRuntimeActivation.settlementAttempts;
                Throwable outer = closing(owner);
                require(nested.get() instanceof IllegalStateException, "duplicate-settlement-accepted");
                require(LatentRuntimeActivation.settlementAttempts == attempts + 1, "duplicate-host-settlement");
                if (args[0].equals("duplicate-throws")) {
                    require(outer == nested.get(), "duplicate-primary-error");
                    retained(owner, token, 1);
                } else {
                    require(outer == null && lease(owner, "token") == null, "confirmed-cleanup-refused");
                    fenced();
                }
            }
            case "capacity", "teardown" -> {
                var owner = Activation.owner(WAIT);
                Object token = lease(owner, "token");
                int pending = args[0].equals("capacity") ? Integer.MAX_VALUE : 0;
                if (pending != 0) set("pendingOwnerSettlements", pending);
                else set("finishingInvocation", true);
                int attempts = LatentRuntimeActivation.settlementAttempts;
                Throwable error = closing(owner);
                require(error instanceof IllegalStateException
                    && ("activation-runtime-owner-settle-" + args[0]).equals(error.getMessage()), "prehost-error");
                require(attempts == LatentRuntimeActivation.settlementAttempts && LatentRuntimeActivation.owners(WAIT) == 1,
                    "prehost-refusal-dispatched");
                retained(owner, token, pending);
            }
            case "nested" -> {
                var first = Activation.owner(WAIT);
                var second = Activation.owner(WAIT);
                LatentRuntimeActivation.settleObservation = observe(() -> {
                    require(get("settlingOwners") == first, "outer-settlement-not-rooted");
                    LatentRuntimeActivation.settleObservation = observe(() -> {
                        require(get("settlingOwners") == second && lease(second, "nextSettling") == first
                            && (int)get("pendingOwnerSettlements") == 2, "nested-settlements-not-rooted");
                    });
                    second.close();
                    require(get("settlingOwners") == first && lease(first, "previousSettling") == null
                        && (int)get("pendingOwnerSettlements") == 1, "nested-unlink-damaged-outer");
                });
                first.close(); clean();
                require(LatentRuntimeActivation.owners(WAIT) == 0, "nested-host-owners-not-settled");
            }
            case "out-of-order" -> {
                var first = Activation.owner(WAIT);
                var second = Activation.owner(WAIT);
                var entered = new CountDownLatch(1);
                var release = new CountDownLatch(1);
                var firstResult = new AtomicReference<Throwable>();
                LatentRuntimeActivation.settleObservation = observe(() -> {
                    entered.countDown();
                    require(release.await(5, TimeUnit.SECONDS), "first-settlement-release-timeout");
                });
                // JVM threads only arrange ordered host-return observations.
                // They do not model simultaneous execution of guest fibers.
                Thread thread = new Thread(() -> firstResult.set(closing(first)));
                thread.start();
                try {
                    require(entered.await(5, TimeUnit.SECONDS), "first-settlement-entry-timeout");
                    LatentRuntimeActivation.settleObservation = observe(() -> {
                        require(get("settlingOwners") == second && lease(second, "nextSettling") == first,
                            "second-settlement-not-rooted");
                        release.countDown(); thread.join(5000);
                        require(!thread.isAlive() && firstResult.get() == null, "first-settlement-not-complete");
                        require(get("settlingOwners") == second && lease(second, "nextSettling") == null
                            && lease(second, "previousSettling") == null && (int)get("pendingOwnerSettlements") == 1,
                            "nonhead-unlink-damaged-second");
                    });
                    second.close(); clean();
                    require(LatentRuntimeActivation.owners(WAIT) == 0, "out-of-order-host-owners");
                } finally { release.countDown(); thread.join(5000); }
            }
            case "refused-reentry" -> {
                var owner = Activation.owner(WAIT);
                Object token = lease(owner, "token");
                LatentRuntimeActivation.denySettle = true;
                LatentRuntimeActivation.settleObservation = observe(() -> {
                    try { finish(); throw new AssertionError("inflight-refusal-completion-accepted"); }
                    catch (IllegalStateException expected) { }
                });
                Throwable error = closing(owner);
                require(error instanceof IllegalStateException
                    && "activation-runtime-owner-settle-Cancelled".equals(error.getMessage()), "inflight-refusal-error");
                require(LatentRuntimeActivation.owners(WAIT) == 1 && get("settlingOwners") == null,
                    "inflight-refusal-host-or-local-state");
                LatentRuntimeActivation.denySettle = false;
                retained(owner, token, 0);
            }
            case "retention" -> {
                Activation.Lease[] owners = { Activation.owner(WAIT), Activation.owner(WAIT), Activation.owner(WAIT) };
                for (var owner : owners) Activation.fenceUncertainQueuedWorkSettlement(owner);
                for (int i : new int[] { 1, 2, 0, 1 }) Activation.fenceUncertainQueuedWorkSettlement(owners[i]);
                var failed = (AtomicReference<Activation.Lease>)get("failedQueuedOwners");
                var seen = new IdentityHashMap<Activation.Lease, Boolean>();
                for (var current = failed.get(); current != null; current = (Activation.Lease)lease(current, "nextFailedQueued")) {
                    require(seen.put(current, true) == null, "failed-owner-cycle");
                }
                require(seen.size() == owners.length, "failed-owner-lost");
                int attempts = LatentRuntimeActivation.settlementAttempts;
                for (var owner : owners) require(closing(owner) instanceof IllegalStateException, "retained-owner-retried");
                require(attempts == LatentRuntimeActivation.settlementAttempts, "retained-owner-retried-host");
                fenced();
            }
            case "try-resources" -> {
                var original = new IllegalStateException("lost-wait-settle-ack");
                LatentRuntimeActivation.settleAcknowledgementFailure = original;
                try { Monitors.ownedSleep(0); throw new AssertionError("raw-hook-ran"); }
                catch (IllegalStateException error) {
                    require("activation-sleep-compiler-hook-required".equals(error.getMessage()), "raw-hook-primary");
                    require(error.getSuppressed().length == 1 && error.getSuppressed()[0] == original, "cleanup-suppressed-error");
                }
                require(LatentRuntimeActivation.owners(WAIT) == 0, "host-wait-not-settled");
                require((boolean)get("poisoned"), "discarded-wait-frame-not-fenced");
                var owner = (Activation.Lease)get("settlingOwners");
                require(owner != null, "discarded-wait-frame-lost-owner");
                retained(owner, lease(owner, "token"), 1);
            }
            default -> throw new IllegalArgumentException(args[0]);
        }
        System.out.println("OWNER_SETTLEMENT_SOURCE PASS " + args[0]);
    }
}
