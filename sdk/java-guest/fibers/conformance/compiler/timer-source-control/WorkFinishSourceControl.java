import dev.latent.generated.Bindings;
import dev.latent.generated.Bindings.LatentRuntimeActivation;
import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.Option;
import dev.latent.guest.runtime.Activation;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Actual Work retirement with a private ledger, not a component or scheduler witness. */
public final class WorkFinishSourceControl {
    private static Object root, work;
    private static Thread target;
    private static boolean rootSettlement;
    private static Pool pool;
    private static final class Pool implements Activation.ManagedPool {
        Runnable observation;
        public boolean hasPendingWork() { return false; }
        public boolean isRetired() { if (observation != null) observation.run(); return true; }
        public void closeAtRoot() { throw new AssertionError("source-control-no-pool-pump"); }
    }
    private interface Action { void run() throws Exception; }
    private static Field field(Class<?> type, String name) throws Exception {
        var result = type.getDeclaredField(name); result.setAccessible(true); return result;
    }
    private static Object get(String name) throws Exception { return field(Activation.class, name).get(null); }
    private static void set(String name, Object value) throws Exception { field(Activation.class, name).set(null, value); }
    private static Object state(Object owner, String name) throws Exception { return field(owner.getClass(), name).get(owner); }
    private static void need(boolean value, String message) { if (!value) throw new AssertionError(message); }
    private static void invoke(java.lang.reflect.Method method, Object... arguments) throws Exception {
        method.setAccessible(true);
        try { method.invoke(null, arguments); }
        catch (InvocationTargetException error) {
            if (error.getCause() instanceof Exception cause) throw cause;
            if (error.getCause() instanceof Error cause) throw cause;
            throw error;
        }
    }
    private static void finish() throws Exception {
        invoke(Activation.class.getDeclaredMethod("finishInvocation", boolean.class), true);
    }
    private static void retire() throws Exception {
        if (rootSettlement) invoke(Activation.class.getDeclaredMethod("finishWork", Thread.class, work.getClass(), boolean.class),
            null, work, true);
        else Activation.finished(target);
    }
    private static Throwable thrown(Action action) {
        try { action.run(); return null; } catch (Throwable error) { return error; }
    }
    private static Runnable observe(Action action) {
        return () -> {
            try { action.run(); } catch (Exception error) { throw new AssertionError("source-observation", error); }
        };
    }
    private static boolean hostOwns(Object token) throws Exception {
        return ((Map<?, ?>)field(LatentRuntimeActivation.class, "owners").get(null)).containsKey(token);
    }
    private static void clean() throws Exception {
        need(!(boolean)get("poisoned"), "healthy-retirement-poisoned");
        need((int)get("pendingWorkFinishes") == 0 && get("finishingWorks") == null, "work-still-pending");
    }
    private static void fenced() throws Exception {
        need((boolean)get("poisoned"), "uncertain-work-not-fenced");
        need(thrown(WorkFinishSourceControl::finish) instanceof IllegalStateException, "uncertain-completion-accepted");
        var threads = (Map<?, ?>)get("threads");
        need(get("root") == root && threads.get(Thread.currentThread()) == root && threads.get(target) == work,
            "teardown-dropped-original-work");
        int attempts = LatentRuntimeActivation.registrationAttempts;
        need(thrown(() -> Activation.owner(LatentRuntimeActivationOwnerKind.Wait)) instanceof IllegalStateException,
            "later-owner-admitted");
        need(attempts == LatentRuntimeActivation.registrationAttempts, "later-host-registration");
    }
    private static void inflightTeardown() throws Exception {
        // Check the behavioral fence before inspecting new bookkeeping fields:
        // the old source actually clears the records and accepts completion here.
        need(thrown(WorkFinishSourceControl::finish) instanceof IllegalStateException, "inflight-completion-accepted");
        need(get("root") == root && ((Map<?, ?>)get("threads")).get(target) == work, "inflight-work-discarded");
        need(get("finishingWorks") == work && (int)get("pendingWorkFinishes") == 1
            && (boolean)state(work, "finishPending"), "inflight-work-not-counted");
    }
    private static void noRetry() throws Exception {
        LatentRuntimeActivation.settleFailure = LatentRuntimeActivation.settleAcknowledgementFailure = null;
        LatentRuntimeActivation.settleAcknowledgementError = null;
        LatentRuntimeActivation.nullSettlement = LatentRuntimeActivation.denySettle = false;
        int attempts = LatentRuntimeActivation.settlementAttempts;
        need(thrown(WorkFinishSourceControl::retire) instanceof IllegalStateException, "uncertain-work-retry-accepted");
        need(attempts == LatentRuntimeActivation.settlementAttempts, "uncertain-work-retried-host");
    }
    private static void retained(Object token) throws Exception {
        need((boolean)get("poisoned"), "uncertain-work-not-fenced");
        need(state(work, "token") == token && !(boolean)state(work, "complete"), "uncertain-token-discarded");
        need((boolean)state(work, "finishPending") && (int)get("pendingWorkFinishes") == 1
            && get("finishingWorks") == work, "uncertain-work-not-rooted");
        noRetry(); fenced();
    }
    @SuppressWarnings("unchecked")
    public static void main(String[] args) throws Exception {
        need(args.length == 2, "usage: kind mode");
        String kind = args[0], mode = args[1];
        var rootToken = LatentRuntimeActivation.register(LatentRuntimeActivationOwnerKind.Task, Option.none()).value();
        var type = Class.forName("dev.latent.guest.runtime.Activation$Work");
        var constructor = type.getDeclaredConstructor(Bindings.LatentRuntimeActivationToken.class);
        constructor.setAccessible(true); root = constructor.newInstance(rootToken);
        var threads = (Map<Thread, Object>)get("threads");
        threads.put(Thread.currentThread(), root); set("root", root); set("entered", true);
        rootSettlement = kind.equals("root");
        if (rootSettlement) {
            target = Thread.currentThread(); work = root;
            set("rootComplete", true); set("finishingInvocation", true);
        } else if (kind.equals("task")) {
            target = new Thread("source-task"); Activation.starting(target); work = threads.get(target);
        } else if (kind.equals("managed")) {
            pool = new Pool(); Activation.manage(pool);
            // Consume the real preparation hook without allocating a JVM worker
            // or claiming this private source control runs a TeaVM continuation.
            target = new Thread("source-managed") { @Override public void start() { Activation.starting(this); } };
            Activation.startManaged(target, pool); work = threads.get(target);
        } else throw new IllegalArgumentException(kind);
        Object token = state(work, "token");
        String refusalMessage = rootSettlement ? "activation-runtime-root-settle-Cancelled" : "activation-runtime-settle-Cancelled";
        switch (mode) {
            case "normal", "refused" -> {
                if (mode.equals("refused")) {
                    LatentRuntimeActivation.denySettle = true;
                    Throwable error = thrown(WorkFinishSourceControl::retire);
                    need(error instanceof IllegalStateException && refusalMessage.equals(error.getMessage()), "refusal-shape");
                    need(hostOwns(token) && state(work, "token") == token && !(boolean)state(work, "complete"), "refusal-lost-owner");
                    need((boolean)state(work, "finishing") && (boolean)state(work, "finishRefused"), "refusal-reopened-work");
                    clean(); LatentRuntimeActivation.denySettle = false;
                }
                retire(); clean();
                need(state(work, "token") == null && (boolean)state(work, "complete") && !hostOwns(token), "work-not-settled");
                int attempts = LatentRuntimeActivation.settlementAttempts;
                need(thrown(WorkFinishSourceControl::retire) instanceof IllegalStateException, "completed-work-retried");
                need(attempts == LatentRuntimeActivation.settlementAttempts, "completed-work-host-call");
                if (!rootSettlement) Activation.finished(Thread.currentThread());
                finish(); need(get("root") == null && threads.isEmpty(), "healthy-teardown-retains-work");
            }
            case "lost-before", "lost-after", "error-after", "null" -> {
                Throwable original = null;
                switch (mode) {
                    case "lost-before" -> original = LatentRuntimeActivation.settleFailure = new IllegalStateException("lost-work-call");
                    case "lost-after" -> original = LatentRuntimeActivation.settleAcknowledgementFailure = new IllegalStateException("lost-work-ack");
                    case "error-after" -> original = LatentRuntimeActivation.settleAcknowledgementError = new OutOfMemoryError("lost-work-ack");
                    case "null" -> LatentRuntimeActivation.nullSettlement = true;
                }
                Throwable error = thrown(WorkFinishSourceControl::retire);
                need(original == null ? error instanceof NullPointerException : error == original, "work-primary-error");
                need(hostOwns(token) == mode.equals("lost-before"), "host-outcome"); retained(token);
            }
            case "reentry", "post-ack-reentry" -> {
                if (mode.equals("reentry")) LatentRuntimeActivation.settleObservation = observe(WorkFinishSourceControl::inflightTeardown);
                else LatentRuntimeActivation.settledObservation = observe(WorkFinishSourceControl::inflightTeardown);
                retire();
                need(state(work, "token") == null && (boolean)state(work, "complete")
                    && (int)get("pendingWorkFinishes") == 0 && get("finishingWorks") == null, "acknowledged-work-not-cleaned");
                fenced();
            }
            case "duplicate", "duplicate-throws" -> {
                var nested = new AtomicReference<Throwable>();
                LatentRuntimeActivation.settleObservation = () -> {
                    nested.set(thrown(WorkFinishSourceControl::retire));
                    if (mode.equals("duplicate-throws")) throw (RuntimeException)nested.get();
                };
                int attempts = LatentRuntimeActivation.settlementAttempts;
                Throwable outer = thrown(WorkFinishSourceControl::retire);
                need(nested.get() instanceof IllegalStateException && attempts + 1 == LatentRuntimeActivation.settlementAttempts,
                    "duplicate-host-dispatch");
                if (mode.equals("duplicate-throws")) { need(outer == nested.get(), "duplicate-primary-error"); retained(token); }
                else { need(outer == null && state(work, "token") == null, "confirmed-cleanup-refused"); fenced(); }
            }
            case "capacity", "teardown" -> {
                if (mode.equals("capacity")) set("pendingWorkFinishes", Integer.MAX_VALUE);
                else if (rootSettlement) set("entered", false);
                else set("finishingInvocation", true);
                int attempts = LatentRuntimeActivation.settlementAttempts;
                need(thrown(WorkFinishSourceControl::retire) instanceof IllegalStateException, "prehost-refusal-accepted");
                need(attempts == LatentRuntimeActivation.settlementAttempts && hostOwns(token)
                    && state(work, "token") == token, "prehost-refusal-dispatched");
                fenced();
            }
            case "refused-reentry" -> {
                LatentRuntimeActivation.denySettle = true;
                LatentRuntimeActivation.settleObservation = observe(WorkFinishSourceControl::inflightTeardown);
                Throwable error = thrown(WorkFinishSourceControl::retire);
                need(error instanceof IllegalStateException && refusalMessage.equals(error.getMessage()), "refusal-shape");
                need(hostOwns(token) && state(work, "token") == token && (int)get("pendingWorkFinishes") == 0
                    && get("finishingWorks") == null, "confirmed-refusal-state");
                noRetry(); fenced();
            }
            case "cleanup", "cleanup-throws" -> {
                need(pool != null, "cleanup-requires-managed");
                var original = new IllegalStateException("pool-retirement-failed");
                pool.observation = mode.equals("cleanup") ? observe(WorkFinishSourceControl::inflightTeardown) : () -> { throw original; };
                Throwable error = thrown(WorkFinishSourceControl::retire);
                need(mode.equals("cleanup") ? error == null : error == original, "cleanup-primary-error");
                need(state(work, "token") == null && (boolean)state(work, "complete") && !hostOwns(token), "host-not-settled-before-cleanup");
                need((boolean)get("poisoned"), "failed-cleanup-not-fenced");
                need((int)get("pendingWorkFinishes") == (mode.equals("cleanup") ? 0 : 1), "cleanup-count");
                if (mode.equals("cleanup-throws")) noRetry();
                fenced();
            }
            case "nested", "out-of-order" -> {
                need(kind.equals("task"), "interleavings-require-task");
                Thread second = new Thread("source-second"); Activation.starting(second); Object other = threads.get(second);
                if (mode.equals("nested")) {
                    LatentRuntimeActivation.settleObservation = observe(() -> {
                        LatentRuntimeActivation.settleObservation = observe(() -> {
                            need(get("finishingWorks") == other && state(other, "nextFinishing") == work
                                && (int)get("pendingWorkFinishes") == 2, "nested-work-not-counted");
                        });
                        Activation.finished(second);
                        need(get("finishingWorks") == work && state(work, "previousFinishing") == null
                            && (int)get("pendingWorkFinishes") == 1, "nested-unlink-damaged-outer");
                    });
                    retire();
                } else {
                    var entered = new CountDownLatch(1); var release = new CountDownLatch(1);
                    var firstResult = new AtomicReference<Throwable>();
                    LatentRuntimeActivation.settleObservation = observe(() -> {
                        entered.countDown(); need(release.await(5, TimeUnit.SECONDS), "release-timeout");
                    });
                    // Ordered JVM latches arrange host-return interleavings only;
                    // this does not claim native parallel guest execution.
                    Thread runner = new Thread(() -> firstResult.set(thrown(WorkFinishSourceControl::retire)));
                    runner.start();
                    try {
                        need(entered.await(5, TimeUnit.SECONDS), "entry-timeout");
                        LatentRuntimeActivation.settleObservation = observe(() -> {
                            need(get("finishingWorks") == other && state(other, "nextFinishing") == work, "second-not-rooted");
                            release.countDown(); runner.join(5000);
                            need(!runner.isAlive() && firstResult.get() == null, "first-not-finished");
                            need(get("finishingWorks") == other && state(other, "nextFinishing") == null
                                && state(other, "previousFinishing") == null && (int)get("pendingWorkFinishes") == 1, "nonhead-unlink-damaged-second");
                        });
                        Activation.finished(second);
                    } finally { release.countDown(); runner.join(5000); }
                }
                clean(); need((boolean)state(work, "complete") && (boolean)state(other, "complete"), "interleaved-work-not-complete");
            }
            default -> throw new IllegalArgumentException(mode);
        }
        System.out.println("WORK_FINISH_SOURCE PASS " + kind + " " + mode);
    }
}
