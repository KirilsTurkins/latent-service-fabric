package dev.latent.guest.runtime.concurrent;

import java.util.Objects;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.ThreadFactory;

/** Owned factories preserve independent FIFO pools and requested parallelism. */
public final class Executors {
    private static int nextPool;
    private Executors() { }
    public static ExecutorService newFixedThreadPool(int threads) { return newFixedThreadPool(threads, defaultThreadFactory()); }
    public static ExecutorService newFixedThreadPool(int threads, ThreadFactory factory) { return new ManagedExecutor(threads, factory); }
    public static ExecutorService newSingleThreadExecutor() { return newFixedThreadPool(1); }
    public static ExecutorService newSingleThreadExecutor(ThreadFactory factory) { return newFixedThreadPool(1, factory); }
    public static ThreadFactory defaultThreadFactory() {
        int pool = ++nextPool;
        return new ThreadFactory() {
            private int nextThread;
            @Override public Thread newThread(Runnable task) {
                Thread thread = new Thread(task, "pool-" + pool + "-thread-" + ++nextThread);
                thread.setDaemon(false);
                thread.setPriority(Thread.NORM_PRIORITY);
                return thread;
            }
        };
    }
    public static <T> Callable<T> callable(Runnable task, T result) {
        Objects.requireNonNull(task);
        return () -> { task.run(); return result; };
    }
    public static Callable<Object> callable(Runnable task) { return callable(task, null); }
}
