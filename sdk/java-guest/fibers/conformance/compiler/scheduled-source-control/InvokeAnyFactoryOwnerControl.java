import dev.latent.generated.Bindings;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.AbstractExecutorService;
import dev.latent.guest.runtime.concurrent.Executors;
import dev.latent.guest.runtime.concurrent.ScheduledThreadPoolExecutor;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.RunnableFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Synthetic host-ledger controls for invokeAny's custom-result delivery. */
public final class InvokeAnyFactoryOwnerControl {
    private static void require(boolean value, String message) { if (!value) throw new AssertionError(message); }
    private static void await(CountDownLatch latch) throws InterruptedException {
        require(latch.await(5, TimeUnit.SECONDS), "latch-timeout");
    }
    private static String counts() {
        return Activation.count(Bindings.LatentRuntimeActivationOwnerKind.Executor) + ":"
            + Activation.count(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork) + ":"
            + Activation.count(Bindings.LatentRuntimeActivationOwnerKind.Result);
    }
    private static final class Factory extends AbstractExecutorService {
        final ExecutorService pool;
        final boolean acceptThenThrow, wrapped;
        int factories, cancellations;
        RunnableFuture<?> lastCreated;
        Runnable lastDelivery;
        Factory(ExecutorService pool, boolean acceptThenThrow) { this(pool, acceptThenThrow, true); }
        Factory(ExecutorService pool, boolean acceptThenThrow, boolean wrapped) {
            this.pool = pool; this.acceptThenThrow = acceptThenThrow; this.wrapped = wrapped;
        }
        @Override protected <T> RunnableFuture<T> newTaskFor(Callable<T> task) {
            factories++;
            RunnableFuture<T> inner = super.newTaskFor(task);
            lastCreated = inner;
            if (!wrapped) return inner;
            return new RunnableFuture<>() {
                @Override public void run() { inner.run(); }
                @Override public boolean cancel(boolean interrupt) { cancellations++; return inner.cancel(interrupt); }
                @Override public boolean isCancelled() { return inner.isCancelled(); }
                @Override public boolean isDone() { return inner.isDone(); }
                @Override public T get() throws InterruptedException, ExecutionException { return inner.get(); }
                @Override public T get(long n, TimeUnit unit) throws InterruptedException, ExecutionException, TimeoutException {
                    return inner.get(n, unit);
                }
            };
        }
        @Override public void execute(Runnable task) {
            lastDelivery = task;
            pool.execute(task);
            if (acceptThenThrow) throw new RejectedExecutionException("after-accept");
        }
        @Override public void shutdown() { pool.shutdown(); }
        @Override public List<Runnable> shutdownNow() { return pool.shutdownNow(); }
        @Override public boolean isShutdown() { return pool.isShutdown(); }
        @Override public boolean isTerminated() { return pool.isTerminated(); }
        @Override public boolean awaitTermination(long n, TimeUnit unit) throws InterruptedException { return pool.awaitTermination(n, unit); }
    }
    private static ExecutorService gated(CountDownLatch ready, CountDownLatch release, boolean scheduled) {
        java.util.concurrent.ThreadFactory factory = target -> new Thread(() -> {
            ready.countDown();
            try { await(release); } catch (InterruptedException error) { throw new AssertionError(error); }
            target.run();
        }, "invoke-any-factory-worker");
        return scheduled ? new ScheduledThreadPoolExecutor(1, factory) : Executors.newFixedThreadPool(1, factory);
    }
    private static void pending(boolean rejected, boolean scheduled) throws Exception {
        CountDownLatch ready = new CountDownLatch(1), release = new CountDownLatch(1);
        ExecutorService pool = gated(ready, release, scheduled);
        Factory factory = new Factory(pool, rejected);
        AtomicInteger calls = new AtomicInteger();
        Callable<Integer> task = () -> { calls.incrementAndGet(); return 42; };
        try {
            try {
                factory.invokeAny(List.of(task, task), 0, TimeUnit.NANOSECONDS);
                throw new AssertionError("expected-failure");
            } catch (RejectedExecutionException error) {
                require(rejected && "after-accept".equals(error.getMessage()), "rejection");
            } catch (TimeoutException error) { require(!rejected, "unexpected-timeout"); }
            await(ready);
            int number = rejected ? 1 : 2;
            require(factory.factories == number && factory.cancellations == number && calls.get() == 0, "cancellation");
            require(counts().equals("1:" + number + ":" + (number * (scheduled ? 2 : 1)))
                    && ((Activation.ManagedPool)pool).hasPendingWork(), "pending-owners-" + counts());
            release.countDown(); pool.shutdown();
            require(pool.awaitTermination(5, TimeUnit.SECONDS), "termination");
            Activation.idle(); require(calls.get() == 0 && counts().equals("0:0:0"), "retirement-" + counts());
        } finally { release.countDown(); pool.shutdownNow(); }
    }
    private static void denied(boolean inner, boolean wrapped, boolean scheduled) throws Exception {
        ExecutorService pool = scheduled ? new ScheduledThreadPoolExecutor(1) : Executors.newFixedThreadPool(1);
        Factory factory = new Factory(pool, false, wrapped);
        AtomicInteger calls = new AtomicInteger();
        AtomicReference<Throwable> outcome = new AtomicReference<>();
        Activation.denyNext = "Result";
        Activation.denyMatchesAfter = (inner ? 1 : 0) + (scheduled ? 1 : 0);
        Thread caller = new Thread(() -> {
            try { factory.invokeAny(List.of(() -> { calls.incrementAndGet(); return 42; })); }
            catch (Throwable error) { outcome.set(error); }
        }, "invoke-any-factory-caller");
        try {
            caller.start(); caller.join(5000);
            require(!caller.isAlive(), "admission-denial-stranded-caller");
            Throwable error = outcome.get();
            if (inner) {
                require(error instanceof ExecutionException && error.getCause() instanceof IllegalStateException
                        && "source-owner-admission-denied".equals(error.getCause().getMessage()), "inner-denial-" + error);
            } else require(error instanceof IllegalStateException && "source-owner-admission-denied".equals(error.getMessage()),
                    "delivery-denial-" + error);
            require(calls.get() == 0 && factory.factories == 1 && factory.lastCreated.isCancelled()
                    && factory.cancellations == (wrapped ? 1 : 0), "denied-work");
            pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS), "termination");
            Activation.idle(); require(counts().equals("0:0:0"), "denial-retirement-" + counts());
        } finally { caller.interrupt(); caller.join(5000); pool.shutdownNow(); }
    }
    private static void running(boolean scheduled) throws Exception {
        ExecutorService pool = scheduled ? new ScheduledThreadPoolExecutor(2) : Executors.newFixedThreadPool(2);
        Factory factory = new Factory(pool, false);
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1), returned = new CountDownLatch(1);
        AtomicBoolean physical = new AtomicBoolean();
        AtomicInteger interrupts = new AtomicInteger();
        AtomicReference<Object> outcome = new AtomicReference<>();
        Thread caller = new Thread(() -> {
            Callable<Integer> held = () -> {
                physical.set(true); entered.countDown();
                while (release.getCount() != 0) try { release.await(); }
                catch (InterruptedException error) { interrupts.incrementAndGet(); }
                physical.set(false); return 1;
            };
            Callable<Integer> winner = () -> { await(entered); return 42; };
            try { outcome.set(factory.invokeAny(List.of(held, winner))); }
            catch (Throwable error) { outcome.set(error); }
            finally { returned.countDown(); }
        }, "invoke-any-factory-parallel-caller");
        try {
            caller.start(); await(entered); await(returned); caller.join(5000);
            require(!caller.isAlive() && Integer.valueOf(42).equals(outcome.get()) && physical.get(), "result-" + outcome.get());
            long deadline = System.nanoTime() + 5_000_000_000L;
            while (!counts().equals(scheduled ? "1:1:3" : "1:0:2") || interrupts.get() == 0) {
                require(System.nanoTime() - deadline < 0, "running-owners-" + counts()); Thread.sleep(1);
            }
            require(((Activation.ManagedPool)pool).hasPendingWork(), "running-not-pending");
            pool.shutdown(); require(!pool.isTerminated(), "retired-before-physical-return");
            release.countDown(); require(pool.awaitTermination(5, TimeUnit.SECONDS), "termination");
            Activation.idle(); require(counts().equals("0:0:0"), "running-retirement-" + counts());
        } finally { release.countDown(); caller.join(5000); pool.shutdownNow(); }
    }
    private static void withdraw(boolean wrapped) throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(1, target -> null);
        Factory factory = new Factory(pool, false, wrapped);
        AtomicInteger calls = new AtomicInteger();
        AtomicReference<Throwable> outcome = new AtomicReference<>();
        Thread caller = new Thread(() -> {
            try { factory.invokeAny(List.of(() -> { calls.incrementAndGet(); return 42; })); }
            catch (Throwable error) { outcome.set(error); }
        }, "invoke-any-withdrawn-caller");
        try {
            var queueField = pool.getClass().getDeclaredField("queue"); queueField.setAccessible(true);
            caller.start();
            long deadline = System.nanoTime() + 5_000_000_000L;
            while (true) {
                boolean queued;
                synchronized (pool) { queued = !((java.util.ArrayDeque<?>)queueField.get(pool)).isEmpty(); }
                if (queued && counts().equals("1:1:1")) break;
                require(System.nanoTime() - deadline < 0, "withdraw-not-queued-" + counts()); Thread.sleep(1);
            }
            List<Runnable> removed = pool.shutdownNow();
            require(removed.size() == 1 && removed.get(0) instanceof RunnableFuture<?>
                    && removed.get(0) != factory.lastCreated, "withdrawn-delivery-identity");
            caller.interrupt(); caller.join(5000);
            require(!caller.isAlive() && outcome.get() instanceof InterruptedException
                    && factory.lastCreated.isCancelled() && calls.get() == 0, "withdrawn-caller");
            require(counts().equals("0:0:0"), "withdrawn-owners-" + counts());
            Runnable delivery = removed.get(0);
            delivery.run();
            require(calls.get() == 0 && ((RunnableFuture<?>)delivery).isDone(), "withdrawn-replay");
            for (String name : List.of("entry", "completion")) {
                var field = delivery.getClass().getDeclaredField(name); field.setAccessible(true);
                require(field.get(delivery) == null, "withdrawn-retained-" + name);
            }
            Activation.idle(); require(counts().equals("0:0:0"), "withdrawn-replay-owners-" + counts());
        } finally { caller.interrupt(); caller.join(5000); pool.shutdownNow(); }
    }
    private static void deliverySettlement(boolean lost) throws Exception {
        AtomicReference<Throwable> uncaught = new AtomicReference<>();
        AtomicReference<Thread> worker = new AtomicReference<>();
        ExecutorService pool = Executors.newFixedThreadPool(1, task -> {
            Thread thread = new Thread(task, "invoke-any-settlement-worker");
            thread.setUncaughtExceptionHandler((ignored, error) -> uncaught.set(error)); worker.set(thread); return thread;
        });
        Factory factory = new Factory(pool, false, false);
        AtomicInteger calls = new AtomicInteger();
        if (lost) { Activation.loseCloseAckNext = "Result"; Activation.loseCloseAckAfter = 1; }
        else { Activation.denyCloseNext = "Result"; Activation.denyCloseAfter = 1; }
        try {
            require(factory.<Integer>invokeAny(List.of(() -> { calls.incrementAndGet(); return 42; })) == 42,
                    "settlement-result");
            pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS), "settlement-termination");
            worker.get().join(5000);
            require(!worker.get().isAlive() && uncaught.get() instanceof IllegalStateException,
                    "settlement-error-not-observed");
            require(Activation.poisoned && calls.get() == 1 && Activation.failedLeaseAttempts() == 1,
                    "settlement-not-fenced");
            require(counts().equals(lost ? "0:0:0" : "0:0:1"), "settlement-counts-" + counts());
            var owner = dev.latent.guest.runtime.concurrent.FutureTask.class.getDeclaredField("owner");
            owner.setAccessible(true);
            require(owner.get(factory.lastDelivery) != null, "settlement-original-not-retained");
            int attempts = Activation.closeAttempts(Bindings.LatentRuntimeActivationOwnerKind.Result);
            require(!((RunnableFuture<?>)factory.lastDelivery).cancel(false)
                    && attempts == Activation.closeAttempts(Bindings.LatentRuntimeActivationOwnerKind.Result), "settlement-retried");
        } finally { pool.shutdownNow(); }
    }
    public static void main(String[] args) throws Exception {
        switch (args[0]) {
            case "timeout" -> pending(false, false);
            case "accepted-throw" -> pending(true, false);
            case "scheduled-timeout" -> pending(false, true);
            case "scheduled-accepted-throw" -> pending(true, true);
            case "delivery-denied" -> denied(false, true, false);
            case "inner-denied" -> denied(true, true, false);
            case "default-delivery-denied" -> denied(false, false, false);
            case "default-inner-denied" -> denied(true, false, false);
            case "scheduled-delivery-denied" -> denied(false, true, true);
            case "scheduled-inner-denied" -> denied(true, true, true);
            case "scheduled-default-inner-denied" -> denied(true, false, true);
            case "running" -> running(false);
            case "scheduled-running" -> running(true);
            case "withdraw" -> withdraw(true);
            case "default-withdraw" -> withdraw(false);
            case "settlement-denied" -> deliverySettlement(false);
            case "settlement-lost" -> deliverySettlement(true);
            default -> throw new IllegalArgumentException("mode");
        }
        System.out.println("INVOKE_ANY_FACTORY_OWNER PASS " + args[0]);
    }
}
