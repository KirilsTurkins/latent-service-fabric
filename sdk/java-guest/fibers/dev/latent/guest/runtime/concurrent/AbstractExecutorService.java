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
        if (Thread.interrupted()) throw new InterruptedException();
        long started = System.nanoTime();
        List<Future<T>> futures = new ArrayList<>(tasks.size());
        boolean finished = false;
        try {
            // Materialize every result before executing: a null task does not
            // accidentally turn a partially validated collection into work.
            for (Callable<T> task : tasks) futures.add(newTaskFor(Objects.requireNonNull(task)));
            for (Future<T> future : futures) {
                if (timed && (nanos <= 0 || System.nanoTime() - started >= nanos)) return futures;
                execute((Runnable)future);
            }
            for (Future<T> future : futures) {
                try {
                    if (timed) {
                        long remaining = nanos - (System.nanoTime() - started);
                        if (remaining <= 0) return futures;
                        future.get(remaining, TimeUnit.NANOSECONDS);
                    } else future.get();
                } catch (ExecutionException | java.util.concurrent.CancellationException ignored) {
                    // Every submitted task is awaited regardless of its result.
                } catch (TimeoutException expired) { return futures; }
            }
            finished = true;
            return futures;
        } finally {
            if (!finished) for (Future<T> future : futures) future.cancel(true);
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
        if (Thread.interrupted()) throw new InterruptedException();
        long started = System.nanoTime();
        Completion<T> completion = new Completion<>(tasks.size());
        ArrayList<Future<T>> futures = new ArrayList<>(tasks.size());
        try {
            for (Callable<T> task : tasks) {
                Objects.requireNonNull(task);
                FutureTask<T> future = new FutureTask<>(task) {
                    @Override protected void done() {
                        synchronized (completion) { completion.ready.addLast(this); completion.notifyAll(); }
                    }
                };
                futures.add(future);
                execute(future);
            }
            ExecutionException last = null;
            while (completion.remaining != 0) {
                Future<T> future;
                synchronized (completion) {
                    if (completion.ready.isEmpty()) {
                        while (completion.ready.isEmpty()) {
                            if (!timed) completion.wait();
                            else {
                                if (nanos <= 0) throw new TimeoutException();
                                long remaining = nanos - (System.nanoTime() - started);
                                if (remaining <= 0) throw new TimeoutException();
                                completion.wait(remaining / 1_000_000, (int)(remaining % 1_000_000));
                            }
                        }
                    }
                    future = completion.ready.removeFirst();
                    completion.remaining--;
                }
                try { return future.get(); }
                catch (ExecutionException failed) { last = failed; }
                catch (java.util.concurrent.CancellationException cancelled) { last = new ExecutionException(cancelled); }
            }
            throw last == null ? new ExecutionException(new IllegalStateException()) : last;
        } finally { for (Future<T> future : futures) future.cancel(true); }
    }

    private static final class Completion<T> {
        final ArrayDeque<Future<T>> ready = new ArrayDeque<>();
        int remaining;
        Completion(int count) { remaining = count; }
    }
}
