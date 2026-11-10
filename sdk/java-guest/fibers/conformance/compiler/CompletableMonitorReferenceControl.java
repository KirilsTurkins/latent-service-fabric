import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

public final class CompletableMonitorReferenceControl {
    static void require(boolean condition, String message) { if (!condition) throw new AssertionError(message); }
    static void await(CountDownLatch latch, String message) throws InterruptedException {
        require(latch.await(5,TimeUnit.SECONDS), message);
    }
    static void test(String mode) throws Exception {
        CountDownLatch held=new CountDownLatch(1), inspect=new CountDownLatch(1), inspected=new CountDownLatch(1);
        CountDownLatch callback=new CountDownLatch(1), release=new CountDownLatch(1);
        AtomicReference<Throwable> threadFailure=new AtomicReference<>();
        RuntimeException plain=new RuntimeException("underlying") {
            @Override public String toString() {
                if (mode.startsWith("unwrap")) return super.toString();
                callback.countDown();
                try { if (!release.await(5,TimeUnit.SECONDS)) throw new AssertionError("callback-timeout"); }
                catch (InterruptedException error) { throw new AssertionError(error); }
                return "controlled-cause";
            }
        };
        CompletionException wrapped=new CompletionException("wrapped",plain) {
            @Override public synchronized Throwable getCause() {
                callback.countDown();
                try { if (!release.await(5,TimeUnit.SECONDS)) throw new AssertionError("callback-timeout"); }
                catch (InterruptedException error) { throw new AssertionError(error); }
                return plain;
            }
        };
        CompletableFuture<Integer> future=new CompletableFuture<>();
        future.completeExceptionally(mode.startsWith("unwrap") ? wrapped : plain);
        Thread holder=new Thread(() -> {
            synchronized (future) {
                held.countDown();
                try { await(inspect,"inspect-not-signalled"); require(future.isDone(),"future-not-done"); }
                catch (Throwable error) { threadFailure.set(error); }
                finally { inspected.countDown(); }
            }
        }, "completable-monitor-holder");
        Thread getter=new Thread(() -> {
            try {
                switch (mode) {
                case "unwrap-get", "execution-get" -> future.get();
                case "unwrap-timed", "execution-timed" -> future.get(0,TimeUnit.NANOSECONDS);
                case "unwrap-exception-now" -> {
                    if (future.exceptionNow()!=plain) throw new AssertionError("exception-now-cause");
                    return;
                }
                case "wrap-join" -> future.join();
                case "wrap-get-now" -> future.getNow(42);
                default -> throw new AssertionError("unknown-mode");
                }
                throw new AssertionError("failed-future-returned");
            } catch (ExecutionException error) {
                if (error.getCause()!=plain) threadFailure.set(new AssertionError("execution-cause"));
            } catch (CompletionException error) {
                if (error.getCause()!=plain) threadFailure.set(new AssertionError("completion-cause"));
            } catch (Throwable error) { threadFailure.set(error); }
        }, "completable-failure-getter");
        boolean entered=false, independent=false;
        try {
            holder.start(); await(held,"future-monitor-not-held"); getter.start();
            entered=callback.await(1,TimeUnit.SECONDS);
            inspect.countDown();
            independent=inspected.await(1,TimeUnit.SECONDS);
        } finally {
            inspect.countDown(); release.countDown();
            holder.join(5000); getter.join(5000);
        }
        require(!holder.isAlive() && !getter.isAlive(),"threads-not-retired");
        if (threadFailure.get()!=null) throw new AssertionError("operation-failed",threadFailure.get());
        require(entered && independent,"callback-lock:"+mode);
    }
    static void completion() throws Exception {
        CompletableFuture<Integer> source=new CompletableFuture<>();
        CompletableFuture<Integer> result=source.thenApply(value -> value+1);
        CountDownLatch entered=new CountDownLatch(1), finished=new CountDownLatch(1);
        AtomicReference<Throwable> error=new AtomicReference<>();
        Thread completer=new Thread(() -> {
            entered.countDown();
            try { require(source.complete(41),"completion-refused"); }
            catch (Throwable failure) { error.set(failure); }
            finally { finished.countDown(); }
        },"completable-reference-completer");
        boolean complete=false;
        try {
            synchronized (source) {
                completer.start(); await(entered,"completer-not-started");
                complete=finished.await(1,TimeUnit.SECONDS);
            }
        } finally { completer.join(5000); }
        require(!completer.isAlive() && error.get()==null && result.get()==42,"completion-outcome");
        require(complete,"completion-blocked-by-public-monitor");
    }
    public static void main(String[] args) throws Exception {
        completion();
        for (String mode : new String[]{"unwrap-get","unwrap-timed","unwrap-exception-now",
                "execution-get","execution-timed","wrap-join","wrap-get-now"}) test(mode);
        System.out.println("COMPLETABLE_FUTURE_MONITOR_REFERENCE PASS completion;exception-callbacks=7");
    }
}
