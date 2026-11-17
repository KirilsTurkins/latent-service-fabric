import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.util.Timer;
import dev.latent.guest.runtime.util.TimerCleanupFailureHooks;
import dev.latent.guest.runtime.util.TimerTask;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Source projection: a monitor failure replaces an in-flight user exception. */
public final class TimerCleanupFailureControl {
    public static void main(String[] args) throws Exception {
        var failure = new AtomicReference<Throwable>();
        var boundary = new CountDownLatch(1);
        var calls = new AtomicInteger();
        var previous = Thread.getDefaultUncaughtExceptionHandler();
        Thread.setDefaultUncaughtExceptionHandler((thread, error) -> {
            failure.set(error); boundary.countDown();
        });
        Timer timer = new Timer("callback-finally-failure", true);
        try {
            timer.schedule(new TimerTask() { @Override public void run() {
                calls.incrementAndGet();
                throw new IllegalArgumentException("user-callback");
            } }, 0);
            if (!boundary.await(5, TimeUnit.SECONDS)) throw new AssertionError("worker-failure-timeout");
            Activation.joinWorkers();
            if (failure.get() != TimerCleanupFailureHooks.REPLACEMENT || calls.get() != 1)
                throw new AssertionError("replacement-failure-not-preserved");
            if (!TimerCleanupFailureHooks.fencedBeforeCleanup || !Activation.poisoned())
                throw new AssertionError("replacement-failure-not-fenced-before-cleanup");
            if (Activation.queued() != 1 || Activation.executors() != 1)
                throw new AssertionError("uncertain-original-owners-not-retained");
            System.out.println("TIMER_CLEANUP_FAILURE_SOURCE PASS exact-replacement;fenced-before-cleanup;owners-retained");
        } finally {
            timer.cancel();
            Thread.setDefaultUncaughtExceptionHandler(previous);
        }
    }
}
