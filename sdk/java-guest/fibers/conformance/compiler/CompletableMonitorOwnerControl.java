import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.CompletableFuture;
import java.util.concurrent.CancellationException;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

public final class CompletableMonitorOwnerControl {
    static void require(boolean value,String message) { if (!value) throw new AssertionError(message); }
    static void await(CountDownLatch latch,String message) throws InterruptedException {
        require(latch.await(5,TimeUnit.SECONDS),message);
    }
    static void join(Thread thread) throws InterruptedException {
        thread.join(5000); require(!thread.isAlive(),"thread-not-retired:"+thread.getName());
    }
    static void counts(int queue,int result) {
        require(Activation.queuedOwners()==queue && Activation.resultOwners()==result,"wrong-owner-count");
    }
    static void callbackRetirement() throws Exception {
        CompletableFuture<Integer> source=new CompletableFuture<>();
        CountDownLatch callback=new CountDownLatch(1),release=new CountDownLatch(1),completed=new CountDownLatch(1);
        AtomicReference<Throwable> failure=new AtomicReference<>();
        CompletableFuture<Integer> result=source.thenApply(value -> {
            callback.countDown();
            try { await(release,"callback-release"); } catch (InterruptedException error) { throw new AssertionError(error); }
            return value+1;
        });
        Thread completer=new Thread(() -> {
            try { require(source.complete(41),"source-completion-refused"); }
            catch (Throwable error) { failure.set(error); }
            finally { completed.countDown(); }
        },"completable-owner-completer");
        boolean entered=false;
        try {
            synchronized (source) {
                completer.start(); entered=callback.await(1,TimeUnit.SECONDS);
                counts(1,1);
                release.countDown();
                if (entered) await(completed,"source-completion-not-finished");
            }
        } finally { release.countDown(); join(completer); }
        require(entered,"callback-blocked-by-public-source-monitor");
        require(failure.get()==null && result.get()==42,"completion-outcome");
        counts(0,0); Activation.cleanup();
    }
    static void cancelledQueuedRetirement() throws Exception {
        CompletableFuture<Integer> source=new CompletableFuture<>();
        AtomicReference<Runnable> queued=new AtomicReference<>();
        Executor capture=command -> require(queued.compareAndSet(null,command),"duplicate-dispatch");
        AtomicInteger callbacks=new AtomicInteger();
        CompletableFuture<Integer> result=source.thenApplyAsync(value -> { callbacks.incrementAndGet(); return value+1; },capture);
        require(source.complete(41),"source-completion-refused");
        Runnable command=queued.get(); require(command!=null,"action-not-queued");
        counts(1,1);
        require(result.cancel(false),"cancel-refused");
        counts(1,1);
        CountDownLatch finished=new CountDownLatch(1);
        AtomicReference<Throwable> failure=new AtomicReference<>();
        Thread runner=new Thread(() -> {
            try { command.run(); } catch (Throwable error) { failure.set(error); }
            finally { finished.countDown(); }
        },"completable-queued-runner");
        boolean retired=false;
        try {
            synchronized (result) { runner.start(); retired=finished.await(1,TimeUnit.SECONDS); }
        } finally { join(runner); }
        require(retired,"cancelled-run-blocked-by-public-destination-monitor");
        require(failure.get()==null && callbacks.get()==0 && result.isCancelled(),"cancelled-action-outcome");
        try { result.join(); throw new AssertionError("cancelled-join-returned"); }
        catch (CancellationException expected) { }
        counts(0,0); Activation.cleanup();
    }
    static void subscribeRace() throws Exception {
        for (int i=0;i<24;i++) {
            CompletableFuture<Integer> source=new CompletableFuture<>();
            CountDownLatch go=new CountDownLatch(1); AtomicInteger callbacks=new AtomicInteger();
            AtomicReference<Throwable> failure=new AtomicReference<>();
            Thread completer=new Thread(() -> {
                try { await(go,"race-go"); require(source.complete(41),"race-completion-refused"); }
                catch (Throwable error) { failure.set(error); }
            },"completable-race-completer");
            completer.start();
            CompletableFuture<Integer> result;
            try {
                go.countDown();
                result=source.thenApply(value -> { callbacks.incrementAndGet(); return value+1; });
                require(result.get(5,TimeUnit.SECONDS)==42,"race-result");
            } finally { go.countDown(); join(completer); }
            require(failure.get()==null && callbacks.get()==1,"race-callback-count");
            counts(0,0); Activation.cleanup();
        }
    }
    public static void main(String[] args) throws Exception {
        callbackRetirement(); cancelledQueuedRetirement(); subscribeRace();
        System.out.println("COMPLETABLE_FUTURE_MONITOR_OWNER PASS callback-retirement;cancelled-queued-retirement;subscribe-race");
    }
}
