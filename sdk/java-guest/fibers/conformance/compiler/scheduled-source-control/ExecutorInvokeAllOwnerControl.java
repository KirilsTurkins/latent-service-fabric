import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.AbstractExecutorService;
import dev.latent.guest.runtime.concurrent.Executors;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Future;
import java.util.concurrent.RunnableFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/** Source-only physical-callback barrier with the existing fake activation ledger. */
public final class ExecutorInvokeAllOwnerControl {
    private static final class Marker extends RuntimeException { }
    private static final class Observed<T> implements RunnableFuture<T> {
        final RunnableFuture<T> original;
        final boolean optimistic;
        volatile int cancels;
        Observed(RunnableFuture<T> original, boolean optimistic) { this.original = original; this.optimistic = optimistic; }
        public void run() { original.run(); }
        public boolean cancel(boolean interrupt) { cancels++; return original.cancel(interrupt); }
        public boolean isCancelled() { return original.isCancelled(); }
        public boolean isDone() { return optimistic || original.isDone(); }
        public T get() throws InterruptedException, ExecutionException { return original.get(); }
        public T get(long t, TimeUnit u) throws InterruptedException, ExecutionException, TimeoutException { return original.get(t, u); }
    }
    private static final class Forward extends AbstractExecutorService {
        final ExecutorService original = Executors.newSingleThreadExecutor();
        final boolean optimistic, prefix;
        final List<Observed<?>> submitted = new ArrayList<>();
        CountDownLatch preparing, continuePreparation, callbackEntered;
        boolean rejectSecondConstruction, rejectAfterAcceptance;
        Forward(boolean optimistic, boolean prefix) { this.optimistic = optimistic; this.prefix = prefix; }
        @Override protected <T> RunnableFuture<T> newTaskFor(Callable<T> task) {
            if (rejectSecondConstruction && !submitted.isEmpty()) throw new Marker();
            if (submitted.isEmpty() && preparing != null) {
                preparing.countDown();
                try { if (!continuePreparation.await(4, TimeUnit.SECONDS)) throw new AssertionError("preparation-release"); }
                catch (InterruptedException error) { throw new AssertionError(error); }
            }
            Observed<T> result = new Observed<>(super.newTaskFor(task), optimistic || prefix && submitted.isEmpty());
            submitted.add(result); return result;
        }
        public void execute(Runnable command) {
            original.execute(command);
            if (callbackEntered != null) {
                try { if (!callbackEntered.await(4, TimeUnit.SECONDS)) throw new AssertionError("callback-not-entered"); }
                catch (InterruptedException error) { throw new AssertionError(error); }
            }
            if (rejectAfterAcceptance) throw new Marker();
        }
        public void shutdown() { original.shutdown(); }
        public List<Runnable> shutdownNow() { return original.shutdownNow(); }
        public boolean isShutdown() { return original.isShutdown(); }
        public boolean isTerminated() { return original.isTerminated(); }
        public boolean awaitTermination(long t, TimeUnit u) throws InterruptedException { return original.awaitTermination(t, u); }
    }
    private static void need(boolean condition, String text) { if (!condition) throw new AssertionError(text); }
    public static void main(String[] args) throws Exception {
        boolean optimistic = args.length == 1 && args[0].equals("optimistic");
        boolean prefix = args.length == 1 && args[0].equals("prefix");
        boolean firstPrepared = args.length == 1 && args[0].equals("first-prepared");
        boolean constructionFailure = args.length == 1 && args[0].equals("construction-failure");
        boolean acceptanceFailure = args.length == 1 && args[0].equals("accept-then-throw");
        need(args.length == 1 && (optimistic || prefix || firstPrepared || constructionFailure || acceptanceFailure
            || args[0].equals("timeout")), "mode");
        Forward pool = new Forward(optimistic, prefix);
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        CountDownLatch preparing = new CountDownLatch(1), continuePreparation = new CountDownLatch(1);
        if (firstPrepared) { pool.preparing = preparing; pool.continuePreparation = continuePreparation; pool.callbackEntered = entered; }
        if (constructionFailure) { pool.rejectSecondConstruction = true; pool.callbackEntered = entered; }
        if (acceptanceFailure) { pool.rejectAfterAcceptance = true; pool.callbackEntered = entered; }
        AtomicBoolean suffixRan = new AtomicBoolean();
        AtomicReference<List<Future<Integer>>> returned = new AtomicReference<>();
        AtomicReference<Throwable> failure = new AtomicReference<>();
        Thread caller = new Thread(() -> {
            try {
                Callable<Integer> first = () -> {
                    entered.countDown();
                    for (;;) try { release.await(); break; } catch (InterruptedException ignored) { }
                    return 42;
                };
                List<Callable<Integer>> tasks = prefix || firstPrepared || constructionFailure
                    ? List.of(first, () -> { suffixRan.set(true); return 43; }) : List.of(first);
                returned.set(constructionFailure || acceptanceFailure ? pool.invokeAll(tasks)
                    : pool.invokeAll(tasks, firstPrepared ? 10 : 1000, TimeUnit.MILLISECONDS));
            } catch (Throwable error) { failure.set(error); }
        });
        caller.setDaemon(true); caller.start();
        try {
            if (firstPrepared) {
                need(preparing.await(3, TimeUnit.SECONDS), "preparation-entered");
                Thread.sleep(50);
                continuePreparation.countDown();
            }
            need(entered.await(3, TimeUnit.SECONDS), "callback-entered");
            caller.join(3000);
            if (constructionFailure || acceptanceFailure) {
                need(!caller.isAlive() && failure.get() instanceof Marker && returned.get() == null
                    && pool.submitted.size() == 1 && pool.submitted.get(0).cancels == 1
                    && pool.submitted.get(0).isCancelled(), "construction-failure-result");
            } else {
                need(!caller.isAlive() && failure.get() == null && returned.get() != null, "caller-returned");
                need(pool.submitted.size() == (prefix || firstPrepared ? 2 : 1)
                    && pool.submitted.get(0).cancels == (optimistic || prefix ? 0 : 1)
                    && returned.get().get(0).isCancelled() == !(optimistic || prefix), "caller-result");
                if (prefix) need(pool.submitted.get(1).cancels == 1 && returned.get().get(1).isCancelled(), "suffix-cancelled");
                if (firstPrepared) need(pool.submitted.get(1).cancels == 1 && returned.get().get(1).isCancelled(), "prepared-suffix-cancelled");
            }
            need(Activation.count(LatentRuntimeActivationOwnerKind.Result) == 1
                && Activation.count(LatentRuntimeActivationOwnerKind.Executor) == 1
                && Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == (prefix ? 1 : 0),
                "physical-work-still-owned");
        } finally {
            continuePreparation.countDown(); release.countDown(); pool.shutdown();
            need(pool.awaitTermination(3, TimeUnit.SECONDS), "pool-retired");
            caller.join(3000);
        }
        need(Activation.count(LatentRuntimeActivationOwnerKind.Result) == 0
            && Activation.count(LatentRuntimeActivationOwnerKind.Executor) == 0
            && Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == 0
            && Activation.closeAttempts(LatentRuntimeActivationOwnerKind.Result) == 1
            && Activation.closeAttempts(LatentRuntimeActivationOwnerKind.Executor) == 1
            && Activation.closeAttempts(LatentRuntimeActivationOwnerKind.QueuedWork) == (prefix ? 2 : 1)
            && !suffixRan.get(),
            "original-owners-settled-once");
        Activation.idle();
        System.out.println("INVOKE_ALL_OWNER " + args[0] + " held=1:1:" + (prefix ? 1 : 0)
            + " retired=0:0:0 result-settle=1");
    }
}
