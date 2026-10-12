import dev.latent.generated.Bindings;
import dev.latent.guest.Option;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.Monitors;
import java.lang.reflect.Field;
import java.util.Map;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

/** Execute the production timer registry with a private source-only host ledger. */
public final class TimerReadinessSourceControl {
    private static void require(boolean yes, String reason) { if (!yes) throw new AssertionError(reason); }
    private static Field field(Class<?> type, String name) throws ReflectiveOperationException { var field = type.getDeclaredField(name); field.setAccessible(true); return field; }
    private static Object get(String name) throws Exception { return field(Activation.class, name).get(null); }
    private static void set(String name, Object value) throws Exception { field(Activation.class, name).set(null, value); }
    @SuppressWarnings("unchecked")
    private static Object work(Thread thread) throws Exception {
        var token = Bindings.LatentRuntimeActivation.register(Bindings.LatentRuntimeActivationOwnerKind.Task, Option.none()).value();
        var type = Class.forName("dev.latent.guest.runtime.Activation$Work");
        var constructor = type.getDeclaredConstructor(Bindings.LatentRuntimeActivationToken.class); constructor.setAccessible(true);
        var work = constructor.newInstance(token);
        ((Map<Thread, Object>)get("threads")).put(thread, work); return work;
    }
    private static Activation.Lease otherTimer(long deadline) throws Exception {
        var value = new AtomicReference<Activation.Lease>(); var error = new AtomicReference<Throwable>();
        var thread = new Thread(() -> { try { value.set(Activation.timer(deadline)); } catch (Throwable caught) { error.set(caught); } });
        work(thread); thread.start(); thread.join();
        if (error.get() != null) throw new IllegalStateException("source-worker", error.get());
        return value.get();
    }
    private static void pair(long clock) throws Exception { set("queueClock", clock); set("queueClockCaptured", true); }
    private static void denied(Runnable operation) {
        try { operation.run(); throw new AssertionError("expected-source-denial"); }
        catch (IllegalStateException expected) { }
    }
    public static void main(String[] arguments) throws Exception {
        set("entered", true); set("root", work(Thread.currentThread()));
        long deadline = Activation.monotonicMillis() + 200;
        var first = Activation.timer(deadline); var second = otherTimer(deadline);
        require(Bindings.LatentRuntimeActivation.timers() == 2 && ((List<?>)get("timers")).size() == 2, "two-original-timer-reservations");

        require(Monitors.absoluteSleepDeadline(99, 1) == 100, "pure-deadline-outside-raw-frame");
        Activation.beginTimedFrame(first);
        require(Monitors.absoluteSleepDeadline(999, 1) == deadline, "captured-raw-sleep-deadline");
        require(Monitors.absoluteWaitDeadline(999, 0, 1) == deadline, "captured-rounded-raw-wait-deadline");
        try { Monitors.absoluteWaitDeadline(1, 0, 1000000); throw new AssertionError("nanos-validation"); } catch (IllegalArgumentException expected) { }
        try { Monitors.absoluteSleepDeadline(1, -1); throw new AssertionError("millis-validation"); } catch (IllegalArgumentException expected) { }
        Activation.endTimedFrame(first);
        require(Monitors.absoluteWaitDeadline(99, 0, 1) == 100, "pure-rounded-deadline-after-frame");
        denied(() -> Activation.beginTimedFrame(second));

        set("queueClockCaptured", false);
        long captured = Activation.queueMonotonicMillis(); Thread.sleep(5); long fresh = Activation.queueMonotonicMillis();
        require(fresh > captured && ((Long)get("queueClock")) == captured, "millisecond-crossing-retains-first-clock");
        pair(deadline - 50); Activation.waitFor(50);
        require(Bindings.LatentRuntimeActivation.selected.size() == 1 && Bindings.LatentRuntimeActivation.waits == 0, "first-tie-reuses-existing-timer");
        require(Bindings.LatentRuntimeActivation.timers() == 2, "fired-timer-held-through-java-frame");
        Activation.waitFor(50);
        require(Bindings.LatentRuntimeActivation.selected.size() == 2
            && !Bindings.LatentRuntimeActivation.selected.get(0).equals(Bindings.LatentRuntimeActivation.selected.get(1)), "stable-tie-selects-unfired-owner");
        denied(() -> Activation.waitFor(50));
        require(Bindings.LatentRuntimeActivation.selected.size() == 2 && Bindings.LatentRuntimeActivation.waits == 1, "fired-timer-not-awaited-twice");
        first.close();
        Bindings.LatentRuntimeActivation.denyStop = true;
        Bindings.LatentRuntimeActivation.stopObservation = () -> {
            try { require((boolean)field(second.getClass(), "closing").get(second), "closing-before-stop-call"); }
            catch (ReflectiveOperationException error) { throw new IllegalStateException(error); }
            require(Bindings.LatentRuntimeActivation.timers() == 1, "charge-retained-until-stop-confirmation");
        };
        denied(second::close);
        require(((List<?>)get("timers")).size() == 1 && Bindings.LatentRuntimeActivation.timers() == 1, "cancelled-stop-retains-record");
        Bindings.LatentRuntimeActivation.denyStop = false; second.close(); Bindings.LatentRuntimeActivation.stopObservation = null;
        require(Bindings.LatentRuntimeActivation.timers() == 0 && ((List<?>)get("timers")).isEmpty(), "confirmed-stop-retires-both-owners");

        var immediate = Activation.timer(Activation.monotonicMillis() - 1);
        require(Bindings.LatentRuntimeActivation.lastNanos == 0, "already-due-zero-delay"); immediate.close();
        var huge = Activation.timer(Long.MAX_VALUE);
        require(Bindings.LatentRuntimeActivation.lastNanos == Long.MAX_VALUE, "huge-wait-preserves-saturation");
        pair(Long.MAX_VALUE - 1); Bindings.LatentRuntimeActivation.denyNext = true; denied(() -> Activation.waitFor(1));
        require(Bindings.LatentRuntimeActivation.timers() == 1, "cancelled-next-keeps-physical-owner");
        Bindings.LatentRuntimeActivation.denyNext = false; huge.close();
        pair(100); int waits = Bindings.LatentRuntimeActivation.waits; Activation.waitFor(1); Activation.waitFor(-1);
        require(Bindings.LatentRuntimeActivation.waits == waits + 2 && Bindings.LatentRuntimeActivation.timers() == 0, "unmatched-and-indefinite-waits-stay-charged");
        require(Monitors.absoluteSleepDeadline(Long.MAX_VALUE - 1, 2) == Long.MAX_VALUE, "pure-saturation-preserved");
        System.out.println("TIMER_READINESS_SOURCE_CONTROL PASS two-timer-bound;captured-frame-deadline;first-clock-latch;stable-ties;fired-and-closing-exclusion;confirmed-stop;cancelled-ownership;zero-huge-and-fallback");
    }
}
