import dev.latent.generated.Bindings;
import dev.latent.guest.Option;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.util.Timer;
import dev.latent.guest.runtime.util.TimerTask;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/** Actual SDK sources and a private host ledger, with only the wait hook projected. */
public final class TimerWaitAdmissionSourceControl {
    private static void require(boolean value, String reason) {
        if (!value) throw new AssertionError(reason);
    }
    private static Field field(Class<?> type, String name) throws Exception {
        var field = type.getDeclaredField(name); field.setAccessible(true); return field;
    }
    private static void set(String name, Object value) throws Exception {
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
        ((Map<Thread, Object>)field(Activation.class, "threads").get(null)).put(thread, work);
        return work;
    }
    private record Held(Thread thread, Activation.Lease lease) { }
    private static Held occupyTimer() throws Exception {
        var lease = new AtomicReference<Activation.Lease>();
        var failure = new AtomicReference<Throwable>();
        Thread thread = new Thread(() -> {
            try { lease.set(Activation.timer(Activation.monotonicMillis() + 60_000)); }
            catch (Throwable error) { failure.set(error); }
        }, "source-held-timer");
        installWork(thread); thread.start(); thread.join(5000);
        require(!thread.isAlive() && failure.get() == null && lease.get() != null, "hold-timer");
        return new Held(thread, lease.get());
    }
    private static void refuseRootCompletion() throws Exception {
        var check = Activation.class.getDeclaredMethod("requireHealthyCompletion");
        check.setAccessible(true);
        try { check.invoke(null); throw new AssertionError("root-completion-succeeded"); }
        catch (InvocationTargetException error) {
            require(error.getCause() instanceof IllegalStateException
                && "activation-runtime-owner-settlement-uncertain".equals(error.getCause().getMessage()),
                "root-completion-error");
        }
    }
    public static void main(String[] args) throws Exception {
        set("entered", true);
        set("root", installWork(Thread.currentThread()));
        Held first = occupyTimer(), second = occupyTimer();
        require(Bindings.LatentRuntimeActivation.timers() == 2, "original-timer-limit");
        var failed = new AtomicReference<Throwable>();
        var worker = new AtomicReference<Thread>();
        var boundary = new CountDownLatch(1);
        var ran = new AtomicBoolean();
        var previous = Thread.getDefaultUncaughtExceptionHandler();
        Thread.setDefaultUncaughtExceptionHandler((thread, error) -> {
            worker.set(thread); failed.set(error); boundary.countDown();
        });
        Timer timer = new Timer("timer-admission-refusal", true);
        try {
            timer.schedule(new TimerTask() { @Override public void run() { ran.set(true); } }, 60_000);
            require(boundary.await(5, TimeUnit.SECONDS), "worker-failure-timeout");
            worker.get().join(5000);
            require(!worker.get().isAlive(), "worker-not-retired");
            require(failed.get() instanceof IllegalStateException
                && "activation-runtime-timer-start-ResourceExhausted".equals(failed.get().getMessage()),
                "typed-timer-refusal");
            require(!ran.get(), "refused-callback-ran");
            require(Bindings.LatentRuntimeActivation.owners(Bindings.LatentRuntimeActivationOwnerKind.Wait) == 0,
                "wait-not-retired");
            require(Bindings.LatentRuntimeActivation.owners(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork) == 0,
                "queued-not-retired");
            require(Bindings.LatentRuntimeActivation.owners(Bindings.LatentRuntimeActivationOwnerKind.Executor) == 0,
                "executor-not-retired");
            first.lease().close(); second.lease().close();
            Activation.finished(first.thread()); Activation.finished(second.thread());
            Activation.finished(worker.get());
            require(Bindings.LatentRuntimeActivation.timers() == 0, "held-timers-not-retired");
            require(Bindings.LatentRuntimeActivation.owners(Bindings.LatentRuntimeActivationOwnerKind.ManagedIdleWorker) == 0,
                "worker-owner-not-retired");
            refuseRootCompletion();
            System.out.println("TIMER_WAIT_ADMISSION_SOURCE PASS typed-refusal;accepted-callback-not-run;owners-retired;root-refused");
        } finally {
            timer.cancel();
            Thread.setDefaultUncaughtExceptionHandler(previous);
        }
    }
}
