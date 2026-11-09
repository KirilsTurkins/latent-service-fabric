import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.FutureTask;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/** Private Result ledger and JVM barriers, not a physical host retirement test. */
public final class FutureTaskNullFailureOwnerControl {
    private static final class Task extends FutureTask<Integer> {
        final AtomicInteger completions = new AtomicInteger();
        Task(CountDownLatch entered, CountDownLatch release) {
            super(() -> { entered.countDown(); release.await(); return 42; });
        }
        void failNull() { setException(null); }
        @Override protected void done() { completions.incrementAndGet(); }
    }
    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    public static void main(String[] args) throws Exception {
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        Task task = new Task(entered, release);
        Thread runner = new Thread(task, "future-null-running-owner");
        try {
            runner.start();
            require(entered.await(5, TimeUnit.SECONDS), "runner did not enter");
            require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == 1, "missing original Result");
            task.failNull();
            require(task.state() == Future.State.FAILED && task.completions.get() == 1, "not failed once");
            try { task.get(); throw new AssertionError("missing execution error"); }
            catch (ExecutionException expected) { require(expected.getCause() == null, "wrong cause"); }
            require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == 1, "Result retired while runner live");
        } finally {
            release.countDown();
            runner.join(5000);
            require(!runner.isAlive(), "runner did not retire");
        }
        require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == 0, "Result did not retire");
        require(task.state() == Future.State.FAILED && task.completions.get() == 1, "runner overwrote failure");
        Activation.idle();
        System.out.println("FUTURE_TASK_NULL_FAILURE_OWNER PASS original-result-held-until-runner-exit");
    }
}
