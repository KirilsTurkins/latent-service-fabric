import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.Executors;
import dev.latent.guest.runtime.concurrent.FutureTask;
import dev.latent.guest.runtime.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Actual SDK bodies with a private host ledger; not a guest execution. */
public final class FutureTaskMonitorOwnerControl {
    private static void require(boolean value, String message) { if (!value) throw new AssertionError(message); }
    private static void await(CountDownLatch latch, String message) {
        try { require(latch.await(4,TimeUnit.SECONDS),message); }
        catch (InterruptedException error) { throw new AssertionError(message,error); }
    }
    private static int count(LatentRuntimeActivationOwnerKind kind) { return Activation.count(kind); }
    private static void retired() throws Exception {
        long end=System.nanoTime()+TimeUnit.SECONDS.toNanos(4);
        while ((count(LatentRuntimeActivationOwnerKind.QueuedWork)!=0 ||
                count(LatentRuntimeActivationOwnerKind.Result)!=0) && System.nanoTime()<end) Thread.sleep(1);
        require(count(LatentRuntimeActivationOwnerKind.QueuedWork)==0 &&
                count(LatentRuntimeActivationOwnerKind.Result)==0,"original-owners-not-retired");
    }
    private static void managed() throws Exception {
        ExecutorService pool=Executors.newSingleThreadExecutor();
        CountDownLatch entered=new CountDownLatch(1), release=new CountDownLatch(1), submitted=new CountDownLatch(1);
        AtomicReference<Throwable> failure=new AtomicReference<>();
        FutureTask<Integer> future=new FutureTask<>(() -> { entered.countDown(); await(release,"callback-release"); return 42; });
        Thread submitter=new Thread(() -> {
            try { pool.execute(future); } catch (Throwable error) { failure.set(error); }
            finally { submitted.countDown(); }
        });
        try {
            synchronized (future) {
                submitter.start();
                await(submitted,"submission-blocked-by-public-future-monitor");
                require(failure.get()==null,"submission-failed");
                await(entered,"callback-not-entered");
                // ManagedExecutor retires the queue owner on dispatch; the
                // original Result remains held until the running callback exits.
                require(count(LatentRuntimeActivationOwnerKind.QueuedWork)==0 &&
                        count(LatentRuntimeActivationOwnerKind.Result)==1,"active-result-not-held");
                release.countDown();
                require(future.get(4,TimeUnit.SECONDS)==42,"future-result");
                retired();
            }
        } finally {
            release.countDown();
            submitter.join(5000);
            pool.shutdownNow();
            require(pool.awaitTermination(5,TimeUnit.SECONDS),"managed-pool-not-retired");
        }
        require(!submitter.isAlive() && failure.get()==null,"managed-submitter-failed");
        Activation.idle();
    }
    private static void scheduled() throws Exception {
        ScheduledThreadPoolExecutor pool=new ScheduledThreadPoolExecutor(1);
        ScheduledFuture<?> future=pool.schedule(() -> { throw new AssertionError("cancelled-task-ran"); },
                                                60,TimeUnit.SECONDS);
        CountDownLatch done=new CountDownLatch(1);
        AtomicReference<Throwable> failure=new AtomicReference<>();
        Thread canceller=new Thread(() -> {
            try { require(future.cancel(false),"scheduled-cancel-result"); }
            catch (Throwable error) { failure.set(error); }
            finally { done.countDown(); }
        });
        try {
            synchronized (future) {
                require(count(LatentRuntimeActivationOwnerKind.QueuedWork)==1 &&
                        count(LatentRuntimeActivationOwnerKind.Result)==1,"scheduled-owners-not-held");
                canceller.start();
                await(done,"scheduled-cancel-blocked-by-public-future-monitor");
                require(failure.get()==null,"scheduled-cancel-failed");
                retired();
            }
        } finally {
            canceller.join(5000);
            pool.shutdownNow();
            require(pool.awaitTermination(5,TimeUnit.SECONDS),"scheduled-pool-not-retired");
        }
        require(!canceller.isAlive() && failure.get()==null,"scheduled-canceller-failed");
        Activation.idle();
    }
    private static void failureReporting() throws Exception {
        CountDownLatch doneEntered=new CountDownLatch(1), doneRelease=new CountDownLatch(1);
        CountDownLatch callbackEntered=new CountDownLatch(1), callbackRelease=new CountDownLatch(1);
        CountDownLatch inspected=new CountDownLatch(1);
        AtomicReference<Throwable> failure=new AtomicReference<>();
        Throwable cause=new RuntimeException() {
            @Override public String toString() {
                callbackEntered.countDown();
                await(callbackRelease,"exception-callback-release");
                return "controlled-exception";
            }
        };
        FutureTask<Integer> future=new FutureTask<Integer>(() -> { throw (RuntimeException) cause; }) {
            @Override protected void done() { doneEntered.countDown(); await(doneRelease,"done-release"); }
        };
        Thread worker=new Thread(future,"exception-owner-worker");
        Thread getter=new Thread(() -> {
            try { future.get(); failure.set(new AssertionError("failed-get-returned")); }
            catch (java.util.concurrent.ExecutionException error) {
                if (error.getCause()!=cause) failure.set(new AssertionError("wrong-cause"));
            } catch (Throwable error) { failure.set(error); }
        },"exception-owner-getter");
        Thread inspector=new Thread(() -> {
            try { require(future.isDone(),"failed-future-not-done"); }
            catch (Throwable error) { failure.set(error); }
            finally { inspected.countDown(); }
        },"exception-owner-inspector");
        boolean independent=false;
        try {
            worker.start(); await(doneEntered,"done-not-entered");
            require(count(LatentRuntimeActivationOwnerKind.Result)==1,"runner-owner-not-held");
            getter.start(); await(callbackEntered,"exception-callback-not-entered");
            inspector.start(); independent=inspected.await(1,TimeUnit.SECONDS);
            require(count(LatentRuntimeActivationOwnerKind.Result)==1,"runner-owner-retired-during-exception-callback");
        } finally {
            callbackRelease.countDown(); doneRelease.countDown();
            worker.join(5000); getter.join(5000); inspector.join(5000);
        }
        require(!worker.isAlive() && !getter.isAlive() && !inspector.isAlive(),"exception-threads-not-retired");
        require(failure.get()==null,"exception-control-failed");
        require(independent,"future-state-locked-by-exception-callback");
        Activation.idle();
    }
    public static void main(String[] args) throws Exception {
        managed(); scheduled(); failureReporting();
        System.out.println("FUTURE_TASK_MONITOR_OWNER PASS managed;active-owners;scheduled;retired-under-public-monitor;failure-owner");
    }
}
