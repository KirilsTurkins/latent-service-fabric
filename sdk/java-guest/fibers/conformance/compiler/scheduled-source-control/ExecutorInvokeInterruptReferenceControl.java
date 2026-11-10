import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.AbstractExecutorService;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Same ordinary executor observables against the JDK and the owned source port. */
public final class ExecutorInvokeInterruptReferenceControl {
    private static final class LocalExecutor extends AbstractExecutorService {
        final boolean direct;
        final List<Runnable> queued = new ArrayList<>();
        final CountDownLatch submitted = new CountDownLatch(1);
        LocalExecutor(boolean direct) { this.direct = direct; }
        public void execute(Runnable task) {
            if (direct) task.run(); else { queued.add(task); submitted.countDown(); }
        }
        void drain() { for (Runnable task : queued) task.run(); }
        public void shutdown() { }
        public List<Runnable> shutdownNow() { return List.of(); }
        public boolean isShutdown() { return false; }
        public boolean isTerminated() { return false; }
        public boolean awaitTermination(long timeout, TimeUnit unit) { return false; }
    }
    private record Observation(String outcome, boolean interrupted, int before, int after) { }
    private static void require(boolean value, String detail) {
        if (!value) throw new AssertionError(detail);
    }
    private static Observation preinterrupted(String mode) throws Exception {
        Thread.interrupted();
        Thread.currentThread().interrupt();
        LocalExecutor service = new LocalExecutor(!mode.contains("pending"));
        AtomicInteger calls = new AtomicInteger();
        String outcome;
        try {
            List<Callable<Integer>> task = List.of(() -> { calls.incrementAndGet(); return 42; });
            Object result = switch (mode) {
                case "all-empty" -> service.invokeAll(List.<Callable<Integer>>of()).size();
                case "any-empty" -> service.invokeAny(List.<Callable<Integer>>of());
                case "all-ready", "all-pending" -> service.invokeAll(task).getFirst().get();
                case "all-timed", "all-pending-timed" -> service.invokeAll(task, 10, TimeUnit.SECONDS).getFirst().get();
                case "all-zero", "all-zero-pending" -> service.invokeAll(task, 0, TimeUnit.SECONDS).getFirst().isCancelled();
                case "any-ready", "any-pending" -> service.invokeAny(task);
                case "any-timed", "any-pending-timed" -> service.invokeAny(task, 10, TimeUnit.SECONDS);
                case "any-zero", "any-zero-pending" -> service.invokeAny(task, 0, TimeUnit.SECONDS);
                default -> throw new AssertionError(mode);
            };
            outcome = "returned=" + result;
        } catch (InterruptedException error) { outcome = "InterruptedException"; }
        catch (TimeoutException error) { outcome = "TimeoutException"; }
        catch (IllegalArgumentException error) { outcome = "IllegalArgumentException"; }
        boolean interrupted = Thread.currentThread().isInterrupted();
        int before = calls.get();
        Thread.interrupted();
        service.drain();
        return new Observation(outcome, interrupted, before, calls.get());
    }
    private static void interruptWhileWaiting(boolean any) throws Exception {
        LocalExecutor service = new LocalExecutor(false);
        AtomicInteger calls = new AtomicInteger();
        AtomicReference<String> outcome = new AtomicReference<>("not-finished");
        Thread caller = new Thread(() -> {
            try {
                List<Callable<Integer>> task = List.of(() -> { calls.incrementAndGet(); return 42; });
                if (any) service.invokeAny(task); else service.invokeAll(task);
                outcome.set("unexpected-return");
            } catch (InterruptedException error) {
                outcome.set(Thread.currentThread().isInterrupted() ? "interrupt-not-cleared" : "interrupted");
            } catch (Exception error) { outcome.set(error.getClass().getName()); }
        }, "invoke-interrupt-caller");
        caller.start();
        require(service.submitted.await(5, TimeUnit.SECONDS), "no task submitted");
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
        while (caller.getState() != Thread.State.WAITING) {
            require(caller.isAlive() && System.nanoTime() - deadline < 0, "caller did not wait");
            Thread.yield();
        }
        caller.interrupt();
        caller.join(5000);
        require(!caller.isAlive() && "interrupted".equals(outcome.get()), "waiting interruption " + outcome.get());
        service.drain();
        require(calls.get() == 0, "cancelled task later ran");
    }
    public static void main(String[] args) throws Exception {
        for (String mode : List.of("all-empty", "any-empty", "all-ready", "all-timed", "all-zero",
                "any-ready", "any-timed", "any-zero", "all-pending", "all-pending-timed",
                "any-pending", "any-pending-timed", "all-zero-pending", "any-zero-pending")) {
            Observation expected = switch (mode) {
                case "all-empty" -> new Observation("returned=0", true, 0, 0);
                case "any-empty" -> new Observation("IllegalArgumentException", true, 0, 0);
                case "all-zero", "all-zero-pending" -> new Observation("returned=true", true, 0, 0);
                case "all-pending", "all-pending-timed", "any-pending", "any-pending-timed" ->
                    new Observation("InterruptedException", false, 0, 0);
                case "any-zero-pending" -> new Observation("InterruptedException", false, 0, 0);
                default -> new Observation("returned=42", true, 1, 1);
            };
            Observation actual = preinterrupted(mode);
            require(expected.equals(actual), mode + " expected=" + expected + " actual=" + actual);
        }
        interruptWhileWaiting(false);
        interruptWhileWaiting(true);
        if (args.length == 1 && args[0].equals("source"))
            Class.forName("dev.latent.guest.runtime.Activation").getMethod("idle").invoke(null);
        System.out.println("EXECUTOR_INVOKE_INTERRUPT PASS preinterrupted-ready;empty;zero;pending-cancel;blocked-interrupt");
    }
}
