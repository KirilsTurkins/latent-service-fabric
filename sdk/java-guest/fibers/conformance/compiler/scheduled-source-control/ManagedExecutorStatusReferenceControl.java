import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/** JDK and SDK source observations, not signed guest evidence. */
public final class ManagedExecutorStatusReferenceControl {
    private static void require(boolean value, String message) { if (!value) throw new AssertionError(message); }
    private static void await(CountDownLatch latch, String message) throws InterruptedException {
        require(latch.await(5, TimeUnit.SECONDS), message);
    }
    private static void publicMonitor(String mode) throws Exception {
        ExecutorService pool = Executors.newSingleThreadExecutor();
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicBoolean observed = new AtomicBoolean();
        AtomicReference<Throwable> failure = new AtomicReference<>();
        Thread reader = new Thread(() -> {
            try {
                boolean shutdown = pool.isShutdown(), terminated = pool.isTerminated();
                observed.set(switch (mode) {
                    case "open" -> !shutdown && !terminated;
                    case "shutdown" -> shutdown && !terminated;
                    case "terminated" -> shutdown && terminated;
                    default -> false;
                });
            } catch (Throwable error) { failure.set(error); }
        }, "executor-status-reader");
        try {
            if (mode.equals("shutdown")) {
                pool.execute(() -> {
                    entered.countDown();
                    while (true) try { release.await(); return; } catch (InterruptedException ignored) { }
                });
                await(entered, "callback-not-entered"); pool.shutdown();
            } else if (mode.equals("terminated")) {
                pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS), "pool-not-terminated");
            }
            synchronized (pool) {
                reader.start(); reader.join(2000);
                require(!reader.isAlive() && observed.get() && failure.get() == null, "public-monitor-blocked-" + mode);
            }
        } finally {
            release.countDown(); reader.join(5000); pool.shutdown();
            require(pool.awaitTermination(5, TimeUnit.SECONDS), "cleanup-not-terminated");
        }
        require(!reader.isAlive(), "reader-not-retired");
    }
    private static void interruptHook() throws Exception {
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        AtomicReference<Thread> reader = new AtomicReference<>();
        AtomicBoolean visible = new AtomicBoolean(), observed = new AtomicBoolean();
        ExecutorService pool = Executors.newSingleThreadExecutor(target -> new Thread(target, "executor-status-worker") {
            @Override public void interrupt() {
                CountDownLatch started = new CountDownLatch(1), inspected = new CountDownLatch(1);
                Thread probe = new Thread(() -> {
                    started.countDown();
                    try { observed.set(selected.get().isShutdown() && !selected.get().isTerminated()); }
                    finally { inspected.countDown(); }
                }, "executor-interrupt-inspector");
                reader.set(probe); probe.start();
                try { await(started, "inspector-not-started"); visible.set(inspected.await(2, TimeUnit.SECONDS) && observed.get()); }
                catch (InterruptedException error) { throw new AssertionError(error); }
                super.interrupt();
            }
        });
        selected.set(pool);
        try {
            pool.execute(() -> {
                entered.countDown();
                while (true) try { release.await(); return; } catch (InterruptedException ignored) { }
            });
            await(entered, "interrupt-worker-not-entered");
            require(pool.shutdownNow().isEmpty(), "unexpected-queued-work");
            require(visible.get(), "status-blocked-by-interrupt-hook");
        } finally {
            release.countDown(); require(pool.awaitTermination(5, TimeUnit.SECONDS), "interrupt-pool-not-retired");
            if (reader.get() != null) reader.get().join(5000);
        }
        require(reader.get() != null && !reader.get().isAlive(), "interrupt-inspector-not-retired");
    }
    public static void main(String[] args) throws Exception {
        for (String mode : new String[] {"open", "shutdown", "terminated"}) publicMonitor(mode);
        interruptHook();
        System.out.println("MANAGED_EXECUTOR_STATUS PASS open;shutdown;terminated;interrupt-hook");
    }
}
