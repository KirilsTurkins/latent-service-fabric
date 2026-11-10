import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.AbstractExecutorService;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Future;
import java.util.concurrent.FutureTask;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.RunnableFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicReference;

/** Same public executor control, run once against the JDK and once against source. */
public final class ExecutorInvokeAllWaitReferenceControl {
    private static final class Marker extends RuntimeException { }
    private static final class Observed<T> implements RunnableFuture<T> {
        final RunnableFuture<T> delegate;
        boolean forbidDoneGet;
        boolean forbidDoneCancel;
        boolean falseDone;
        boolean throwDone;
        int cancelCalls;
        int getCalls;
        long lastTimeout = Long.MAX_VALUE;
        Observed(RunnableFuture<T> delegate) { this.delegate = delegate; }
        public void run() { delegate.run(); }
        public boolean cancel(boolean mayInterrupt) {
            cancelCalls++;
            if (forbidDoneCancel && delegate.isDone()) throw new Marker();
            return delegate.cancel(mayInterrupt);
        }
        public boolean isCancelled() { return delegate.isCancelled(); }
        public boolean isDone() { if (throwDone) throw new Marker(); return !falseDone && delegate.isDone(); }
        public T get() throws InterruptedException, ExecutionException {
            getCalls++;
            if (forbidDoneGet && delegate.isDone()) throw new Marker();
            return delegate.get();
        }
        public T get(long t, TimeUnit u) throws InterruptedException, ExecutionException, TimeoutException {
            getCalls++; lastTimeout = t;
            if (forbidDoneGet && delegate.isDone()) throw new Marker();
            return delegate.get(t, u);
        }
    }
    private static final class Direct extends AbstractExecutorService {
        final List<Observed<?>> created = new ArrayList<>();
        boolean holdSecond;
        boolean rejectSecond;
        boolean sleepAfterFirst;
        boolean forbidDoneGet;
        boolean forbidDoneCancel;
        boolean falseDone;
        boolean throwDone;
        int submissions;
        CountDownLatch preparing, continuePreparation;
        @Override protected <T> RunnableFuture<T> newTaskFor(Callable<T> task) {
            if (created.isEmpty() && preparing != null) {
                preparing.countDown();
                try {
                    if (!continuePreparation.await(4, TimeUnit.SECONDS)) throw new AssertionError("preparation-release");
                } catch (InterruptedException error) { throw new AssertionError(error); }
            }
            Observed<T> f = new Observed<>(super.newTaskFor(task));
            f.forbidDoneGet = forbidDoneGet; f.forbidDoneCancel = forbidDoneCancel;
            f.falseDone = falseDone; f.throwDone = throwDone;
            created.add(f); return f;
        }
        @Override public void execute(Runnable task) {
            if (++submissions == 2 && rejectSecond) throw new RejectedExecutionException("second");
            if (submissions == 2 && holdSecond) return;
            task.run();
            if (sleepAfterFirst && submissions == 1)
                try { Thread.sleep(650); } catch (InterruptedException e) { throw new AssertionError(e); }
        }
        public void shutdown() { }
        public List<Runnable> shutdownNow() { return List.of(); }
        public boolean isShutdown() { return false; }
        public boolean isTerminated() { return false; }
        public boolean awaitTermination(long timeout, TimeUnit unit) { return false; }
    }
    private static final class Guarded<T> extends FutureTask<T> {
        int gets;
        Guarded(Callable<T> task) { super(task); }
        @Override public T get() throws InterruptedException, ExecutionException {
            gets++; if (isDone()) throw new Marker(); return super.get();
        }
        @Override public T get(long t, TimeUnit u) throws InterruptedException, ExecutionException, TimeoutException {
            gets++; if (isDone()) throw new Marker(); return super.get(t, u);
        }
    }
    private static final class DirectGuarded extends AbstractExecutorService {
        Guarded<?> submitted;
        @Override protected <T> RunnableFuture<T> newTaskFor(Callable<T> task) {
            Guarded<T> future = new Guarded<>(task); submitted = future; return future;
        }
        public void execute(Runnable task) { task.run(); }
        public void shutdown() { }
        public List<Runnable> shutdownNow() { return List.of(); }
        public boolean isShutdown() { return false; }
        public boolean isTerminated() { return false; }
        public boolean awaitTermination(long timeout, TimeUnit unit) { return false; }
    }
    private static void need(boolean ok, String label) { if (!ok) throw new AssertionError(label); }
    private static void completed(boolean timed, boolean failure) throws Exception {
        Direct executor = new Direct(); executor.forbidDoneGet = true; executor.forbidDoneCancel = true;
        executor.sleepAfterFirst = timed;
        Callable<Integer> task = () -> { if (failure) throw new IllegalStateException("task"); return 42; };
        List<Future<Integer>> result = timed ? executor.invokeAll(List.of(task), 500, TimeUnit.MILLISECONDS)
            : executor.invokeAll(List.of(task));
        Observed<?> f = executor.created.get(0);
        need(executor.submissions == 1 && result.size() == 1 && f.cancelCalls == 0 && f.getCalls == 0,
            "completed-early-or-late");
        if (failure) {
            try { f.delegate.get(); throw new AssertionError("missing-failure"); }
            catch (ExecutionException expected) { need(expected.getCause() instanceof IllegalStateException, "failure-cause"); }
        } else need(f.delegate.get().equals(42), "completed-value");
    }
    private static void completedRace() throws Exception {
        Direct executor = new Direct(); executor.falseDone = true; executor.forbidDoneCancel = true;
        executor.sleepAfterFirst = true;
        executor.invokeAll(List.of(() -> 42), 500, TimeUnit.MILLISECONDS);
        Observed<?> f = executor.created.get(0);
        need(f.getCalls == 1 && f.lastTimeout <= 0 && f.cancelCalls == 0 && f.delegate.get().equals(42),
            "completed-between-check-and-get");
    }
    private static void guarded(boolean timed) throws Exception {
        DirectGuarded executor = new DirectGuarded();
        List<Future<Integer>> result = timed ? executor.invokeAll(List.of(() -> 42), 1, TimeUnit.SECONDS)
            : executor.invokeAll(List.of(() -> 42));
        need(result.size() == 1 && result.get(0).isDone() && !result.get(0).isCancelled()
            && executor.submitted.gets == 0, "subclass-completed-get");
    }
    private static void timeoutSuffix() throws Exception {
        Direct executor = new Direct(); executor.forbidDoneCancel = true; executor.holdSecond = true;
        List<Future<Integer>> result = executor.invokeAll(List.of(() -> 42, () -> 43), 150, TimeUnit.MILLISECONDS);
        need(result.size() == 2 && result.get(0).get() == 42 && result.get(1).isCancelled()
            && executor.created.get(0).cancelCalls == 0 && executor.created.get(1).cancelCalls == 1,
            "timeout-cancel-suffix");
    }
    private static void exceptionCancelsAll() throws Exception {
        Direct executor = new Direct(); executor.rejectSecond = true;
        try { executor.invokeAll(List.of(() -> 42, () -> 43), 1, TimeUnit.SECONDS); throw new AssertionError("missing-rejection"); }
        catch (RejectedExecutionException expected) {
            need(executor.created.size() == 2 && executor.created.get(0).cancelCalls == 1
                && executor.created.get(1).cancelCalls == 1, "failure-cancel-all");
        }
        Direct inspecting = new Direct(); inspecting.throwDone = true;
        try { inspecting.invokeAll(List.of(() -> 42, () -> 43)); throw new AssertionError("missing-done-failure"); }
        catch (Marker expected) {
            need(inspecting.created.size() == 2 && inspecting.created.get(0).cancelCalls == 1
                && inspecting.created.get(1).cancelCalls == 1, "done-failure-cancel-all");
        }
    }
    private static void nonpositive() throws Exception {
        for (int timeout : new int[]{0, -1}) {
            Direct executor = new Direct();
            List<Future<Integer>> result = executor.invokeAll(List.of(() -> 42), timeout, TimeUnit.NANOSECONDS);
            need(executor.submissions == 0 && result.get(0).isCancelled()
                && executor.created.get(0).cancelCalls == 1, "nonpositive");
        }
    }
    private static void firstSubmissionAfterPreparation() throws Exception {
        Direct executor = new Direct();
        executor.preparing = new CountDownLatch(1); executor.continuePreparation = new CountDownLatch(1);
        AtomicReference<List<Future<Integer>>> result = new AtomicReference<>();
        AtomicReference<Throwable> error = new AtomicReference<>();
        Thread caller = new Thread(() -> {
            try { result.set(executor.invokeAll(List.of(() -> 42, () -> 43), 10, TimeUnit.MILLISECONDS)); }
            catch (Throwable failure) { error.set(failure); }
        });
        caller.setDaemon(true); caller.start();
        try {
            need(executor.preparing.await(4, TimeUnit.SECONDS), "preparation-entry");
            Thread.sleep(50); // The first task has not yet been constructed when the deadline expires.
        } finally { executor.continuePreparation.countDown(); }
        caller.join(4000);
        need(!caller.isAlive() && error.get() == null && result.get() != null, "preparation-caller");
        need(executor.submissions == 1 && result.get().get(0).get() == 42
            && result.get().get(1).isCancelled(), "first-submission-after-preparation");
    }
    public static void main(String[] args) throws Exception {
        if (args.length > 1 || args.length == 1 && !List.of("untimed", "guarded", "late", "negative", "suffix", "exception", "nonpositive", "first-submission").contains(args[0]))
            throw new IllegalArgumentException("control-mode");
        if (args.length == 0 || args[0].equals("untimed")) { completed(false, false); completed(false, true); }
        if (args.length == 0 || args[0].equals("guarded")) { guarded(false); guarded(true); }
        if (args.length == 0 || args[0].equals("late")) { completed(true, false); completed(true, true); }
        if (args.length == 0 || args[0].equals("negative")) completedRace();
        if (args.length == 0 || args[0].equals("suffix")) timeoutSuffix();
        if (args.length == 0 || args[0].equals("exception")) exceptionCancelsAll();
        if (args.length == 0 || args[0].equals("nonpositive")) nonpositive();
        if (args.length == 0 || args[0].equals("first-submission")) firstSubmissionAfterPreparation();
        System.out.println("INVOKE_ALL_WAIT PASS " + (args.length == 0
            ? "completed;subclass;late;negative-get;timeout-suffix;exception;done-failure;nonpositive;first-submission" : args[0]));
    }
}
