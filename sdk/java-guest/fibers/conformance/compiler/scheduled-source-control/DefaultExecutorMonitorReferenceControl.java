import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

public final class DefaultExecutorMonitorReferenceControl {
    private static void test(String mode, boolean sourcePort) throws Exception {
        CompletableFuture<Integer> source=new CompletableFuture<>();
        Executor executor=source.defaultExecutor();
        if (mode.equals("warm")) {
            CountDownLatch warmed=new CountDownLatch(1);
            executor.execute(warmed::countDown);
            if (!warmed.await(5,TimeUnit.SECONDS)) throw new AssertionError("warm-task-not-run");
        }
        CompletableFuture<Integer> result=source.thenApplyAsync(value -> value+1,executor);
        CountDownLatch entered=new CountDownLatch(1),finished=new CountDownLatch(1);
        AtomicReference<Throwable> failure=new AtomicReference<>();
        Thread completer=new Thread(() -> {
            entered.countDown();
            try { if (!source.complete(41)) throw new AssertionError("completion-refused"); }
            catch (Throwable error) { failure.set(error); }
            finally { finished.countDown(); }
        },"default-executor-completer");
        boolean completed=false;
        try {
            try {
                synchronized (executor) {
                    completer.start();
                    if (!entered.await(5,TimeUnit.SECONDS)) throw new AssertionError("completer-not-started");
                    completed=finished.await(1,TimeUnit.SECONDS);
                }
            } finally { completer.join(5000); }
            if (completer.isAlive() || failure.get()!=null || result.get(5,TimeUnit.SECONDS)!=42)
                throw new AssertionError("default-executor-outcome",failure.get());
            if (!completed) throw new AssertionError("default-executor-public-monitor-blocked:"+mode);
        } finally {
            if (sourcePort) {
                java.lang.reflect.Field field=executor.getClass().getDeclaredField("pool");
                field.setAccessible(true);
                java.util.concurrent.ExecutorService pool=(java.util.concurrent.ExecutorService)field.get(executor);
                if (pool!=null) {
                    pool.shutdown();
                    if (!pool.awaitTermination(5,TimeUnit.SECONDS)) throw new AssertionError("pool-not-retired");
                }
                Class.forName("dev.latent.guest.runtime.Activation").getMethod("idle").invoke(null);
            }
        }
    }
    public static void main(String[] args) throws Exception {
        boolean sourcePort=args.length==1 && args[0].equals("source");
        test("cold",sourcePort); test("warm",sourcePort);
        System.out.println("DEFAULT_EXECUTOR_MONITOR_REFERENCE PASS cold;warm");
    }
}
