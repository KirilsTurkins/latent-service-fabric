import java.util.AbstractCollection;
import java.util.Iterator;
import java.util.List;
import java.util.concurrent.AbstractExecutorService;
import java.util.concurrent.Callable;
import java.util.concurrent.CancellationException;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/** Compares local JDK behavior and explicitly checks the SDK's full null validation. */
public final class ExecutorInvokeAnyReadyReferenceControl {
    private static final class Marker extends RuntimeException { }
    private static final class Direct extends AbstractExecutorService {
        final boolean rejectSecond;
        int executed;
        Direct(boolean rejectSecond) { this.rejectSecond = rejectSecond; }
        @Override public void execute(Runnable task) {
            executed++;
            if (rejectSecond && executed == 2) throw new RejectedExecutionException("second-denied");
            task.run();
        }
        @Override public void shutdown() { }
        @Override public List<Runnable> shutdownNow() { return List.of(); }
        @Override public boolean isShutdown() { return false; }
        @Override public boolean isTerminated() { return false; }
        @Override public boolean awaitTermination(long timeout, TimeUnit unit) { return false; }
    }
    private static final class Inputs extends AbstractCollection<Callable<Integer>> {
        final String mode;
        final AtomicInteger callbacks;
        int reads;
        Inputs(String mode, AtomicInteger callbacks) { this.mode = mode; this.callbacks = callbacks; }
        @Override public int size() { return 2; }
        @Override public Iterator<Callable<Integer>> iterator() {
            return new Iterator<>() {
                int position;
                @Override public boolean hasNext() { return position < 2; }
                @Override public Callable<Integer> next() {
                    position++;
                    reads++;
                    if (position == 2 && mode.equals("throw")) throw new Marker();
                    if (position == 2 && mode.equals("cancel")) throw new CancellationException("iterator");
                    if (position == 2 && mode.equals("null")) return null;
                    int value = position == 1 ? 42 : 43;
                    return () -> { callbacks.incrementAndGet(); return value; };
                }
            };
        }
    }
    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
    private static void ready(boolean timed) throws Exception {
        Direct direct = new Direct(true);
        AtomicInteger callbacks = new AtomicInteger();
        Callable<Integer> first = () -> { callbacks.incrementAndGet(); return 42; };
        Callable<Integer> second = () -> { callbacks.incrementAndGet(); return 43; };
        int result = timed ? direct.invokeAny(List.of(first, second), 0, TimeUnit.NANOSECONDS)
                           : direct.invokeAny(List.of(first, second));
        require(result == 42 && direct.executed == 1 && callbacks.get() == 1, "ready " + timed);
    }
    private static void failurePaths() throws Exception {
        Direct direct = new Direct(false);
        Callable<Integer> failed = () -> { throw new IllegalStateException("failed"); };
        require(direct.invokeAny(List.of(failed, () -> 43)) == 43 && direct.executed == 2, "failure then success");
        direct = new Direct(true);
        try { direct.invokeAny(List.of(failed, () -> 43)); throw new AssertionError("missing rejection"); }
        catch (RejectedExecutionException expected) { require(direct.executed == 2, "rejection attempts"); }
        direct = new Direct(false);
        try { direct.invokeAny(List.of(failed, failed)); throw new AssertionError("missing failure"); }
        catch (ExecutionException expected) {
            require(direct.executed == 2 && expected.getCause() instanceof IllegalStateException, "all failed");
        }
    }
    private static void iterator(String mode, boolean source) throws Exception {
        Direct direct = new Direct(false);
        AtomicInteger callbacks = new AtomicInteger();
        Inputs inputs = new Inputs(mode, callbacks);
        String outcome;
        try { outcome = "value-" + direct.invokeAny(inputs); }
        catch (Marker expected) { outcome = "marker"; }
        catch (CancellationException expected) { outcome = "iterator-cancel"; }
        catch (NullPointerException expected) { outcome = "null"; }
        String expected = !source || mode.equals("normal") ? "value-42"
            : mode.equals("throw") ? "marker" : mode.equals("cancel") ? "iterator-cancel" : "null";
        require(outcome.equals(expected), mode + " outcome=" + outcome);
        require(direct.executed == 1 && callbacks.get() == 1 && inputs.reads == (source ? 2 : 1), mode + " traversal");
    }
    public static void main(String[] args) throws Exception {
        boolean source = args[0].equals("source");
        if (!source && !args[0].equals("jdk")) throw new AssertionError("scope");
        ready(false); ready(true); failurePaths();
        for (String mode : List.of("normal", "throw", "cancel", "null")) iterator(mode, source);
        System.out.println("EXECUTOR_INVOKE_ANY_READY PASS one;zero;failure;rejection;all-failed;null-rule;iterator-observed");
    }
}
