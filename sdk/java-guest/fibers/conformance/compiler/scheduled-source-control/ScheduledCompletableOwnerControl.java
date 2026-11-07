import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.CompletableFuture;
import dev.latent.guest.runtime.concurrent.Executors;
import dev.latent.guest.runtime.concurrent.ScheduledThreadPoolExecutor;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Actual SDK sources with a private ledger, not a signed guest run. */
public final class ScheduledCompletableOwnerControl {
    private static void require(boolean value) {
        if (!value) throw new AssertionError("scheduled-completable-owner");
    }
    private static void held(int queued, int results) {
        require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == queued);
        require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == results);
    }
    private static void await(CountDownLatch latch) throws InterruptedException {
        require(latch.await(5, TimeUnit.SECONDS));
    }
    private static void waitForRelease(CountDownLatch entered, CountDownLatch release) {
        entered.countDown();
        while (true) {
            try { release.await(); return; } catch (InterruptedException ignored) { }
        }
    }
    private static void terminated(java.util.concurrent.ExecutorService pool) throws InterruptedException {
        require(pool.awaitTermination(5, TimeUnit.SECONDS));
    }
    private static void timedWait(Thread thread) {
        long start = System.nanoTime();
        while (thread.getState() != Thread.State.TIMED_WAITING) {
            require(thread.isAlive() && System.nanoTime() - start < TimeUnit.SECONDS.toNanos(5));
            Thread.yield();
        }
    }
    private static void clearedCallback(Object future) throws Exception {
        var action = future.getClass().getDeclaredField("action"); action.setAccessible(true);
        var call = future.getClass().getDeclaredField("runnableCall"); call.setAccessible(true);
        require(action.get(future) == null && call.get(future) == null);
    }
    private static final class RetainingPool extends ScheduledThreadPoolExecutor {
        Runnable saved;
        RetainingPool() { super(1); }
        @Override public void execute(Runnable command) { saved = command; super.execute(command); }
    }
    private static void rejection() throws Exception {
        var closed = new ScheduledThreadPoolExecutor(1);
        closed.shutdown(); terminated(closed);
        AtomicInteger calls = new AtomicInteger();
        try { CompletableFuture.supplyAsync(() -> { calls.incrementAndGet(); return 42; }, closed); throw new AssertionError(); }
        catch (RejectedExecutionException expected) { }
        held(0, 0); require(calls.get() == 0);
        var pending = new CompletableFuture<Integer>();
        try { pending.completeAsync(() -> { calls.incrementAndGet(); return 42; }, closed); throw new AssertionError(); }
        catch (RejectedExecutionException expected) { }
        held(0, 0); require(!pending.isDone() && calls.get() == 0);

        var failedFactory = new ScheduledThreadPoolExecutor(1, command -> null);
        try { CompletableFuture.supplyAsync(() -> 42, failedFactory); throw new AssertionError(); }
        catch (RejectedExecutionException expected) { }
        held(0, 0); failedFactory.shutdownNow(); terminated(failedFactory);

        var deniedInner = new ScheduledThreadPoolExecutor(1);
        var nested = new dev.latent.guest.runtime.concurrent.FutureTask<>(() -> 42);
        Activation.denyNext = "Result"; Activation.denyMatchesAfter = 1;
        try { deniedInner.schedule(nested, 1, TimeUnit.DAYS); throw new AssertionError(); }
        catch (IllegalStateException expected) { require(expected.getMessage().equals("source-owner-admission-denied")); }
        held(0, 0); require(!nested.isDone());
        nested.run(); require(nested.get() == 42); held(0, 0);
        deniedInner.shutdownNow(); terminated(deniedInner);

        var subclass = new RetainingPool();
        subclass.shutdown(); terminated(subclass);
        try { CompletableFuture.supplyAsync(() -> { calls.incrementAndGet(); return 42; }, subclass); throw new AssertionError(); }
        catch (RejectedExecutionException expected) { }
        held(1, 1); require(calls.get() == 0 && subclass.saved != null);
        subclass.saved.run(); held(0, 0); require(calls.get() == 1);
        Activation.idle();
    }
    private static void directWithdrawal() throws Exception {
        var pool = new ScheduledThreadPoolExecutor(1);
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        pool.execute(() -> waitForRelease(entered, release)); await(entered);
        AtomicInteger calls = new AtomicInteger();
        var result = CompletableFuture.supplyAsync(() -> { calls.incrementAndGet(); return 42; }, pool);
        held(3, 3);
        List<Runnable> returned = pool.shutdownNow();
        require(returned.size() == 1 && !result.isDone() && calls.get() == 0);
        release.countDown(); terminated(pool); held(0, 0);
        returned.get(0).run();
        require(((java.util.concurrent.Future<?>)returned.get(0)).isCancelled() && !result.isDone() && calls.get() == 0);
        held(0, 0); clearedCallback(returned.get(0));
        Activation.idle();
    }
    private static void opaqueWithdrawal() throws Exception {
        var pool = new ScheduledThreadPoolExecutor(1);
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        pool.execute(() -> waitForRelease(entered, release)); await(entered);
        AtomicReference<Runnable> saved = new AtomicReference<>();
        AtomicInteger calls = new AtomicInteger();
        var result = CompletableFuture.supplyAsync(() -> { calls.incrementAndGet(); return 42; }, command -> {
            saved.set(command); pool.execute(command);
        });
        List<Runnable> returned = pool.shutdownNow();
        require(returned.size() == 1 && !result.isDone());
        release.countDown(); terminated(pool); held(1, 1);
        returned.get(0).run();
        require(((java.util.concurrent.Future<?>)returned.get(0)).isCancelled() && !result.isDone()); held(1, 1);
        saved.get().run();
        require(result.join() == 42 && calls.get() == 1); held(0, 0);
        Activation.idle();
    }
    private static void subclassWithdrawal() throws Exception {
        var pool = new RetainingPool();
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        pool.execute(() -> waitForRelease(entered, release)); await(entered);
        AtomicInteger calls = new AtomicInteger();
        var result = CompletableFuture.supplyAsync(() -> { calls.incrementAndGet(); return 42; }, pool);
        Runnable retained = pool.saved;
        List<Runnable> returned = pool.shutdownNow();
        require(returned.size() == 1 && !result.isDone());
        release.countDown(); terminated(pool); held(1, 1);
        returned.get(0).run();
        require(((java.util.concurrent.Future<?>)returned.get(0)).isCancelled() && !result.isDone()); held(1, 1);
        retained.run();
        require(result.join() == 42 && calls.get() == 1); held(0, 0);
        Activation.idle();
    }
    private static final class Original {
        final CompletableFuture<Integer> result;
        final Runnable action;
        final AtomicInteger calls = new AtomicInteger();
        Original() throws Exception { this(null); }
        Original(Runnable body) throws Exception {
            var pool = Executors.newSingleThreadExecutor();
            CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
            pool.execute(() -> waitForRelease(entered, release)); await(entered);
            result = CompletableFuture.supplyAsync(() -> {
                calls.incrementAndGet(); if (body != null) body.run(); return 42;
            }, pool);
            var returned = pool.shutdownNow();
            require(returned.size() == 1 && !result.isDone());
            action = returned.get(0);
            release.countDown(); terminated(pool); held(0, 0);
        }
    }
    private static void copies() throws Exception {
        Original original = new Original();
        var first = new ScheduledThreadPoolExecutor(1);
        var second = new ScheduledThreadPoolExecutor(1);
        first.schedule(original.action, 1, TimeUnit.DAYS);
        second.schedule(original.action, 1, TimeUnit.DAYS);
        held(3, 3);
        require(first.shutdownNow().size() == 1); terminated(first); held(2, 2);
        require(second.shutdownNow().size() == 1); terminated(second); held(0, 0);
        require(!original.result.isDone() && original.calls.get() == 0);
        original.action.run(); original.action.run();
        require(original.result.join() == 42 && original.calls.get() == 1); held(0, 0);
        Activation.idle();
    }
    private static void wrapperCopies() throws Exception {
        Original original = new Original();
        var first = new ScheduledThreadPoolExecutor(1);
        var second = new ScheduledThreadPoolExecutor(1);
        var wrapper = first.schedule(original.action, 1, TimeUnit.DAYS);
        second.schedule((Runnable)wrapper, 1, TimeUnit.DAYS);
        held(3, 3);
        require(first.shutdownNow().size() == 1); terminated(first); held(2, 3);
        require(second.shutdownNow().size() == 1); terminated(second); held(0, 0);
        require(!original.result.isDone());

        // Once withdrawn, a new managed queue copy must re-admit the inner
        // action before it can retain the wrapper's callable.
        var managed = Executors.newSingleThreadExecutor();
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        managed.execute(() -> waitForRelease(entered, release)); await(entered);
        managed.execute((Runnable)wrapper); held(2, 2);
        require(managed.shutdownNow().size() == 1);
        release.countDown(); terminated(managed); held(0, 0);
        original.action.run();
        require(original.result.join() == 42 && original.calls.get() == 1); held(0, 0);
        Activation.idle();
    }
    private static void failedReadmission() throws Exception {
        for (String denied : new String[]{"QueuedWork", "Result"}) {
            Original original = new Original();
            var timer = new ScheduledThreadPoolExecutor(1);
            var wrapper = timer.schedule(original.action, 1, TimeUnit.DAYS);
            require(timer.shutdownNow().size() == 1); terminated(timer); held(0, 0);
            var managed = Executors.newSingleThreadExecutor();
            CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
            managed.execute(() -> waitForRelease(entered, release)); await(entered);
            // The first admission of this kind belongs to the outer queue or
            // wrapper. Deny the next, inside the withdrawn action's readmit.
            Activation.denyNext = denied; Activation.denyMatchesAfter = 1;
            try { managed.execute((Runnable)wrapper); throw new AssertionError(); }
            catch (IllegalStateException expected) { require(expected.getMessage().equals("source-owner-admission-denied")); }
            held(0, 0); require(!original.result.isDone() && original.calls.get() == 0);
            original.action.run();
            require(original.result.join() == 42 && original.calls.get() == 1); held(0, 0);
            release.countDown(); managed.shutdownNow(); terminated(managed);
            Activation.idle();
        }
    }
    private static void cancelledWrapper() throws Exception {
        Original original = new Original();
        var timer = new ScheduledThreadPoolExecutor(1);
        var wrapper = timer.schedule(original.action, 1, TimeUnit.DAYS);
        var managed = Executors.newSingleThreadExecutor();
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        managed.execute(() -> waitForRelease(entered, release)); await(entered);
        managed.execute((Runnable)wrapper); held(3, 2);
        require(wrapper.cancel(false)); held(1, 0); clearedCallback(wrapper);
        require(managed.shutdownNow().size() == 1);
        release.countDown(); terminated(managed); timer.shutdownNow(); terminated(timer); held(0, 0);
        original.action.run(); require(original.result.join() == 42 && original.calls.get() == 1); held(0, 0);
        Activation.idle();
    }
    private static final class Deferred extends dev.latent.guest.runtime.concurrent.FutureTask<Integer> {
        Deferred() { super(() -> 42); }
        @Override public void run() { }
        void complete() { set(42); }
    }
    private static void deferredFuture() throws Exception {
        var pool = new ScheduledThreadPoolExecutor(1);
        Deferred deferred = new Deferred();
        pool.schedule(deferred, 0, TimeUnit.NANOSECONDS).get(5, TimeUnit.SECONDS);
        pool.shutdown(); terminated(pool);
        require(!deferred.isDone()); held(0, 1);
        deferred.complete(); require(deferred.get() == 42); held(0, 0);
        Activation.idle();
    }
    private static void inFlightWrapper() throws Exception {
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        Original original = new Original(() -> waitForRelease(entered, release));
        AtomicReference<Thread> worker = new AtomicReference<>();
        var pool = new ScheduledThreadPoolExecutor(1, target -> {
            Thread result = new Thread(target); worker.set(result); return result;
        });
        var future = pool.schedule(original.action, 1, TimeUnit.DAYS);
        timedWait(worker.get());
        Thread caller = new Thread((Runnable)future); caller.start(); await(entered);
        var returned = pool.shutdownNow();
        require(returned.size() == 1 && returned.get(0) == future); terminated(pool); held(1, 2);
        returned.get(0).run(); require(future.isCancelled()); held(1, 2);
        release.countDown(); caller.join(5000); require(!caller.isAlive());
        require(original.result.join() == 42 && original.calls.get() == 1); held(0, 0); clearedCallback(future);
        Activation.idle();
    }
    private static void stoppedWorkerBoundary() throws Exception {
        for (String mode : new String[]{"once", "fixed", "delay"}) {
            var pool = new ScheduledThreadPoolExecutor(1);
            AtomicInteger calls = new AtomicInteger();
            Runnable callback = calls::incrementAndGet;
            var future = mode.equals("once") ? pool.schedule(callback, 1, TimeUnit.DAYS)
                : mode.equals("fixed") ? pool.scheduleAtFixedRate(callback, 1, 1, TimeUnit.DAYS)
                : pool.scheduleWithFixedDelay(callback, 1, 1, TimeUnit.DAYS);
            require(pool.shutdownNow().size() == 1); terminated(pool); held(0, 0);
            var invoke = future.getClass().getDeclaredMethod("invoke"); invoke.setAccessible(true);
            require(Boolean.FALSE.equals(invoke.invoke(future)));
            require(future.isCancelled() && calls.get() == 0); held(0, 0); clearedCallback(future);
            Activation.idle();
        }
    }
    public static void main(String[] arguments) throws Exception {
        rejection(); directWithdrawal(); opaqueWithdrawal(); subclassWithdrawal(); copies(); wrapperCopies();
        failedReadmission(); cancelledWrapper(); deferredFuture();
        inFlightWrapper(); stoppedWorkerBoundary();
        System.out.println("SCHEDULED_COMPLETABLE_OWNER PASS rejection;inner-admission-rollback;withdrawal;action-replay;opaque;subclass;copies;wrapper-copies;failed-readmission;cancelled-capture;deferred-future;in-flight-wrapper;stopped-worker");
    }
}
