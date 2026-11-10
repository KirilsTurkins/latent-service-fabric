import dev.latent.guest.runtime.Activation;
import java.util.Collection;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** JDK and SDK interface defaults around real source-port workers, not a guest. */
public final class ExecutorCloseInterruptControl {
    private static void require(boolean condition) {
        if (!condition) throw new AssertionError("executor-close-interrupt");
    }
    private static void await(CountDownLatch latch) throws InterruptedException {
        require(latch.await(5, TimeUnit.SECONDS));
    }
    private abstract static class Pool {
        final java.util.concurrent.ExecutorService delegate =
            dev.latent.guest.runtime.concurrent.Executors.newSingleThreadExecutor();
        final AtomicInteger shutdowns = new AtomicInteger(), stops = new AtomicInteger(), waits = new AtomicInteger();
        final CountDownLatch[] waiting = { new CountDownLatch(1), new CountDownLatch(1), new CountDownLatch(1) };
        public void execute(Runnable command) { delegate.execute(command); }
        public void shutdown() { shutdowns.incrementAndGet(); delegate.shutdown(); }
        public List<Runnable> shutdownNow() { stops.incrementAndGet(); return delegate.shutdownNow(); }
        public boolean isShutdown() { return delegate.isShutdown(); }
        public boolean isTerminated() { return delegate.isTerminated(); }
        public boolean awaitTermination(long timeout, TimeUnit unit) throws InterruptedException {
            int number = waits.incrementAndGet();
            if (number <= waiting.length) waiting[number - 1].countDown();
            return delegate.awaitTermination(timeout, unit);
        }
        public <T> Future<T> submit(Callable<T> task) { return delegate.submit(task); }
        public <T> Future<T> submit(Runnable task, T value) { return delegate.submit(task, value); }
        public Future<?> submit(Runnable task) { return delegate.submit(task); }
        public <T> List<Future<T>> invokeAll(Collection<? extends Callable<T>> tasks) throws InterruptedException {
            return delegate.invokeAll(tasks);
        }
        public <T> List<Future<T>> invokeAll(Collection<? extends Callable<T>> tasks, long timeout, TimeUnit unit)
                throws InterruptedException { return delegate.invokeAll(tasks, timeout, unit); }
        public <T> T invokeAny(Collection<? extends Callable<T>> tasks) throws InterruptedException, ExecutionException {
            return delegate.invokeAny(tasks);
        }
        public <T> T invokeAny(Collection<? extends Callable<T>> tasks, long timeout, TimeUnit unit)
                throws InterruptedException, ExecutionException, TimeoutException {
            return delegate.invokeAny(tasks, timeout, unit);
        }
    }
    private static final class Reference extends Pool implements java.util.concurrent.ExecutorService { }
    private static final class Source extends Pool implements dev.latent.guest.runtime.concurrent.ExecutorService { }
    private static Pool pool(String implementation) {
        return implementation.equals("jdk") ? new Reference() : new Source();
    }
    private static void close(Pool pool) throws Exception { ((AutoCloseable)pool).close(); }

    private static void terminated(String implementation) throws Exception {
        Pool pool = pool(implementation);
        pool.delegate.shutdown();
        require(pool.delegate.awaitTermination(5, TimeUnit.SECONDS));
        close(pool);
        require(pool.shutdowns.get() == 0 && pool.stops.get() == 0 && pool.waits.get() == 0);
        Activation.idle();
    }

    private static void drain(String implementation) throws Exception {
        Pool pool = pool(implementation);
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicReference<Throwable> closeFailure = new AtomicReference<>();
        AtomicBoolean restored = new AtomicBoolean();
        Thread closer = new Thread(() -> {
            try { close(pool); restored.set(Thread.currentThread().isInterrupted()); }
            catch (Throwable error) { closeFailure.set(error); }
        });
        pool.execute(() -> {
            entered.countDown();
            try { release.await(); }
            catch (InterruptedException error) { throw new AssertionError(error); }
        });
        try {
            await(entered); closer.start(); await(pool.waiting[0]);
            require(closer.isAlive() && pool.isShutdown() && pool.shutdowns.get() == 1 && pool.stops.get() == 0);
        } finally {
            release.countDown(); closer.join(5000);
            if (closer.isAlive()) { pool.delegate.shutdownNow(); closer.interrupt(); closer.join(1000); }
        }
        require(!closer.isAlive() && closeFailure.get() == null && !restored.get());
        require(pool.delegate.awaitTermination(5, TimeUnit.SECONDS));
        Activation.idle();
    }

    private static void interrupted(String implementation) throws Exception {
        Pool pool = pool(implementation);
        CountDownLatch entered = new CountDownLatch(1), first = new CountDownLatch(1);
        CountDownLatch second = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicReference<Throwable> closeFailure = new AtomicReference<>();
        AtomicBoolean restored = new AtomicBoolean();
        Thread closer = new Thread(() -> {
            try { close(pool); restored.set(Thread.currentThread().isInterrupted()); }
            catch (Throwable error) { closeFailure.set(error); }
        });
        pool.execute(() -> {
            entered.countDown();
            try { new CountDownLatch(1).await(); }
            catch (InterruptedException expected) { }
            finally {
                first.countDown();
                while (true) {
                    try { release.await(); return; }
                    catch (InterruptedException unexpected) { second.countDown(); }
                }
            }
        });
        try {
            await(entered);
            closer.start();
            await(pool.waiting[0]); closer.interrupt();
            await(first); await(pool.waiting[1]); closer.interrupt();
            // The third wait proves the closer processed both interruptions
            // while the original worker is still held in its finally path.
            await(pool.waiting[2]);
            if (pool.stops.get() != 1) await(second);
            require(pool.shutdowns.get() == 1 && pool.stops.get() == 1 && second.getCount() == 1);
        } finally {
            release.countDown();
            closer.join(5000);
            // Failure-path cleanup cannot strand either real host thread.
            if (closer.isAlive() || !pool.delegate.isTerminated()) {
                pool.delegate.shutdownNow();
                if (closer.isAlive()) closer.interrupt();
                closer.join(1000);
            }
        }
        require(!closer.isAlive() && closeFailure.get() == null && restored.get() && second.getCount() == 1);
        require(pool.delegate.awaitTermination(5, TimeUnit.SECONDS));
        Activation.idle();
    }
    public static void main(String[] args) throws Exception {
        require(args.length == 2 && (args[0].equals("jdk") || args[0].equals("source")));
        switch (args[1]) {
            case "terminated" -> terminated(args[0]);
            case "drain" -> drain(args[0]);
            case "interrupted" -> interrupted(args[0]);
            default -> throw new AssertionError("unsupported-mode");
        }
        System.out.println("EXECUTOR_CLOSE_INTERRUPT PASS " + args[0] + " " + args[1]);
    }
}
