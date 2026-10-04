package dev.latent.app;

import java.util.concurrent.CancellationException;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/** Ordinary standard API defaults: no executor injection or activation/shutdown glue. */
public final class Capsule {
    private static final ThreadLocal<String> local = new ThreadLocal<>();
    public static volatile boolean lateFlush;

    private static void require(boolean value) {
        if (!value) throw new IllegalStateException("completable-observable");
    }
    private static void sleep(long millis) {
        try { Thread.sleep(millis); }
        catch (InterruptedException error) { throw new IllegalStateException(error); }
    }
    public Long run(Long mode) {
        try {
            if (mode == 0) return defaults();
            if (mode == 1) return errorsAndCancellation();
            if (mode == 2) return stagesAndAggregation();
            if (mode == 3) return rootReturns();
            throw new IllegalArgumentException("completable-mode");
        } catch (InterruptedException | ExecutionException | TimeoutException error) {
            throw new IllegalStateException(error);
        }
    }
    private static Long defaults() throws InterruptedException, ExecutionException, TimeoutException {
        Thread root = Thread.currentThread();
        local.set("root");
        CompletableFuture<Integer> base = CompletableFuture.supplyAsync(() -> {
            require(Thread.currentThread() != root && local.get() == null);
            local.set("worker"); sleep(10); return 20;
        });
        require(base.thenApplyAsync(value -> value + 22).get() == 42);
        require("root".equals(local.get()));
        CompletionStage<Integer> pending = new CompletableFuture<>();
        CompletionStage<Integer> mapped = pending.thenComposeAsync(value -> CompletableFuture.supplyAsync(() -> value + 22));
        require(!mapped.toCompletableFuture().isDone());
        pending.toCompletableFuture().complete(20);
        require(mapped.toCompletableFuture().get(5, TimeUnit.SECONDS) == 42);
        require(CompletableFuture.runAsync(() -> { }).thenRunAsync(() -> { }).get() == null);
        return 42L;
    }
    private static final class Gate {
        private boolean entered, released, exited;
        private boolean interrupted;
        synchronized int work() {
            entered = true; notifyAll();
            try {
                while (!released) wait();
                return 42;
            } catch (InterruptedException error) { interrupted = true; return -1; }
            finally { exited = true; notifyAll(); }
        }
        synchronized void entered() throws InterruptedException { while (!entered) wait(); }
        synchronized void release() { released = true; notifyAll(); }
        synchronized void exited() throws InterruptedException { while (!exited) wait(); require(!interrupted); }
    }
    private static Long errorsAndCancellation() throws InterruptedException, ExecutionException {
        IllegalArgumentException cause = new IllegalArgumentException("completable-original-cause");
        CompletableFuture<Integer> failed = CompletableFuture.failedFuture(cause);
        try { failed.get(); throw new IllegalStateException("missing-exception"); }
        catch (ExecutionException error) { require(error.getCause() == cause); }
        try { failed.join(); throw new IllegalStateException("missing-completion-exception"); }
        catch (CompletionException error) { require(error.getCause() == cause); }
        require(failed.exceptionallyAsync(error -> 42).get() == 42);
        require(failed.handleAsync((value, error) -> error == cause ? 42 : -1).get() == 42);
        CompletableFuture<Integer> input = new CompletableFuture<>();
        boolean[] callback = {false};
        CompletableFuture<Integer> removed = input.thenApplyAsync(value -> { callback[0] = true; return value; });
        require(removed.cancel(true)); input.complete(42);
        Gate gate = new Gate();
        CompletableFuture<Integer> running = CompletableFuture.supplyAsync(gate::work);
        gate.entered(); require(running.cancel(true) && running.isCancelled());
        try { running.get(); throw new IllegalStateException("missing-cancellation"); }
        catch (CancellationException expected) { }
        gate.release(); gate.exited();
        require(!callback[0] && removed.isCancelled());
        return 42L;
    }
    private static Long stagesAndAggregation() throws InterruptedException, ExecutionException {
        CompletableFuture<Integer> first = new CompletableFuture<>();
        CompletableFuture<Integer> second = new CompletableFuture<>();
        CompletableFuture<Integer> combined = first.thenCombine(second, Integer::sum);
        CompletableFuture<Void> all = CompletableFuture.allOf(first, second);
        CompletableFuture<Object> any = CompletableFuture.anyOf(first, second);
        Thread left = new Thread(() -> { sleep(10); first.complete(20); });
        Thread right = new Thread(() -> { sleep(20); second.complete(22); });
        left.start(); right.start();
        require(combined.get() == 42 && all.join() == null);
        require(any.join().equals(20) || any.join().equals(22));
        left.join(); right.join();
        require(first.applyToEither(second, value -> value + 22).join() == 42);
        require(CompletableFuture.allOf().join() == null && !CompletableFuture.anyOf().isDone());
        require(first.thenCompose(value -> CompletableFuture.completedFuture(value + 22)).join() == 42);
        require(first.whenComplete((value, error) -> require(value == 20 && error == null)).join() == 20);
        return 42L;
    }
    private static Long rootReturns() {
        CompletableFuture.runAsync(() -> sleep(20)).thenRunAsync(() -> {
            sleep(10); lateFlush = true;
        });
        return 42L;
    }
}
