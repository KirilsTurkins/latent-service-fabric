package dev.latent.guest.runtime.concurrent;

import java.util.ArrayList;
import java.util.ArrayDeque;
import java.util.Collection;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Future;
import java.util.concurrent.RunnableFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/** Standard submissions with real pending tasks and cancellation on abandonment. */
public abstract class AbstractExecutorService implements java.util.concurrent.ExecutorService {
    protected <T> RunnableFuture<T> newTaskFor(Callable<T> task) { return new FutureTask<>(task); }
    protected <T> RunnableFuture<T> newTaskFor(Runnable task, T result) { return new FutureTask<>(task, result); }
    @Override public <T> Future<T> submit(Callable<T> task) {
        var future = newTaskFor(Objects.requireNonNull(task));
        execute(future);
        return future;
    }
    @Override public <T> Future<T> submit(Runnable task, T result) {
        var future = newTaskFor(Objects.requireNonNull(task), result);
        execute(future);
        return future;
    }
    @Override public Future<?> submit(Runnable task) { return submit(task, null); }

    @Override public <T> List<Future<T>> invokeAll(Collection<? extends Callable<T>> tasks) throws InterruptedException {
        try { return all(tasks, 0, false); }
        catch (TimeoutException impossible) { throw new AssertionError(impossible); }
    }
    @Override public <T> List<Future<T>> invokeAll(Collection<? extends Callable<T>> tasks,
            long timeout, TimeUnit unit) throws InterruptedException {
        try { return all(tasks, Objects.requireNonNull(unit).toNanos(timeout), true); }
        catch (TimeoutException impossible) { throw new AssertionError(impossible); }
    }
    private <T> List<Future<T>> all(Collection<? extends Callable<T>> tasks, long nanos, boolean timed)
            throws InterruptedException, TimeoutException {
        Objects.requireNonNull(tasks);
        // Completed results and empty task sets need no interruptible wait.
        long started = System.nanoTime();
        List<Future<T>> futures = new ArrayList<>(tasks.size());
        boolean finished = false;
        boolean timedOut = false;
        int observed = 0;
        try {
            // Materialize every result before executing: a null task does not
            // accidentally turn a partially validated collection into work.
            for (Callable<T> task : tasks) futures.add(newTaskFor(Objects.requireNonNull(task)));
            for (Future<T> future : futures) {
                if (timed && (nanos <= 0 || System.nanoTime() - started >= nanos)) return futures;
                execute((Runnable)future);
            }
            for (Future<T> future : futures) {
                // Preserve custom RunnableFuture dispatch, as the JDK does:
                // an already completed result does not need a get or a wait.
                if (!future.isDone()) {
                    try {
                        if (timed) {
                            long remaining = nanos - (System.nanoTime() - started);
                            future.get(remaining, TimeUnit.NANOSECONDS);
                        } else future.get();
                    } catch (ExecutionException | java.util.concurrent.CancellationException ignored) {
                        // Every submitted task is awaited regardless of its result.
                    } catch (TimeoutException expired) { timedOut = true; return futures; }
                }
                observed++;
            }
            finished = true;
            return futures;
        } finally {
            // A timed-out wait cancels its remaining suffix. Other failures
            // still cancel every submitted or not-yet-submitted result.
            if (!finished) for (int i = timedOut ? observed : 0; i < futures.size(); i++) futures.get(i).cancel(true);
        }
    }

    @Override public <T> T invokeAny(Collection<? extends Callable<T>> tasks)
            throws InterruptedException, ExecutionException {
        try { return any(tasks, 0, false); }
        catch (TimeoutException impossible) { throw new AssertionError(impossible); }
    }
    @Override public <T> T invokeAny(Collection<? extends Callable<T>> tasks, long timeout, TimeUnit unit)
            throws InterruptedException, ExecutionException, TimeoutException {
        return any(tasks, Objects.requireNonNull(unit).toNanos(timeout), true);
    }
    private <T> T any(Collection<? extends Callable<T>> tasks, long nanos, boolean timed)
            throws InterruptedException, ExecutionException, TimeoutException {
        Objects.requireNonNull(tasks);
        if (tasks.isEmpty()) throw new IllegalArgumentException();
        // A ready completion can be consumed without an interruptible wait.
        long started = System.nanoTime();
        Completion<T> completion = new Completion<>();
        ArrayList<Future<T>> futures = new ArrayList<>(tasks.size());
        var remaining = tasks.iterator();
        int active = 0;
        try {
            ExecutionException last = null;
            while (true) {
                Future<T> future;
                synchronized (completion) { future = completion.ready.pollFirst(); }
                if (future == null && remaining.hasNext()) {
                    Callable<T> task = Objects.requireNonNull(remaining.next());
                    FutureTask<T> next = new FutureTask<>(task) {
                        @Override protected void done() {
                            synchronized (completion) { completion.ready.addLast(this); completion.notifyAll(); }
                        }
                    };
                    // An executor may accept the task and then throw, so retain
                    // its cancellation obligation before entering execute.
                    futures.add(next);
                    execute(next);
                    active++;
                    continue;
                }
                if (future == null) {
                    if (active == 0) break;
                    synchronized (completion) {
                        while (completion.ready.isEmpty()) {
                            if (!timed) completion.wait();
                            else {
                                // A timed queue wait observes interruption even
                                // when its deadline has already elapsed.
                                if (Thread.interrupted()) throw new InterruptedException();
                                if (nanos <= 0) throw new TimeoutException();
                                long wait = nanos - (System.nanoTime() - started);
                                if (wait <= 0) throw new TimeoutException();
                                completion.wait(wait / 1_000_000, (int)(wait % 1_000_000));
                            }
                        }
                        future = completion.ready.removeFirst();
                    }
                }
                active--;
                T value;
                try { value = future.get(); }
                catch (ExecutionException failed) { last = failed; continue; }
                catch (java.util.concurrent.CancellationException cancelled) { last = new ExecutionException(cancelled); continue; }
                // Preserve the public null-element check without submitting more
                // work once an already-completed task supplied the result.
                while (remaining.hasNext()) Objects.requireNonNull(remaining.next());
                return value;
            }
            throw last == null ? new ExecutionException(new IllegalStateException()) : last;
        } finally { for (Future<T> future : futures) future.cancel(true); }
    }

    private static final class Completion<T> {
        final ArrayDeque<Future<T>> ready = new ArrayDeque<>();
    }
}
