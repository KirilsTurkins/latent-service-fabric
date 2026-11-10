import java.util.concurrent.Callable;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Future;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Identical JDK and source-port controls for a protected FutureTask API. */
public final class FutureTaskNullFailureReferenceControl {
    private static final class Task extends FutureTask<Integer> {
        final AtomicInteger completions = new AtomicInteger();
        Task(Callable<Integer> action) { super(action); }
        void fail(Throwable error) { setException(error); }
        void succeed(Integer value) { set(value); }
        @Override protected void done() { completions.incrementAndGet(); }
    }
    private static void require(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    private static void nullFailure(Task task) throws Exception {
        require(task.isDone() && !task.isCancelled() && task.state() == Future.State.FAILED, "failure state");
        try { task.get(); throw new AssertionError("missing execution error"); }
        catch (ExecutionException expected) { require(expected.getCause() == null, "failure cause"); }
        require(task.exceptionNow() == null, "exceptionNow null cause");
        try { task.resultNow(); throw new AssertionError("failed result"); }
        catch (IllegalStateException expected) { }
        require(task.completions.get() == 1, "completion count");
    }
    private static void pendingAndTerminal() throws Exception {
        Task failed = new Task(() -> 42);
        failed.fail(null);
        nullFailure(failed);
        failed.fail(null);
        nullFailure(failed);

        Task success = new Task(() -> 42);
        success.succeed(null);
        success.fail(null);
        require(success.isDone() && success.state() == Future.State.SUCCESS && success.get() == null
            && success.resultNow() == null && success.completions.get() == 1, "successful null");
        try { success.exceptionNow(); throw new AssertionError("successful exception"); }
        catch (IllegalStateException expected) { }

        Task cancelled = new Task(() -> 42);
        require(cancelled.cancel(false), "cancel first");
        cancelled.fail(null);
        require(cancelled.state() == Future.State.CANCELLED && cancelled.completions.get() == 1, "cancelled no-op");

        RuntimeException original = new IllegalStateException("original");
        Task nonnull = new Task(() -> 42);
        nonnull.fail(original);
        nonnull.fail(null);
        require(nonnull.state() == Future.State.FAILED && nonnull.exceptionNow() == original
            && nonnull.completions.get() == 1, "nonnull cause changed");
    }
    private static void waitingGetter() throws Exception {
        Task task = new Task(() -> 42);
        AtomicReference<String> result = new AtomicReference<>("not-finished");
        Thread getter = new Thread(() -> {
            try { task.get(); result.set("unexpected-result"); }
            catch (ExecutionException error) { result.set(error.getCause() == null ? "null-cause" : "wrong-cause"); }
            catch (InterruptedException error) { result.set("interrupted"); }
        }, "future-null-getter");
        getter.start();
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
        while (getter.getState() != Thread.State.WAITING) {
            require(getter.isAlive() && System.nanoTime() - deadline < 0, "getter did not wait");
            Thread.yield();
        }
        task.fail(null);
        getter.join(5000);
        require(!getter.isAlive() && "null-cause".equals(result.get()), "getter outcome " + result.get());
        nullFailure(task);
    }
    public static void main(String[] args) throws Exception {
        pendingAndTerminal();
        waitingGetter();
        if (args.length == 1 && args[0].equals("source"))
            Class.forName("dev.latent.guest.runtime.Activation").getMethod("idle").invoke(null);
        System.out.println("FUTURE_TASK_NULL_FAILURE PASS pending;null-success;terminal-noop;nonnull;blocked-getter");
    }
}
