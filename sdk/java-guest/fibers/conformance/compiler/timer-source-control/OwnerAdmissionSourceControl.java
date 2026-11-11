import dev.latent.generated.Bindings;
import dev.latent.guest.Option;
import dev.latent.guest.runtime.Activation;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Executor;
import java.util.concurrent.atomic.AtomicReference;

/** Actual Java admission code with a private, fault-injecting host ledger. */
public final class OwnerAdmissionSourceControl {
    private static final Bindings.LatentRuntimeActivationOwnerKind WAIT =
        Bindings.LatentRuntimeActivationOwnerKind.Wait;

    private static final Bindings.LatentRuntimeActivationOwnerKind WORKER =
        Bindings.LatentRuntimeActivationOwnerKind.ManagedIdleWorker;
    private static final Activation.ManagedPool POOL = new Activation.ManagedPool() {
        public boolean hasPendingWork() { return false; }
        public boolean isRetired() { return false; }
        public void closeAtRoot() { throw new AssertionError("source-control-no-pool-retirement"); }
    };
    private static final Executor EXECUTOR = command -> { throw new AssertionError("source-control-no-execution"); };
    private static Thread preparedThread;
    private static Object preparedWork;
    private static Bindings.LatentRuntimeActivationToken preparedToken;

    private static Field field(Class<?> type, String name) throws Exception {
        Field result = type.getDeclaredField(name);
        result.setAccessible(true);
        return result;
    }
    private static Object get(String name) throws Exception { return field(Activation.class, name).get(null); }
    private static void set(String name, Object value) throws Exception { field(Activation.class, name).set(null, value); }
    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    private static void finish() throws Exception {
        var method = Activation.class.getDeclaredMethod("finishInvocation", boolean.class);
        method.setAccessible(true);
        try { method.invoke(null, true); }
        catch (InvocationTargetException error) {
            if (error.getCause() instanceof Exception cause) throw cause;
            if (error.getCause() instanceof Error cause) throw cause;
            throw error;
        }
    }
    private static void rejected(Runnable action, String message, String label) {
        try { action.run(); throw new AssertionError(label + "-allowed"); }
        catch (IllegalStateException error) { require(message.equals(error.getMessage()), label + "-error"); }
    }
    private static void fenced() throws Exception {
        require((boolean)get("poisoned"), "uncertain-admission-not-fenced");
        int attempts = Bindings.LatentRuntimeActivation.registrationAttempts;
        int poolCount = ((List<?>)get("pools")).size();
        Object root = get("root");
        String message = "activation-runtime-poisoned-store";
        rejected(() -> Activation.owner(WAIT), message, "later-admission");
        rejected(() -> Activation.starting(preparedThread), message, "prepared-worker-start");
        rejected(() -> Activation.starting(new Thread()), message, "new-worker-start");
        rejected(() -> Activation.manage(POOL), message, "later-pool");
        rejected(() -> Activation.defaultAsyncExecutor(() -> {
            throw new AssertionError("later-default-factory-called");
        }), message, "cached-default-executor");
        rejected(() -> Activation.invoke(0, null, 0), message, "store-reentry");
        require(attempts == Bindings.LatentRuntimeActivation.registrationAttempts, "later-host-registration");
        require((boolean)field(preparedWork.getClass(), "prepared").get(preparedWork), "prepared-worker-consumed");
        require(field(preparedWork.getClass(), "token").get(preparedWork) == preparedToken, "prepared-token-lost");
        require(((List<?>)get("pools")).size() == poolCount, "later-pool-published");
        require(get("defaultAsyncExecutor") == EXECUTOR, "cached-default-executor-changed");
        try { finish(); throw new AssertionError("uncertain-completion-allowed"); }
        catch (IllegalStateException expected) { }
        require(get("root") == root && ((Map<?, ?>)get("threads")).get(preparedThread) == preparedWork,
            "fenced-work-custody-lost");
        require(Bindings.LatentRuntimeActivation.owners(WORKER) == 1, "prepared-host-owner-lost");
        require(((List<?>)get("pools")).size() == poolCount && get("defaultAsyncExecutor") == EXECUTOR,
            "fenced-pool-custody-lost");
    }
    private static void finishHealthy() throws Exception {
        int attempts = Bindings.LatentRuntimeActivation.registrationAttempts;
        // Exercise the maintained start hook without starting a JVM thread or
        // pretending that this private ledger executes a TeaVM continuation.
        Activation.starting(preparedThread);
        require(!(boolean)field(preparedWork.getClass(), "prepared").get(preparedWork), "preparation-not-consumed");
        require(Activation.runningManaged(preparedThread, POOL), "prepared-worker-not-running");
        require(attempts == Bindings.LatentRuntimeActivation.registrationAttempts, "prepared-worker-reregistered");
        require(Activation.defaultAsyncExecutor(() -> {
            throw new AssertionError("cached-default-factory-called");
        }) == EXECUTOR, "healthy-default-executor-not-cached");
        Activation.finished(preparedThread);
        Activation.finished(Thread.currentThread());
        require(Bindings.LatentRuntimeActivation.owners(WORKER) == 0, "healthy-worker-not-settled");
        finish();
        require(!(boolean)get("poisoned") && get("root") == null && get("defaultAsyncExecutor") == null,
            "healthy-teardown-fenced-or-retained");
    }
    @SuppressWarnings("unchecked")
    public static void main(String[] args) throws Exception {
        var rootToken = Bindings.LatentRuntimeActivation.register(
            Bindings.LatentRuntimeActivationOwnerKind.Task, Option.none()).value();
        Class<?> work = Class.forName("dev.latent.guest.runtime.Activation$Work");
        var constructor = work.getDeclaredConstructor(Bindings.LatentRuntimeActivationToken.class);
        constructor.setAccessible(true);
        Object root = constructor.newInstance(rootToken);
        ((Map<Thread, Object>)get("threads")).put(Thread.currentThread(), root);
        set("root", root); set("entered", true);
        Activation.manage(POOL);
        require(Activation.defaultAsyncExecutor(() -> EXECUTOR) == EXECUTOR, "default-executor-not-created");
        // Reproduce startManaged's admitted-but-not-yet-started local custody.
        // Reflection constructs the fixture only; admission gates run unchanged.
        preparedThread = new Thread("source-control-prepared-worker");
        preparedToken = Bindings.LatentRuntimeActivation.register(WORKER, Option.some(rootToken)).value();
        preparedWork = constructor.newInstance(preparedToken);
        field(work, "prepared").set(preparedWork, true);
        field(work, "managed").set(preparedWork, true);
        field(work, "pool").set(preparedWork, POOL);
        ((Map<Thread, Object>)get("threads")).put(preparedThread, preparedWork);
        switch (args[0]) {
            case "normal", "refused" -> {
                if (args[0].equals("refused")) {
                    Bindings.LatentRuntimeActivation.denyRegistration = true;
                    try { Activation.owner(WAIT); throw new AssertionError("refusal-missing"); }
                    catch (IllegalStateException expected) {
                        require("activation-runtime-register-ResourceExhausted".equals(expected.getMessage()), "refusal-error");
                    }
                    require(!(boolean)get("poisoned") && Bindings.LatentRuntimeActivation.owners(WAIT) == 0, "typed-refusal-poisoned");
                    require((int)get("pendingRegistrations") == 0, "typed-refusal-still-pending");
                    Bindings.LatentRuntimeActivation.denyRegistration = false;
                }
                var lease = Activation.owner(WAIT);
                require(Bindings.LatentRuntimeActivation.owners(WAIT) == 1, "owner-not-admitted");
                lease.close();
                require(Bindings.LatentRuntimeActivation.owners(WAIT) == 0 && (int)get("pendingRegistrations") == 0,
                    "normal-owner-not-settled");
                finishHealthy();
            }
            case "lost" -> {
                var original = new IllegalStateException("lost-registration-ack");
                Bindings.LatentRuntimeActivation.registrationFailure = original;
                try { Activation.owner(WAIT); throw new AssertionError("lost-ack-missing"); }
                catch (IllegalStateException actual) { require(actual == original, "lost-ack-primary"); }
                require(Bindings.LatentRuntimeActivation.owners(WAIT) == 1, "host-owner-not-retained");
                fenced();
                require((int)get("pendingRegistrations") == 1, "uncertain-registration-not-pending");
            }
            case "null" -> {
                Bindings.LatentRuntimeActivation.nullRegistration = true;
                try { Activation.owner(WAIT); throw new AssertionError("missing-token-accepted"); }
                catch (IllegalStateException actual) {
                    require("activation-runtime-register-token".equals(actual.getMessage()), "missing-token-error");
                }
                require(Bindings.LatentRuntimeActivation.owners(WAIT) == 1, "missing-token-host-owner-not-retained");
                fenced();
            }
            case "reentry" -> {
                var nested = new AtomicReference<Throwable>();
                Bindings.LatentRuntimeActivation.registrationObservation = () -> {
                    try { finish(); } catch (Throwable error) { nested.set(error); }
                };
                try { Activation.owner(WAIT); throw new AssertionError("admission-after-finish"); }
                catch (IllegalStateException expected) { }
                require(nested.get() instanceof IllegalStateException, "inflight-completion-not-refused");
                require(Bindings.LatentRuntimeActivation.owners(WAIT) == 1, "inflight-host-owner-not-retained");
                fenced();
                require((int)get("pendingRegistrations") == 1 && get("root") == root, "inflight-root-not-retained");
            }
            case "capacity" -> {
                set("pendingRegistrations", Integer.MAX_VALUE);
                int attempts = Bindings.LatentRuntimeActivation.registrationAttempts;
                try { Activation.owner(WAIT); throw new AssertionError("overflow-admission-allowed"); }
                catch (IllegalStateException actual) {
                    require("activation-runtime-register-capacity".equals(actual.getMessage()), "overflow-error");
                }
                require(attempts == Bindings.LatentRuntimeActivation.registrationAttempts, "overflow-host-call");
                fenced();
            }
            default -> throw new IllegalArgumentException(args[0]);
        }
        System.out.println("OWNER_ADMISSION_SOURCE PASS " + args[0]);
    }
}
