import dev.latent.generated.Bindings;
import dev.latent.guest.Option;
import dev.latent.guest.runtime.Activation;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

/** Actual Java admission code with a private, fault-injecting host ledger. */
public final class OwnerAdmissionSourceControl {
    private static final Bindings.LatentRuntimeActivationOwnerKind WAIT =
        Bindings.LatentRuntimeActivationOwnerKind.Wait;

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
    private static void fenced() throws Exception {
        require((boolean)get("poisoned"), "uncertain-admission-not-fenced");
        int attempts = Bindings.LatentRuntimeActivation.registrationAttempts;
        try { Activation.owner(WAIT); throw new AssertionError("later-admission-allowed"); }
        catch (IllegalStateException expected) {
            require("activation-runtime-poisoned-store".equals(expected.getMessage()), "later-admission-error");
        }
        require(attempts == Bindings.LatentRuntimeActivation.registrationAttempts, "later-host-registration");
        try { finish(); throw new AssertionError("uncertain-completion-allowed"); }
        catch (IllegalStateException expected) { }
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
        switch (args[0]) {
            case "normal", "refused" -> {
                if (args[0].equals("refused")) {
                    Bindings.LatentRuntimeActivation.denyRegistration = true;
                    try { Activation.owner(WAIT); throw new AssertionError("refusal-missing"); }
                    catch (IllegalStateException expected) {
                        require("activation-runtime-register-ResourceExhausted".equals(expected.getMessage()), "refusal-error");
                    }
                    require(!(boolean)get("poisoned") && Bindings.LatentRuntimeActivation.owners(WAIT) == 0, "typed-refusal-poisoned");
                    Bindings.LatentRuntimeActivation.denyRegistration = false;
                }
                var lease = Activation.owner(WAIT);
                require(Bindings.LatentRuntimeActivation.owners(WAIT) == 1, "owner-not-admitted");
                lease.close();
                require(Bindings.LatentRuntimeActivation.owners(WAIT) == 0 && (int)get("pendingRegistrations") == 0,
                    "normal-owner-not-settled");
                finish();
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
