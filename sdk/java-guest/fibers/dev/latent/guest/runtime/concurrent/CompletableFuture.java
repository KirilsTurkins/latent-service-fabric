package dev.latent.guest.runtime.concurrent;

import dev.latent.generated.Bindings;
import dev.latent.guest.runtime.Activation;
import java.util.ArrayList;
import java.util.Objects;
import java.util.concurrent.CancellationException;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.function.BiConsumer;
import java.util.function.BiFunction;
import java.util.function.Consumer;
import java.util.function.Function;
import java.util.function.Supplier;

/** Pending standard stages on activation-owned fibers, with physical callback retirement. */
public class CompletableFuture<T> implements java.util.concurrent.Future<T>, CompletionStage<T> {
    private T value;
    private Throwable failure;
    private boolean completed;
    private final ArrayList<Action> dependents = new ArrayList<>();
    private final ArrayList<Action> accepted = new ArrayList<>();
    private Activation.Lease resultOwner;

    public CompletableFuture() { }

    private static Executor asyncPool() {
        return Activation.defaultAsyncExecutor(() -> Executors.newCachedThreadPool());
    }
    public Executor defaultExecutor() { return asyncPool(); }
    public <U> CompletableFuture<U> newIncompleteFuture() { return new CompletableFuture<>(); }

    private synchronized boolean accept(Action action, boolean evenIfCompleted) {
        if (completed && !evenIfCompleted) return false;
        if (resultOwner == null) resultOwner = Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.Result);
        try { accepted.add(action); }
        catch (Throwable error) {
            if (accepted.isEmpty()) { resultOwner.close(); resultOwner = null; }
            throw error;
        }
        return true;
    }
    private synchronized void retired(Action action) {
        if (!accepted.remove(action)) throw new IllegalStateException("activation-future-callback-owner");
        if (completed && accepted.isEmpty() && resultOwner != null) {
            resultOwner.close();
            resultOwner = null;
        }
    }
    private void subscribe(Action action) {
        synchronized (this) {
            if (action.finished || action.dispatched) return;
            if (!completed) { dependents.add(action); return; }
        }
        action.fire(false);
    }
    private synchronized void unsubscribe(Action action) { dependents.remove(action); }

    private static class Action implements Runnable {
        final CompletableFuture<?> destination;
        final CompletableFuture<?> left;
        final CompletableFuture<?> right;
        final boolean both;
        final Executor executor;
        final Runnable body;
        private Activation.Lease queued;
        volatile boolean dispatched;
        volatile boolean finished;

        Action(CompletableFuture<?> destination, CompletableFuture<?> left, CompletableFuture<?> right,
               boolean both, Executor executor, Runnable body) {
            this(destination, left, right, both, executor, body, false);
        }
        Action(CompletableFuture<?> destination, CompletableFuture<?> left, CompletableFuture<?> right,
               boolean both, Executor executor, Runnable body, boolean evenIfCompleted) {
            this.destination = destination;
            this.left = left;
            this.right = right;
            this.both = both;
            this.executor = executor;
            this.body = body;
            queued = Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork);
            try {
                if (!destination.accept(this, evenIfCompleted)) { queued.close(); queued = null; finished = true; }
            } catch (Throwable error) { queued.close(); queued = null; throw error; }
        }
        void install() {
            try {
                if (left != null) left.subscribe(this);
                if (right != null && right != left) right.subscribe(this);
                fire(false);
            } catch (Throwable error) { destination.asyncFailure(error); cancelWaiting(); throw error; }
        }
        void detach() {
            if (left != null) left.unsubscribe(this);
            if (right != null && right != left) right.unsubscribe(this);
        }
        private void finish() {
            synchronized (this) { if (finished) return; finished = true; }
            detach();
            try { queued.close(); }
            finally { queued = null; destination.retired(this); }
        }
        void cancelWaiting() {
            synchronized (this) {
                if (finished || dispatched) return;
                dispatched = true; // Claim removal before a concurrent input completion.
            }
            finish();
        }
        boolean ready() {
            return left == null || (right == null ? left.isDone()
                : both ? left.isDone() && right.isDone() : left.isDone() || right.isDone());
        }
        void perform() { body.run(); }
        void fire(boolean propagateRejection) {
            if (!ready()) return;
            synchronized (this) { if (finished || dispatched) return; dispatched = true; }
            detach();
            try {
                if (executor == null) run();
                else executor.execute(this);
            } catch (Throwable error) {
                try { destination.asyncFailure(error); }
                finally { finish(); }
                if (propagateRejection) throw error;
            }
        }
        @Override public void run() {
            try {
                if (!destination.isDone()) perform();
            } catch (Throwable error) { destination.asyncFailure(error); }
            finally { finish(); }
        }
    }

    private static final class Aggregate extends Action {
        private CompletableFuture<?>[] inputs;
        Aggregate(CompletableFuture<?> destination, CompletableFuture<?>[] inputs, boolean all) {
            super(destination, null, null, all, null, null);
            try { this.inputs = inputs.clone(); }
            catch (Throwable error) { destination.asyncFailure(error); throw error; }
        }
        @Override void install() {
            try {
                for (CompletableFuture<?> input : inputs) input.subscribe(this);
                fire(false);
            } catch (Throwable error) { destination.asyncFailure(error); cancelWaiting(); throw error; }
        }
        @Override void detach() {
            if (inputs != null) for (CompletableFuture<?> input : inputs) input.unsubscribe(this);
        }
        @Override boolean ready() {
            if (inputs == null) return false;
            for (CompletableFuture<?> input : inputs) {
                if (both && !input.isDone()) return false;
                if (!both && input.isDone()) return true;
            }
            return both;
        }
        @SuppressWarnings("unchecked")
        @Override void perform() {
            if (both) {
                for (CompletableFuture<?> input : inputs) {
                    Throwable error = input.error();
                    if (error != null) { destination.asyncFailure(error); return; }
                }
                ((CompletableFuture<Object>)destination).complete(null);
            } else {
                for (CompletableFuture<?> input : inputs) if (input.isDone()) {
                    ((CompletableFuture<Object>)destination).complete(input.successful());
                    return;
                }
                throw new IllegalStateException("activation-future-aggregate-not-ready");
            }
        }
    }

    private boolean finish(T result, Throwable error) {
        Action[] ready;
        Action[] pending;
        synchronized (this) {
            if (completed) return false;
            ready = dependents.toArray(new Action[0]);
            pending = accepted.toArray(new Action[0]);
            value = result;
            failure = error;
            completed = true;
            dependents.clear();
            notifyAll();
        }
        // Waiting continuations can be removed; queued/running callbacks retain
        // both owners until their physical run/finally scope has completed.
        for (Action action : pending) action.cancelWaiting();
        for (Action action : ready) action.fire(false);
        return true;
    }
    private static Throwable wrapped(Throwable error) {
        return error instanceof CompletionException ? error : new CompletionException(error);
    }
    private void asyncFailure(Throwable error) { completeExceptionally(wrapped(error)); }
    public boolean complete(T result) { return finish(result, null); }
    public boolean completeExceptionally(Throwable error) { return finish(null, Objects.requireNonNull(error)); }
    @Override public boolean cancel(boolean interrupt) {
        return finish(null, new CancellationException()) || isCancelled();
    }
    @Override public synchronized boolean isCancelled() { return completed && failure instanceof CancellationException; }
    @Override public synchronized boolean isDone() { return completed; }
    public synchronized boolean isCompletedExceptionally() { return completed && failure != null; }
    @Override public synchronized T resultNow() {
        if (!completed || failure != null) throw new IllegalStateException();
        return value;
    }
    @Override public synchronized Throwable exceptionNow() {
        if (!completed || failure == null || failure instanceof CancellationException) throw new IllegalStateException();
        return failure instanceof CompletionException && failure.getCause() != null ? failure.getCause() : failure;
    }
    @Override public synchronized java.util.concurrent.Future.State state() {
        if (!completed) return java.util.concurrent.Future.State.RUNNING;
        if (failure == null) return java.util.concurrent.Future.State.SUCCESS;
        return failure instanceof CancellationException ? java.util.concurrent.Future.State.CANCELLED
            : java.util.concurrent.Future.State.FAILED;
    }
    private T getResult() throws ExecutionException {
        if (failure instanceof CancellationException) throw (CancellationException)failure;
        if (failure != null) throw new ExecutionException(
            failure instanceof CompletionException && failure.getCause() != null ? failure.getCause() : failure);
        return value;
    }
    private T joinResult() {
        if (failure instanceof CancellationException) throw (CancellationException)failure;
        if (failure != null) throw (CompletionException)wrapped(failure);
        return value;
    }
    @Override public T get() throws InterruptedException, ExecutionException {
        synchronized (this) {
            if (!completed) {
                if (Thread.interrupted()) throw new InterruptedException();
                while (!completed) wait();
            }
            return getResult();
        }
    }
    @Override public T get(long timeout, TimeUnit unit) throws InterruptedException, ExecutionException, TimeoutException {
        long nanos = Objects.requireNonNull(unit).toNanos(timeout);
        long started = System.nanoTime();
        synchronized (this) {
            if (!completed) {
                if (Thread.interrupted()) throw new InterruptedException();
                if (nanos <= 0) throw new TimeoutException();
                while (!completed) {
                    long remaining = nanos - (System.nanoTime() - started);
                    if (remaining <= 0) throw new TimeoutException();
                    wait(remaining / 1_000_000, (int)(remaining % 1_000_000));
                }
            }
            return getResult();
        }
    }
    public T join() {
        boolean interrupted = false;
        try {
            synchronized (this) {
                while (!completed) {
                    try { wait(); }
                    catch (InterruptedException wake) { interrupted = true; }
                }
                return joinResult();
            }
        } finally { if (interrupted) Thread.currentThread().interrupt(); }
    }
    public synchronized T getNow(T otherwise) { return completed ? joinResult() : otherwise; }
    public synchronized int getNumberOfDependents() { return dependents.size(); }
    @Override public CompletableFuture<T> toCompletableFuture() { return this; }
    public CompletableFuture<T> copy() { return thenApply(Function.identity()); }

    private static <U> void submit(CompletableFuture<U> destination, Executor executor,
            Supplier<? extends U> supplier, boolean evenIfCompleted) {
        new Action(destination, null, null, true, executor,
            () -> destination.complete(supplier.get()), evenIfCompleted).fire(true);
    }
    public static <U> CompletableFuture<U> supplyAsync(Supplier<U> supplier) {
        Objects.requireNonNull(supplier);
        return supplyAsync(supplier, asyncPool());
    }
    public static <U> CompletableFuture<U> supplyAsync(Supplier<U> supplier, Executor executor) {
        Objects.requireNonNull(supplier); Objects.requireNonNull(executor);
        CompletableFuture<U> destination = new CompletableFuture<>();
        submit(destination, executor, supplier, false);
        return destination;
    }
    public static CompletableFuture<Void> runAsync(Runnable action) {
        Objects.requireNonNull(action);
        return runAsync(action, asyncPool());
    }
    public static CompletableFuture<Void> runAsync(Runnable action, Executor executor) {
        Objects.requireNonNull(action);
        return supplyAsync(() -> { action.run(); return null; }, executor);
    }
    public static <U> CompletableFuture<U> completedFuture(U result) {
        CompletableFuture<U> future = new CompletableFuture<>(); future.complete(result); return future;
    }
    public static <U> CompletableFuture<U> failedFuture(Throwable error) {
        CompletableFuture<U> future = new CompletableFuture<>(); future.completeExceptionally(error); return future;
    }
    public CompletableFuture<T> completeAsync(Supplier<? extends T> supplier) {
        Objects.requireNonNull(supplier); return completeAsync(supplier, defaultExecutor());
    }
    public CompletableFuture<T> completeAsync(Supplier<? extends T> supplier, Executor executor) {
        Objects.requireNonNull(supplier); Objects.requireNonNull(executor); submit(this, executor, supplier, true); return this;
    }

    private synchronized Throwable error() { return failure; }
    private synchronized T successful() {
        if (!completed) throw new IllegalStateException("activation-future-input-not-ready");
        return joinResult();
    }
    private <U> CompletableFuture<U> unary(Function<? super T, ? extends U> fn, Executor executor) {
        Objects.requireNonNull(fn);
        CompletableFuture<U> destination = newIncompleteFuture();
        new Action(destination, this, null, true, executor, () -> destination.complete(fn.apply(successful()))).install();
        return destination;
    }
    private <U, V> CompletableFuture<V> binary(CompletionStage<? extends U> other,
            BiFunction<? super T, ? super U, ? extends V> fn, Executor executor) {
        Objects.requireNonNull(fn);
        CompletableFuture<? extends U> right = Objects.requireNonNull(other).toCompletableFuture();
        CompletableFuture<V> destination = newIncompleteFuture();
        new Action(destination, this, right, true, executor,
            () -> destination.complete(fn.apply(successful(), right.successful()))).install();
        return destination;
    }
    private <U> CompletableFuture<U> either(CompletionStage<? extends T> other,
            Function<? super T, ? extends U> fn, Executor executor) {
        Objects.requireNonNull(fn);
        CompletableFuture<? extends T> right = Objects.requireNonNull(other).toCompletableFuture();
        CompletableFuture<U> destination = newIncompleteFuture();
        new Action(destination, this, right, false, executor,
            () -> destination.complete(fn.apply(isDone() ? successful() : right.successful()))).install();
        return destination;
    }
    private <U> CompletableFuture<U> handled(BiFunction<? super T, Throwable, ? extends U> fn, Executor executor) {
        Objects.requireNonNull(fn);
        CompletableFuture<U> destination = newIncompleteFuture();
        new Action(destination, this, null, true, executor, () -> {
            T result;
            Throwable error;
            synchronized (this) { result = value; error = failure; }
            destination.complete(fn.apply(result, error));
        }).install();
        return destination;
    }
    private CompletableFuture<T> observed(BiConsumer<? super T, ? super Throwable> fn, Executor executor) {
        Objects.requireNonNull(fn);
        CompletableFuture<T> destination = newIncompleteFuture();
        new Action(destination, this, null, true, executor, () -> {
            T result;
            Throwable error;
            synchronized (this) { result = value; error = failure; }
            try { fn.accept(result, error); }
            catch (Throwable callback) {
                if (error == null) throw callback;
                if (callback != error) error.addSuppressed(callback);
            }
            if (error == null) destination.complete(result); else destination.asyncFailure(error);
        }).install();
        return destination;
    }
    private void relay(CompletableFuture<T> destination) {
        new Action(destination, this, null, true, null, () -> {
            Throwable error = error();
            if (error == null) destination.complete(successful()); else destination.asyncFailure(error);
        }).install();
    }
    private <U> CompletableFuture<U> composed(Function<? super T, ? extends CompletionStage<U>> fn, Executor executor) {
        Objects.requireNonNull(fn);
        CompletableFuture<U> destination = newIncompleteFuture();
        new Action(destination, this, null, true, executor,
            () -> Objects.requireNonNull(fn.apply(successful())).toCompletableFuture().relay(destination)).install();
        return destination;
    }
    private CompletableFuture<T> recovered(Function<Throwable, ? extends T> fn, Executor executor) {
        Objects.requireNonNull(fn);
        return handled((result, error) -> error == null ? result : fn.apply(error), executor);
    }
    private CompletableFuture<T> recoveredStage(Function<Throwable, ? extends CompletionStage<T>> fn, Executor executor) {
        Objects.requireNonNull(fn);
        CompletableFuture<T> destination = newIncompleteFuture();
        new Action(destination, this, null, true, executor, () -> {
            Throwable error = error();
            if (error == null) destination.complete(successful());
            else Objects.requireNonNull(fn.apply(error)).toCompletableFuture().relay(destination);
        }).install();
        return destination;
    }

    @Override public <U> CompletableFuture<U> thenApply(Function<? super T, ? extends U> fn) { return unary(fn, null); }
    @Override public <U> CompletableFuture<U> thenApplyAsync(Function<? super T, ? extends U> fn) { Objects.requireNonNull(fn); return unary(fn, defaultExecutor()); }
    @Override public <U> CompletableFuture<U> thenApplyAsync(Function<? super T, ? extends U> fn, Executor executor) { return unary(fn, Objects.requireNonNull(executor)); }
    @Override public CompletableFuture<Void> thenAccept(Consumer<? super T> fn) { Objects.requireNonNull(fn); return unary(value -> { fn.accept(value); return null; }, null); }
    @Override public CompletableFuture<Void> thenAcceptAsync(Consumer<? super T> fn) { Objects.requireNonNull(fn); return thenAcceptAsync(fn, defaultExecutor()); }
    @Override public CompletableFuture<Void> thenAcceptAsync(Consumer<? super T> fn, Executor executor) { Objects.requireNonNull(fn); return unary(value -> { fn.accept(value); return null; }, Objects.requireNonNull(executor)); }
    @Override public CompletableFuture<Void> thenRun(Runnable fn) { Objects.requireNonNull(fn); return unary(value -> { fn.run(); return null; }, null); }
    @Override public CompletableFuture<Void> thenRunAsync(Runnable fn) { Objects.requireNonNull(fn); return thenRunAsync(fn, defaultExecutor()); }
    @Override public CompletableFuture<Void> thenRunAsync(Runnable fn, Executor executor) { Objects.requireNonNull(fn); return unary(value -> { fn.run(); return null; }, Objects.requireNonNull(executor)); }
    @Override public <U, V> CompletableFuture<V> thenCombine(CompletionStage<? extends U> other, BiFunction<? super T, ? super U, ? extends V> fn) { return binary(other, fn, null); }
    @Override public <U, V> CompletableFuture<V> thenCombineAsync(CompletionStage<? extends U> other, BiFunction<? super T, ? super U, ? extends V> fn) { Objects.requireNonNull(other); Objects.requireNonNull(fn); return binary(other, fn, defaultExecutor()); }
    @Override public <U, V> CompletableFuture<V> thenCombineAsync(CompletionStage<? extends U> other, BiFunction<? super T, ? super U, ? extends V> fn, Executor executor) { return binary(other, fn, Objects.requireNonNull(executor)); }
    @Override public <U> CompletableFuture<Void> thenAcceptBoth(CompletionStage<? extends U> other, BiConsumer<? super T, ? super U> fn) { Objects.requireNonNull(fn); return binary(other, (left, right) -> { fn.accept(left, right); return null; }, null); }
    @Override public <U> CompletableFuture<Void> thenAcceptBothAsync(CompletionStage<? extends U> other, BiConsumer<? super T, ? super U> fn) { Objects.requireNonNull(other); Objects.requireNonNull(fn); return thenAcceptBothAsync(other, fn, defaultExecutor()); }
    @Override public <U> CompletableFuture<Void> thenAcceptBothAsync(CompletionStage<? extends U> other, BiConsumer<? super T, ? super U> fn, Executor executor) { Objects.requireNonNull(fn); return binary(other, (left, right) -> { fn.accept(left, right); return null; }, Objects.requireNonNull(executor)); }
    @Override public CompletableFuture<Void> runAfterBoth(CompletionStage<?> other, Runnable fn) { Objects.requireNonNull(fn); return binary(other, (left, right) -> { fn.run(); return null; }, null); }
    @Override public CompletableFuture<Void> runAfterBothAsync(CompletionStage<?> other, Runnable fn) { Objects.requireNonNull(other); Objects.requireNonNull(fn); return runAfterBothAsync(other, fn, defaultExecutor()); }
    @Override public CompletableFuture<Void> runAfterBothAsync(CompletionStage<?> other, Runnable fn, Executor executor) { Objects.requireNonNull(fn); return binary(other, (left, right) -> { fn.run(); return null; }, Objects.requireNonNull(executor)); }
    @Override public <U> CompletableFuture<U> applyToEither(CompletionStage<? extends T> other, Function<? super T, U> fn) { return either(other, fn, null); }
    @Override public <U> CompletableFuture<U> applyToEitherAsync(CompletionStage<? extends T> other, Function<? super T, U> fn) { Objects.requireNonNull(other); Objects.requireNonNull(fn); return either(other, fn, defaultExecutor()); }
    @Override public <U> CompletableFuture<U> applyToEitherAsync(CompletionStage<? extends T> other, Function<? super T, U> fn, Executor executor) { return either(other, fn, Objects.requireNonNull(executor)); }
    @Override public CompletableFuture<Void> acceptEither(CompletionStage<? extends T> other, Consumer<? super T> fn) { Objects.requireNonNull(fn); return either(other, value -> { fn.accept(value); return null; }, null); }
    @Override public CompletableFuture<Void> acceptEitherAsync(CompletionStage<? extends T> other, Consumer<? super T> fn) { Objects.requireNonNull(other); Objects.requireNonNull(fn); return acceptEitherAsync(other, fn, defaultExecutor()); }
    @Override public CompletableFuture<Void> acceptEitherAsync(CompletionStage<? extends T> other, Consumer<? super T> fn, Executor executor) { Objects.requireNonNull(fn); return either(other, value -> { fn.accept(value); return null; }, Objects.requireNonNull(executor)); }
    @Override public CompletableFuture<Void> runAfterEither(CompletionStage<?> other, Runnable fn) { Objects.requireNonNull(fn); return eitherAny(other, fn, null); }
    @Override public CompletableFuture<Void> runAfterEitherAsync(CompletionStage<?> other, Runnable fn) { Objects.requireNonNull(other); Objects.requireNonNull(fn); return eitherAny(other, fn, defaultExecutor()); }
    @Override public CompletableFuture<Void> runAfterEitherAsync(CompletionStage<?> other, Runnable fn, Executor executor) { return eitherAny(other, Objects.requireNonNull(fn), Objects.requireNonNull(executor)); }
    private CompletableFuture<Void> eitherAny(CompletionStage<?> other, Runnable fn, Executor executor) {
        CompletableFuture<?> right = Objects.requireNonNull(other).toCompletableFuture();
        CompletableFuture<Void> destination = newIncompleteFuture();
        new Action(destination, this, right, false, executor, () -> {
            if (isDone()) successful(); else right.successful(); fn.run(); destination.complete(null);
        }).install();
        return destination;
    }
    @Override public <U> CompletableFuture<U> thenCompose(Function<? super T, ? extends CompletionStage<U>> fn) { return composed(fn, null); }
    @Override public <U> CompletableFuture<U> thenComposeAsync(Function<? super T, ? extends CompletionStage<U>> fn) { Objects.requireNonNull(fn); return composed(fn, defaultExecutor()); }
    @Override public <U> CompletableFuture<U> thenComposeAsync(Function<? super T, ? extends CompletionStage<U>> fn, Executor executor) { return composed(fn, Objects.requireNonNull(executor)); }
    @Override public <U> CompletableFuture<U> handle(BiFunction<? super T, Throwable, ? extends U> fn) { return handled(fn, null); }
    @Override public <U> CompletableFuture<U> handleAsync(BiFunction<? super T, Throwable, ? extends U> fn) { Objects.requireNonNull(fn); return handled(fn, defaultExecutor()); }
    @Override public <U> CompletableFuture<U> handleAsync(BiFunction<? super T, Throwable, ? extends U> fn, Executor executor) { return handled(fn, Objects.requireNonNull(executor)); }
    @Override public CompletableFuture<T> whenComplete(BiConsumer<? super T, ? super Throwable> fn) { return observed(fn, null); }
    @Override public CompletableFuture<T> whenCompleteAsync(BiConsumer<? super T, ? super Throwable> fn) { Objects.requireNonNull(fn); return observed(fn, defaultExecutor()); }
    @Override public CompletableFuture<T> whenCompleteAsync(BiConsumer<? super T, ? super Throwable> fn, Executor executor) { return observed(fn, Objects.requireNonNull(executor)); }
    @Override public CompletableFuture<T> exceptionally(Function<Throwable, ? extends T> fn) { return recovered(fn, null); }
    @Override public CompletableFuture<T> exceptionallyAsync(Function<Throwable, ? extends T> fn) { Objects.requireNonNull(fn); return recovered(fn, defaultExecutor()); }
    @Override public CompletableFuture<T> exceptionallyAsync(Function<Throwable, ? extends T> fn, Executor executor) { return recovered(fn, Objects.requireNonNull(executor)); }
    @Override public CompletableFuture<T> exceptionallyCompose(Function<Throwable, ? extends CompletionStage<T>> fn) { return recoveredStage(fn, null); }
    @Override public CompletableFuture<T> exceptionallyComposeAsync(Function<Throwable, ? extends CompletionStage<T>> fn) { Objects.requireNonNull(fn); return recoveredStage(fn, defaultExecutor()); }
    @Override public CompletableFuture<T> exceptionallyComposeAsync(Function<Throwable, ? extends CompletionStage<T>> fn, Executor executor) { return recoveredStage(fn, Objects.requireNonNull(executor)); }

    public static CompletableFuture<Void> allOf(CompletableFuture<?>... futures) {
        Objects.requireNonNull(futures);
        for (CompletableFuture<?> future : futures) Objects.requireNonNull(future);
        if (futures.length == 0) return completedFuture(null);
        CompletableFuture<Void> result = new CompletableFuture<>();
        new Aggregate(result, futures, true).install();
        return result;
    }
    public static CompletableFuture<Object> anyOf(CompletableFuture<?>... futures) {
        Objects.requireNonNull(futures);
        for (CompletableFuture<?> future : futures) Objects.requireNonNull(future);
        if (futures.length == 0) return new CompletableFuture<>();
        CompletableFuture<Object> result = new CompletableFuture<>();
        new Aggregate(result, futures, false).install();
        return result;
    }
}
