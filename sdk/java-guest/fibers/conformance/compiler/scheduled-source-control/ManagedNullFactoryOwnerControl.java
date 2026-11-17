import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.CompletableFuture;
import dev.latent.guest.runtime.concurrent.Executors;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Future;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Managed source and private ledger; no host or guest qualification. */
public final class ManagedNullFactoryOwnerControl {
    private static void require(boolean value) { if (!value) throw new AssertionError("managed-null-factory-owner"); }
    private static void held(int queue, int result, int executor) {
        require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == queue
            && Activation.count(LatentRuntimeActivationOwnerKind.Result) == result
            && Activation.count(LatentRuntimeActivationOwnerKind.Executor) == executor);
    }
    private static void await(CountDownLatch latch) throws InterruptedException { require(latch.await(5, TimeUnit.SECONDS)); }
    private static Object worker(Runnable target) throws Exception {
        var capture = target.getClass().getDeclaredFields()[0]; capture.setAccessible(true);
        return capture.get(target);
    }
    private static long preference(Object worker) throws Exception {
        var first = worker.getClass().getDeclaredField("first"); first.setAccessible(true);
        require(first.getType() == long.class);
        return first.getLong(worker);
    }
    private static void inert(Runnable target) throws Exception {
        Object worker = worker(target);
        var field = worker.getClass().getDeclaredField("pool"); field.setAccessible(true);
        require(field.get(worker) == null && preference(worker) == 0); target.run();
    }
    private static void unavailable() throws Exception {
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        AtomicReference<Runnable> first = new AtomicReference<>(), second = new AtomicReference<>();
        var pool = Executors.newFixedThreadPool(1, target -> {
            if (attempts.incrementAndGet() == 1) first.set(target); else second.set(target);
            return null;
        });
        var future = pool.submit(calls::incrementAndGet);
        require(attempts.get() == 2 && !future.isDone() && ((Activation.ManagedPool)pool).hasPendingWork());
        held(1, 1, 1); inert(first.get()); inert(second.get()); require(calls.get() == 0);
        List<Runnable> removed = pool.shutdownNow();
        require(removed.size() == 1 && removed.get(0) == future && !future.isDone());
        require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
        require(future.cancel(false)); Activation.idle();
    }
    private static void recovery(boolean later) throws Exception {
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        var pool = Executors.newFixedThreadPool(1, target -> attempts.incrementAndGet() <= (later ? 2 : 1) ? null : new Thread(target));
        try {
            var first = pool.submit(() -> {
                calls.incrementAndGet(); entered.countDown();
                try { release.await(); } catch (InterruptedException error) { Thread.currentThread().interrupt(); }
            });
            Future<?> second = null;
            if (later) {
                require(attempts.get() == 2 && !first.isDone()); held(1, 1, 1);
                second = pool.submit(calls::incrementAndGet);
                second.get(5, TimeUnit.SECONDS);
            }
            await(entered);
            require(attempts.get() == (later ? 3 : 2));
            held(0, 1, 1);
            release.countDown(); first.get(5, TimeUnit.SECONDS);
            if (second != null) second.get(5, TimeUnit.SECONDS);
            require(calls.get() == (later ? 2 : 1));
            pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
        } finally { release.countDown(); pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
        Activation.idle();
    }
    private static void fallbackThrow() throws Exception {
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        CountDownLatch originalRan = new CountDownLatch(1);
        var failure = new IllegalStateException("fallback-factory-failed");
        var pool = Executors.newFixedThreadPool(1, target -> {
            int attempt = attempts.incrementAndGet();
            if (attempt == 1) return null;
            if (attempt == 2) throw failure;
            return new Thread(target);
        });
        try {
            try { pool.submit(() -> { calls.incrementAndGet(); originalRan.countDown(); }); throw new AssertionError("missing-fallback-failure"); }
            catch (IllegalStateException error) { require(error == failure); }
            require(attempts.get() == 2 && calls.get() == 0 && ((Activation.ManagedPool)pool).hasPendingWork());
            held(1, 1, 1);
            pool.submit(() -> {}).get(5, TimeUnit.SECONDS); await(originalRan);
            require(calls.get() == 1 && attempts.get() == 3);
            pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
        } finally { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
        Activation.idle();
    }
    private static void cached() throws Exception {
        AtomicInteger attempts = new AtomicInteger();
        var pool = Executors.newCachedThreadPool(target -> { attempts.incrementAndGet(); return null; });
        try {
            try { pool.submit(() -> {}); throw new AssertionError("cached-accepted-null"); }
            catch (RejectedExecutionException expected) { require(attempts.get() == 1); }
            held(0, 0, 1);
        } finally { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
        held(0, 0, 0); Activation.idle();
    }
    private static void existingWorker() throws Exception {
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        var pool = Executors.newFixedThreadPool(2, target -> attempts.incrementAndGet() == 1 ? new Thread(target) : null);
        try {
            var first = pool.submit(() -> {
                entered.countDown();
                try { release.await(); } catch (InterruptedException error) { Thread.currentThread().interrupt(); }
            });
            await(entered); held(0, 1, 1);
            var second = pool.submit(calls::incrementAndGet);
            require(attempts.get() == 2 && !second.isDone()); held(1, 2, 1);
            release.countDown(); first.get(5, TimeUnit.SECONDS); second.get(5, TimeUnit.SECONDS);
            require(calls.get() == 1 && attempts.get() == 2);
            pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
        } finally { release.countDown(); pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
        Activation.idle();
    }
    private static void preferredRunningShutdown() throws Exception {
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        AtomicReference<Runnable> target = new AtomicReference<>();
        CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
        var pool = Executors.newFixedThreadPool(1, command -> {
            if (attempts.incrementAndGet() <= 2) return null;
            target.set(command); return new Thread(command);
        });
        try {
            var older = pool.submit(() -> { throw new AssertionError("withdrawn-older-ran"); });
            held(1, 1, 1);
            var preferred = pool.submit(() -> {
                calls.incrementAndGet(); entered.countDown();
                while (true) try { release.await(); return; } catch (InterruptedException ignored) { }
            });
            await(entered); held(1, 2, 1);
            require(preference(worker(target.get())) == 0);
            var removed = pool.shutdownNow();
            require(removed.size() == 1 && removed.get(0) == older && !older.isDone());
            held(0, 1, 1);
            release.countDown(); preferred.get(5, TimeUnit.SECONDS);
            require(pool.awaitTermination(5, TimeUnit.SECONDS) && calls.get() == 1); held(0, 0, 0);
            require(older.cancel(false)); inert(target.get());
        } finally { release.countDown(); pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
        Activation.idle();
    }
    private static void preferredWithdrawn() throws Exception {
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        AtomicReference<Runnable> target = new AtomicReference<>();
        CountDownLatch workerEntered = new CountDownLatch(1), release = new CountDownLatch(1);
        var pool = Executors.newFixedThreadPool(1, command -> {
            if (attempts.incrementAndGet() <= 2) return null;
            target.set(command);
            return new Thread(() -> {
                workerEntered.countDown();
                while (true) try { release.await(); break; } catch (InterruptedException ignored) { }
                command.run();
            });
        });
        try {
            var older = pool.submit(calls::incrementAndGet);
            var preferred = pool.submit(calls::incrementAndGet);
            await(workerEntered); held(2, 2, 1);
            var removed = pool.shutdownNow();
            require(removed.size() == 1 && removed.get(0) == older && !preferred.isDone()); held(1, 1, 1);
            Object heldWorker = worker(target.get());
            var firstLease = heldWorker.getClass().getDeclaredField("firstLease"); firstLease.setAccessible(true);
            var reserved = pool.getClass().getDeclaredField("reservedFirsts"); reserved.setAccessible(true);
            Object item = reserved.get(pool); var queued = item.getClass().getDeclaredField("queued"); queued.setAccessible(true);
            require(firstLease.get(heldWorker) == queued.get(item));
            for (var field : heldWorker.getClass().getDeclaredFields()) {
                if (!field.getType().isPrimitive() && !field.getName().equals("pool")
                        && !field.getName().equals("thread") && !field.getName().equals("firstLease")) {
                    field.setAccessible(true); require(field.get(heldWorker) == null);
                }
            }
            release.countDown(); require(preferred.get(5, TimeUnit.SECONDS).equals(1));
            require(pool.awaitTermination(5, TimeUnit.SECONDS) && calls.get() == 1 && !older.isDone()); held(0, 0, 0);
            require(older.cancel(false)); inert(target.get());
        } finally { release.countDown(); pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
        Activation.idle();
    }
    private static void preferenceExhaustion() throws Exception {
        AtomicInteger attempts = new AtomicInteger();
        AtomicReference<Runnable> firstTarget = new AtomicReference<>(), secondTarget = new AtomicReference<>();
        CountDownLatch firstPaused = new CountDownLatch(1), releaseFirst = new CountDownLatch(1);
        CountDownLatch secondPaused = new CountDownLatch(1), releaseSecond = new CountDownLatch(1);
        CountDownLatch secondRunning = new CountDownLatch(1), finishSecond = new CountDownLatch(1);
        StringBuffer calls = new StringBuffer();
        var pool = Executors.newFixedThreadPool(2, target -> {
            boolean first = attempts.incrementAndGet() == 1;
            (first ? firstTarget : secondTarget).set(target);
            return new Thread(() -> {
                (first ? firstPaused : secondPaused).countDown();
                while (true) try { (first ? releaseFirst : releaseSecond).await(); break; }
                catch (InterruptedException ignored) { }
                target.run();
            });
        });
        var counter = pool.getClass().getDeclaredField("nextPreference"); counter.setAccessible(true);
        counter.setLong(pool, Long.MAX_VALUE);
        try {
            var older = pool.submit(() -> calls.append('A')); await(firstPaused);
            var second = pool.submit(() -> {
                calls.append('B'); secondRunning.countDown();
                while (true) try { finishSecond.await(); return; } catch (InterruptedException ignored) { }
            });
            await(secondPaused);
            Object firstWorker = worker(firstTarget.get()), secondWorker = worker(secondTarget.get());
            var lease = firstWorker.getClass().getDeclaredField("firstLease"); lease.setAccessible(true);
            require(lease.get(firstWorker) != null && lease.get(secondWorker) != null
                && lease.get(firstWorker) != lease.get(secondWorker) && counter.getLong(pool) == Long.MAX_VALUE);
            var queueField = pool.getClass().getDeclaredField("queue"); queueField.setAccessible(true);
            synchronized (pool) { require(((java.util.ArrayDeque<?>)queueField.get(pool)).isEmpty()); }
            releaseSecond.countDown(); await(secondRunning); require(!older.isDone());
            var later = pool.submit(() -> calls.append('C'));
            synchronized (pool) { require(((java.util.ArrayDeque<?>)queueField.get(pool)).size() == 1); }
            releaseFirst.countDown(); older.get(5, TimeUnit.SECONDS); later.get(5, TimeUnit.SECONDS);
            require(calls.toString().equals("BAC"));
            finishSecond.countDown(); second.get(5, TimeUnit.SECONDS);
            pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
            inert(firstTarget.get()); inert(secondTarget.get());
        } finally {
            releaseFirst.countDown(); releaseSecond.countDown(); finishSecond.countDown();
            pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS));
        }
        Activation.idle();
    }
    private static void nestedInitialWithdrawal() throws Exception {
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        AtomicReference<Future<?>> first = new AtomicReference<>(), second = new AtomicReference<>();
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        var pool = Executors.newFixedThreadPool(1, target -> {
            if (attempts.incrementAndGet() == 1) {
                first.set(selected.get().submit(calls::incrementAndGet));
                second.set(selected.get().submit(calls::incrementAndGet));
            }
            return null;
        });
        selected.set(pool);
        var outer = pool.submit(calls::incrementAndGet);
        require(attempts.get() == 2 && ((Activation.ManagedPool)pool).hasPendingWork()); held(3, 3, 1);
        List<Runnable> removed = pool.shutdownNow();
        require(removed.size() == 3 && removed.get(0) == first.get() && removed.get(1) == second.get()
            && removed.get(2) == outer && calls.get() == 0);
        require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
        require(first.get().cancel(false) && second.get().cancel(false) && outer.cancel(false)); Activation.idle();
    }
    private static void nestedInitialFallbackThrow() throws Exception {
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        AtomicReference<Future<?>> nested = new AtomicReference<>();
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        var failure = new IllegalStateException("nested-initial-fallback-failed");
        var pool = Executors.newFixedThreadPool(1, target -> {
            if (attempts.incrementAndGet() == 1) {
                nested.set(selected.get().submit(calls::incrementAndGet));
                return null;
            }
            throw failure;
        });
        selected.set(pool);
        Runnable outer = calls::incrementAndGet;
        try { pool.execute(outer); throw new AssertionError("missing-fallback-failure"); }
        catch (IllegalStateException actual) { require(actual == failure); }
        require(attempts.get() == 2 && ((Activation.ManagedPool)pool).hasPendingWork()); held(2, 1, 1);
        List<Runnable> removed = pool.shutdownNow();
        require(removed.size() == 2 && removed.get(0) == nested.get() && removed.get(1) == outer && calls.get() == 0);
        require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
        require(nested.get().cancel(false)); Activation.idle();
    }
    private static void nestedInitialShutdown() throws Exception {
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        AtomicReference<Future<?>> nested = new AtomicReference<>();
        AtomicReference<List<Runnable>> removed = new AtomicReference<>();
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        var pool = Executors.newFixedThreadPool(1, target -> {
            attempts.incrementAndGet(); nested.set(selected.get().submit(calls::incrementAndGet));
            removed.set(selected.get().shutdownNow());
            require(removed.get().size() == 1 && removed.get().get(0) == nested.get()); held(1, 1, 1);
            return null;
        });
        selected.set(pool);
        try { pool.submit(calls::incrementAndGet); throw new AssertionError("accepted-after-shutdown"); }
        catch (RejectedExecutionException expected) { }
        require(attempts.get() == 1 && calls.get() == 0 && pool.awaitTermination(5, TimeUnit.SECONDS));
        held(0, 0, 0); require(nested.get().cancel(false)); Activation.idle();
    }
    private static void nestedInitialRotationFailure() throws Exception {
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        AtomicReference<Future<?>> nested = new AtomicReference<>();
        AtomicInteger calls = new AtomicInteger();
        var failure = new IllegalStateException("synthetic-queue-append-failure");
        class FaultDeque<E> extends java.util.ArrayDeque<E> {
            boolean armed;
            @Override public void addLast(E item) {
                if (armed) { armed = false; throw failure; }
                super.addLast(item);
            }
        }
        var queue = new FaultDeque<>();
        var pool = Executors.newFixedThreadPool(1, target -> {
            nested.set(selected.get().submit(calls::incrementAndGet)); queue.armed = true; return null;
        });
        selected.set(pool);
        var field = pool.getClass().getDeclaredField("queue"); field.setAccessible(true); field.set(pool, queue);
        try { pool.submit(calls::incrementAndGet); throw new AssertionError("missing-queue-failure"); }
        catch (IllegalStateException actual) { require(actual == failure); }
        require(((Activation.ManagedPool)pool).hasPendingWork() && Activation.poisoned && calls.get() == 0); held(2, 2, 1);
        List<Runnable> removed = pool.shutdownNow();
        require(removed.size() == 1 && removed.get(0) == nested.get() && calls.get() == 0 && !pool.isTerminated());
        held(1, 1, 1); require(nested.get().cancel(false));
        // The unclassifiable original insertion stays rooted until Store teardown.
    }
    private static void nestedOuterAlreadyRunning() throws Exception {
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        AtomicReference<Future<?>> nested = new AtomicReference<>();
        AtomicInteger attempts = new AtomicInteger(); StringBuffer calls = new StringBuffer();
        CountDownLatch firstEntered = new CountDownLatch(1), releaseFirst = new CountDownLatch(1), nestedRan = new CountDownLatch(1);
        var pool = Executors.newFixedThreadPool(2, target -> {
            if (attempts.incrementAndGet() == 1) return new Thread(target);
            nested.set(selected.get().submit(() -> { calls.append('B'); nestedRan.countDown(); }));
            releaseFirst.countDown();
            try { await(nestedRan); } catch (InterruptedException error) { throw new AssertionError(error); }
            require(calls.toString().equals("B")); return null;
        });
        selected.set(pool);
        try {
            var first = pool.submit(() -> {
                firstEntered.countDown();
                try { releaseFirst.await(); } catch (InterruptedException error) { Thread.currentThread().interrupt(); }
            });
            await(firstEntered);
            var outer = pool.submit(() -> calls.append('A'));
            first.get(5, TimeUnit.SECONDS); nested.get().get(5, TimeUnit.SECONDS); outer.get(5, TimeUnit.SECONDS);
            require(attempts.get() == 2 && calls.toString().equals("BA"));
            pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
        } finally { releaseFirst.countDown(); pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
        Activation.idle();
    }
    private static void nestedFallbackThrow() throws Exception {
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        AtomicReference<Future<?>> nested = new AtomicReference<>();
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        CountDownLatch originalRan = new CountDownLatch(1);
        var failure = new IllegalStateException("nested-fallback-failed");
        var pool = Executors.newFixedThreadPool(1, target -> {
            int attempt = attempts.incrementAndGet();
            if (attempt == 1) return null;
            if (attempt == 2) {
                nested.set(selected.get().submit(calls::incrementAndGet));
                held(2, 2, 1);
                throw failure;
            }
            return new Thread(target);
        });
        selected.set(pool);
        try {
            try { pool.submit(() -> { calls.incrementAndGet(); originalRan.countDown(); });
                throw new AssertionError("missing-factory-failure"); }
            catch (IllegalStateException error) { require(error == failure); }
            require(attempts.get() == 2 && nested.get() != null && !nested.get().isDone());
            held(2, 2, 1);
            pool.submit(() -> {}).get(5, TimeUnit.SECONDS);
            nested.get().get(5, TimeUnit.SECONDS); await(originalRan);
            require(calls.get() == 2 && attempts.get() == 3);
            pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
        } finally { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
        Activation.idle();
    }
    private static void fallbackCompletable() throws Exception {
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        var failure = new IllegalStateException("fallback-factory-failed");
        var pool = Executors.newFixedThreadPool(1, target -> {
            int attempt = attempts.incrementAndGet();
            if (attempt == 1) return null;
            if (attempt == 2) throw failure;
            return new Thread(target);
        });
        var result = new CompletableFuture<Integer>();
        try {
            try { result.completeAsync(() -> { calls.incrementAndGet(); return 42; }, pool);
                throw new AssertionError("missing-factory-failure"); }
            catch (IllegalStateException error) { require(error == failure); }
            require(!result.isDone() && calls.get() == 0 && attempts.get() == 2); held(2, 1, 1);
            pool.submit(() -> {}).get(5, TimeUnit.SECONDS);
            require(result.get(5, TimeUnit.SECONDS) == 42 && calls.get() == 1 && attempts.get() == 3);
            pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
        } finally { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
        Activation.idle();
    }
    private static void fallbackStartFailure(boolean uncertain) throws Exception {
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        CountDownLatch originalRan = new CountDownLatch(1);
        AtomicReference<Thread> worker = new AtomicReference<>();
        AtomicReference<Runnable> target = new AtomicReference<>();
        var failure = new IllegalStateException("fallback-worker-start-failed");
        var pool = Executors.newFixedThreadPool(1, command -> {
            int attempt = attempts.incrementAndGet();
            if (attempt == 1) return null;
            if (attempt == 2) {
                target.set(command);
                Thread thread = new Thread(command) { @Override public void start() { throw failure; } };
                worker.set(thread); return thread;
            }
            return new Thread(command);
        });
        Activation.retainFailedStart = uncertain;
        try {
            try { pool.submit(() -> { calls.incrementAndGet(); originalRan.countDown(); }); throw new AssertionError("missing-start-failure"); }
            catch (IllegalStateException error) { require(error == failure); }
            require(attempts.get() == 2 && calls.get() == 0 && ((Activation.ManagedPool)pool).hasPendingWork());
            held(1, 1, 1);
            if (uncertain) {
                require(Activation.recorded(worker.get(), (Activation.ManagedPool)pool));
                var capture = target.get().getClass().getDeclaredFields()[0]; capture.setAccessible(true);
                Object heldWorker = capture.get(target.get());
                var owner = heldWorker.getClass().getDeclaredField("pool"); owner.setAccessible(true);
                require(owner.get(heldWorker) == pool);
                List<Runnable> removed = pool.shutdownNow();
                require(removed.size() == 1 && !((Future<?>)removed.get(0)).isDone());
                held(0, 0, 1); require(!pool.isTerminated() && ((Future<?>)removed.get(0)).cancel(false));
                // The uncertain worker and executor remain owned until teardown.
                return;
            }
            inert(target.get());
            pool.submit(() -> {}).get(5, TimeUnit.SECONDS);
            await(originalRan);
            require(attempts.get() == 3 && calls.get() == 1);
            pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
        } finally {
            Activation.retainFailedStart = false;
            if (!uncertain) { pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
        }
        Activation.idle();
    }
    private static void fallbackLiveThread() throws Exception {
        CountDownLatch liveEntered = new CountDownLatch(1), liveRelease = new CountDownLatch(1), originalRan = new CountDownLatch(1);
        Thread live = new Thread(() -> {
            liveEntered.countDown();
            try { liveRelease.await(); } catch (InterruptedException error) { Thread.currentThread().interrupt(); }
        });
        live.start(); await(liveEntered);
        AtomicInteger attempts = new AtomicInteger();
        var pool = Executors.newFixedThreadPool(1, target -> {
            int attempt = attempts.incrementAndGet();
            if (attempt == 1) return null;
            return attempt == 2 ? live : new Thread(target);
        });
        try {
            try { pool.submit(originalRan::countDown); throw new AssertionError("accepted-live-thread"); }
            catch (IllegalThreadStateException expected) { require(attempts.get() == 2 && live.isAlive()); }
            held(1, 1, 1);
            pool.submit(() -> {}).get(5, TimeUnit.SECONDS); await(originalRan);
            require(attempts.get() == 3 && live.isAlive() && !live.isInterrupted());
            pool.shutdown(); require(pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
        } finally {
            liveRelease.countDown(); live.join(5000); require(!live.isAlive());
            pool.shutdownNow(); require(pool.awaitTermination(5, TimeUnit.SECONDS));
        }
        Activation.idle();
    }
    private static void fallbackShutdown(String fault) throws Exception {
        AtomicReference<ExecutorService> selected = new AtomicReference<>();
        AtomicReference<List<Runnable>> removed = new AtomicReference<>();
        AtomicInteger attempts = new AtomicInteger(), calls = new AtomicInteger();
        var failure = new IllegalStateException("factory-after-shutdown");
        var pool = Executors.newFixedThreadPool(1, target -> {
            if (attempts.incrementAndGet() == 1) return null;
            if (fault.equals("denied")) Activation.denyCloseNext = "QueuedWork";
            if (fault.equals("lost")) Activation.loseCloseAckNext = "QueuedWork";
            removed.set(selected.get().shutdownNow());
            held(0, 0, 1);
            require(((Activation.ManagedPool)selected.get()).hasPendingWork());
            throw failure;
        });
        selected.set(pool);
        try {
            try { pool.submit(calls::incrementAndGet); throw new AssertionError("missing-shutdown-failure"); }
            catch (IllegalStateException error) {
                require(fault.equals("none") ? error == failure : error.getMessage().startsWith("source-owner-settlement-"));
            }
            require(attempts.get() == 2 && calls.get() == 0);
            if (fault.equals("none")) {
                require(removed.get().size() == 1 && pool.awaitTermination(5, TimeUnit.SECONDS)); held(0, 0, 0);
                var future = (Future<?>)removed.get().get(0);
                require(!future.isDone() && future.cancel(false)); Activation.idle();
            } else {
                require(Activation.poisoned && Activation.retainsFailedQueued() && Activation.failedLeaseAttempts() == 1);
                held(fault.equals("denied") ? 1 : 0, 1, 0);
                pool.shutdownNow();
                require(Activation.failedLeaseAttempts() == 1);
                // The original uncertain queued and result owners remain charged until Store teardown.
            }
        } finally { pool.shutdownNow(); }
    }
    public static void main(String[] args) throws Exception {
        String mode = args[0];
        switch (mode) {
            case "unavailable" -> unavailable();
            case "immediate-recovery" -> recovery(false);
            case "later-recovery" -> recovery(true);
            case "fallback-throw" -> fallbackThrow();
            case "nested-fallback-throw" -> nestedFallbackThrow();
            case "fallback-completable" -> fallbackCompletable();
            case "fallback-start-failure" -> fallbackStartFailure(false);
            case "fallback-start-uncertain" -> fallbackStartFailure(true);
            case "fallback-live-thread" -> fallbackLiveThread();
            case "cached-null" -> cached();
            case "existing-worker" -> existingWorker();
            case "preferred-running-shutdown" -> preferredRunningShutdown();
            case "preferred-withdrawn" -> preferredWithdrawn();
            case "preference-exhaustion" -> preferenceExhaustion();
            case "nested-initial-withdrawal" -> nestedInitialWithdrawal();
            case "nested-initial-fallback-throw" -> nestedInitialFallbackThrow();
            case "nested-initial-shutdown" -> nestedInitialShutdown();
            case "nested-initial-rotation-failure" -> nestedInitialRotationFailure();
            case "nested-outer-already-running" -> nestedOuterAlreadyRunning();
            case "fallback-shutdown" -> fallbackShutdown("none");
            case "fallback-denied" -> fallbackShutdown("denied");
            case "fallback-lost" -> fallbackShutdown("lost");
            default -> throw new IllegalArgumentException(mode);
        }
        System.out.println("MANAGED_NULL_FACTORY_OWNER PASS " + mode);
    }
}
