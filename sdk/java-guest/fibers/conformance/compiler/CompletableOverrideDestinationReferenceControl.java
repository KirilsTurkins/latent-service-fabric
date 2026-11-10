import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executor;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

public final class CompletableOverrideDestinationReferenceControl {
    private static boolean sourcePort;
    private static void owners(int queued, int results) {
        if (!sourcePort) return;
        try {
            Class<?> ledger = Class.forName("dev.latent.guest.runtime.Activation");
            if ((Integer)ledger.getMethod("queuedOwners").invoke(null) != queued
                    || (Integer)ledger.getMethod("resultOwners").invoke(null) != results)
                throw new AssertionError("original-source-ledger");
        } catch (ReflectiveOperationException error) { throw new AssertionError(error); }
    }
    private static void cleanup() throws Exception {
        if (sourcePort) Class.forName("dev.latent.guest.runtime.Activation").getMethod("cleanup").invoke(null);
    }
    private static final class Sink<T> extends CompletableFuture<T> {
        int completions, failures;
        @Override public boolean complete(T value) { completions++; return false; }
        @Override public boolean completeExceptionally(Throwable error) { failures++; return false; }
    }
    private static final class Maker<T> extends CompletableFuture<T> {
        @Override public <U> CompletableFuture<U> newIncompleteFuture() { return new Sink<U>(); }
    }
    private static final class Held implements Executor {
        Runnable action;
        @Override public void execute(Runnable action) { this.action = action; }
    }
    private static final class HeldReject implements Executor {
        Runnable action;
        @Override public void execute(Runnable action) {
            this.action = action;
            throw new RejectedExecutionException("queued-before-throw");
        }
    }
    private static String outcome(CompletableFuture<?> future) {
        try { return String.valueOf(future.getNow(null)); }
        catch (RuntimeException error) {
            Throwable cause = error.getCause();
            return "error:" + (cause == null ? error : cause).getClass().getSimpleName();
        }
    }
    private static void result(String name, CompletableFuture<Integer> future) {
        Sink<?> sink = (Sink<?>)future;
        System.out.println(name + ":" + outcome(future) + ":completeCalls=" + sink.completions + ":failureCalls=" + sink.failures);
        owners(0, 0);
        future.cancel(false);
    }
    private static void success() {
        Maker<Integer> source = new Maker<>();
        CompletableFuture<Integer> child = source.thenApply(v -> v + 1);
        source.complete(41);
        result("thenApply", child);
    }
    private static void failure() {
        Maker<Integer> source = new Maker<>();
        CompletableFuture<Integer> child = source.thenApply(v -> { throw new IllegalArgumentException("callback"); });
        source.complete(41);
        result("callbackFailure", child);
    }
    private static void failureShortcut() {
        Maker<Integer> source = new Maker<>();
        CompletableFuture<Integer> child = source.thenApply(v -> v + 1);
        source.completeExceptionally(new IllegalArgumentException("source"));
        result("sourceFailure", child);
    }
    private static void compose() {
        Maker<Integer> source = new Maker<>();
        CompletableFuture<Integer> child = source.thenCompose(v -> CompletableFuture.completedFuture(v + 1));
        source.complete(41);
        result("thenCompose", child);
    }
    private static void recovery() {
        Maker<Integer> source = new Maker<>();
        CompletableFuture<Integer> child = source.exceptionally(error -> 42);
        source.completeExceptionally(new IllegalArgumentException("source"));
        result("exceptionally", child);
    }
    private static void binary() {
        Maker<Integer> source = new Maker<>();
        CompletableFuture<Integer> child = source.thenCombine(CompletableFuture.completedFuture(2), Integer::sum);
        source.complete(40);
        result("thenCombine", child);
    }
    private static void either() {
        Maker<Integer> source = new Maker<>();
        CompletableFuture<Integer> child = source.applyToEither(new CompletableFuture<>(), v -> v + 1);
        source.complete(41);
        result("applyToEither", child);
    }
    private static void eitherVoid() {
        Maker<Integer> source = new Maker<>();
        int[] calls = {0};
        CompletableFuture<Void> child = source.runAfterEither(new CompletableFuture<>(), () -> calls[0]++);
        source.complete(41);
        Sink<?> sink = (Sink<?>)child;
        System.out.println("runAfterEither:done=" + child.isDone() + ":callbacks=" + calls[0]
            + ":completeCalls=" + sink.completions + ":failureCalls=" + sink.failures);
        owners(0, 0);
        child.cancel(false);
    }
    private static void handle() {
        Maker<Integer> source = new Maker<>();
        CompletableFuture<Integer> child = source.handle((value, error) -> error == null ? value : 42);
        source.completeExceptionally(new IllegalArgumentException("source"));
        result("handle", child);
    }
    private static void observed(boolean failed) {
        Maker<Integer> source = new Maker<>();
        int[] calls = {0};
        CompletableFuture<Integer> child = source.whenComplete((value, error) -> calls[0]++);
        if (failed) source.completeExceptionally(new IllegalArgumentException("source"));
        else source.complete(41);
        if (calls[0] != 1) throw new AssertionError("observer-not-called");
        result(failed ? "whenCompleteFailure" : "whenComplete", child);
    }
    private static void recoverStage() {
        Maker<Integer> source = new Maker<>();
        CompletableFuture<Integer> child = source.exceptionallyCompose(error -> CompletableFuture.completedFuture(42));
        source.completeExceptionally(new IllegalArgumentException("source"));
        result("exceptionallyCompose", child);
    }
    private static void composeFailure() {
        Maker<Integer> source = new Maker<>();
        CompletableFuture<Integer> child = source.thenCompose(v -> CompletableFuture.failedFuture(new IllegalArgumentException("nested")));
        source.complete(41);
        result("thenComposeFailure", child);
    }
    private static void asyncCompletion() {
        Sink<Integer> sink = new Sink<>();
        Executor inline = Runnable::run;
        sink.completeAsync(() -> 42, inline);
        result("completeAsync", sink);
    }
    private static void asyncFailure() {
        Sink<Integer> sink = new Sink<>();
        sink.completeAsync(() -> { throw new IllegalArgumentException("supplier"); }, Runnable::run);
        result("completeAsyncFailure", sink);
    }
    private static void publicOverride() {
        Sink<Integer> sink = new Sink<>();
        boolean returned = sink.complete(42);
        System.out.println("publicComplete:" + returned + ":" + outcome(sink) + ":completeCalls=" + sink.completions);
        sink.cancel(false);
    }
    private static void publicFailureOverride() {
        Sink<Integer> sink = new Sink<>();
        boolean returned = sink.completeExceptionally(new IllegalArgumentException("manual"));
        System.out.println("publicFailure:" + returned + ":" + outcome(sink) + ":failureCalls=" + sink.failures);
        sink.cancel(false);
    }
    private static void barrier(String mode) throws Exception {
        Maker<Integer> source = new Maker<>();
        Held held = new Held();
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicReference<Throwable> workerError = new AtomicReference<>();
        CompletableFuture<Integer> child = source.thenApplyAsync(v -> {
            entered.countDown();
            try {
                if (!release.await(5, TimeUnit.SECONDS)) throw new AssertionError("release-timeout");
            } catch (InterruptedException error) { throw new AssertionError(error); }
            if (mode.equals("failure")) throw new IllegalArgumentException("callback");
            return v + 1;
        }, held);
        source.complete(41);
        if (held.action == null) throw new AssertionError("not-enqueued");
        owners(1, 1);
        Thread worker = new Thread(() -> {
            try { held.action.run(); } catch (Throwable error) { workerError.set(error); }
        });
        worker.setDaemon(true); worker.start();
        try {
            if (!entered.await(5, TimeUnit.SECONDS)) throw new AssertionError("callback-not-entered");
            owners(1, 1);
            String before = outcome(child);
            if (mode.equals("cancel")) child.cancel(false);
            owners(1, 1);
            release.countDown();
            worker.join(5000);
            if (worker.isAlive() || workerError.get() != null) throw new AssertionError("worker-not-clean", workerError.get());
            owners(0, 0);
            Sink<?> sink = (Sink<?>)child;
            System.out.println("barrier:" + mode + ":before=" + before + ":after=" + outcome(child)
                + ":completeCalls=" + sink.completions + ":failureCalls=" + sink.failures);
        } finally { release.countDown(); worker.join(5000); child.cancel(false); }
    }
    private static void queuedRejection() {
        Maker<Integer> source = new Maker<>();
        HeldReject executor = new HeldReject();
        int[] callbacks = {0};
        CompletableFuture<Integer> child = source.thenApplyAsync(v -> { callbacks[0]++; return v + 1; }, executor);
        source.complete(41);
        if (executor.action == null) throw new AssertionError("not-retained");
        owners(1, 1);
        String before = outcome(child);
        executor.action.run();
        owners(0, 0);
        Sink<?> sink = (Sink<?>)child;
        System.out.println("queuedRejection:before=" + before + ":after=" + outcome(child) + ":callbacks=" + callbacks[0]
            + ":completeCalls=" + sink.completions + ":failureCalls=" + sink.failures);
        child.cancel(false);
    }
    public static void main(String[] args) throws Exception {
        sourcePort = args.length == 1 && args[0].equals("source");
        success(); failure(); failureShortcut(); compose(); recovery(); binary(); either(); eitherVoid(); handle();
        observed(false); observed(true); recoverStage(); composeFailure(); asyncCompletion(); asyncFailure();
        publicOverride(); publicFailureOverride(); barrier("normal"); barrier("failure"); barrier("cancel"); queuedRejection();
        cleanup();
    }
}
