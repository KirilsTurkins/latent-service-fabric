import dev.latent.generated.Bindings;
import dev.latent.guest.Option;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.Monitors;
import java.lang.reflect.Field;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

/** Production Java source with a private host ledger; not a guest execution. */
public final class TimerSleepAdmissionSourceControl {
    private static void require(boolean ok, String detail) {
        if (!ok) throw new AssertionError(detail);
    }
    private static Field field(Class<?> type, String name) throws Exception {
        var field = type.getDeclaredField(name); field.setAccessible(true); return field;
    }
    private static Object staticField(String name) throws Exception {
        return field(Activation.class, name).get(null);
    }
    private static void setStatic(String name, Object value) throws Exception {
        field(Activation.class, name).set(null, value);
    }
    @SuppressWarnings("unchecked")
    private static Object installWork(Thread thread) throws Exception {
        var token = Bindings.LatentRuntimeActivation.register(
            Bindings.LatentRuntimeActivationOwnerKind.Task, Option.none()).value();
        var type = Class.forName("dev.latent.guest.runtime.Activation$Work");
        var constructor = type.getDeclaredConstructor(Bindings.LatentRuntimeActivationToken.class);
        constructor.setAccessible(true);
        Object work = constructor.newInstance(token);
        ((Map<Thread, Object>)staticField("threads")).put(thread, work);
        return work;
    }
    private static Activation.Lease syntheticOtherTimer() throws Exception {
        var lease = new AtomicReference<Activation.Lease>();
        var failure = new AtomicReference<Throwable>();
        Thread thread = new Thread(() -> {
            try { lease.set(Activation.timer(Activation.monotonicMillis() + 60_000)); }
            catch (Throwable error) { failure.set(error); }
        }, "source-ledger-timer");
        // These synthetic Work entries deliberately outlive the host threads;
        // they model distinct owners, not actual TeaVM worker retirement.
        installWork(thread); thread.start(); thread.join();
        if (failure.get() != null) throw new AssertionError("synthetic-timer", failure.get());
        return lease.get();
    }
    private static long waitOwners() throws Exception {
        Map<?, ?> owners = (Map<?, ?>)field(Bindings.LatentRuntimeActivation.class, "owners").get(null);
        return owners.values().stream().filter(kind -> kind == Bindings.LatentRuntimeActivationOwnerKind.Wait).count();
    }
    public static void main(String[] args) throws Exception {
        setStatic("entered", true);
        Object root = installWork(Thread.currentThread());
        setStatic("root", root);
        Activation.Lease first = syntheticOtherTimer(), second = syntheticOtherTimer();
        require(Bindings.LatentRuntimeActivation.timers() == 2 && waitOwners() == 0, "initial-owners");
        try {
            Monitors.ownedSleep(0);
            throw new AssertionError("zero-source-hook-unexpectedly-ran");
        } catch (IllegalStateException error) {
            require("activation-sleep-compiler-hook-required".equals(error.getMessage()), "zero-reaches-raw-hook");
        }
        require(Bindings.LatentRuntimeActivation.timers() == 2 && waitOwners() == 0, "zero-keeps-other-timers");
        Thread.currentThread().interrupt();
        try {
            Monitors.ownedSleep(0);
            throw new AssertionError("interrupted-zero-succeeded");
        } catch (InterruptedException expected) {
            require(!Thread.currentThread().isInterrupted(), "zero-interrupt-cleared");
        }
        require(Bindings.LatentRuntimeActivation.timers() == 2 && waitOwners() == 0, "interrupted-zero-owners");
        try {
            Monitors.ownedSleep(1);
            throw new AssertionError("third-timer-was-admitted");
        } catch (IllegalStateException error) {
            require("activation-runtime-timer-start-ResourceExhausted".equals(error.getMessage()), "typed-refusal");
        }
        require(Bindings.LatentRuntimeActivation.timers() == 2 && waitOwners() == 0, "refusal-returns-wait");
        require(field(root.getClass(), "timer").get(root) == null, "refusal-restores-work-slot");
        first.close();
        try {
            Monitors.ownedSleep(1);
            throw new AssertionError("source-hook-unexpectedly-ran");
        } catch (IllegalStateException error) {
            require("activation-sleep-compiler-hook-required".equals(error.getMessage()), "retry-reached-raw-hook");
        }
        require(Bindings.LatentRuntimeActivation.timers() == 1 && waitOwners() == 0, "retry-finally-returns-owners");
        require(field(root.getClass(), "timer").get(root) == null, "retry-restores-work-slot");
        second.close();
        require(Bindings.LatentRuntimeActivation.timers() == 0 && waitOwners() == 0, "final-owners");
        long deadline = Activation.monotonicMillis() + 60_000;
        try (Activation.Lease outer = Activation.timer(deadline)) {
            Activation.beginTimedFrame(outer);
            try {
                require(Monitors.absoluteSleepDeadline(123, 0) == 123, "zero-ignores-outer-timer-frame");
                require(Monitors.absoluteWaitDeadline(123, 0, 0) == deadline, "indefinite-wait-helper-unchanged");
            }
            finally { Activation.endTimedFrame(outer); }
        }
        System.out.println("TIMER_SLEEP_ADMISSION_SOURCE PASS zero-raw-frame;zero-interrupt;typed-refusal;wait-return;same-work-retry;raw-hook-finally");
    }
}
