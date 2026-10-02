package dev.latent.guest.runtime.concurrent;

import dev.latent.guest.runtime.Activation;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/** Executes the actual SDK queue's absence/removal witness with private host bindings. */
public final class CompletableFutureDelayedManagedControl {
    private static int checks;
    private static void require(boolean condition) {
        if (!condition) throw new AssertionError("managed-delayed-witness-" + checks);
        checks++;
    }
    public static void main(String[] args) throws Exception {
        AtomicInteger calls = new AtomicInteger();
        for (String mode : new String[]{"closed", "queued-owner-denied", "null-factory", "throwing-factory"}) {
            ThreadFactory factory = command -> new Thread(command);
            if (mode.equals("null-factory")) factory = command -> null;
            else if (mode.equals("throwing-factory")) factory = command -> {
                throw new IllegalStateException("actual-sdk-worker-factory-failure");
            };
            ManagedExecutor pool = new ManagedExecutor(1, factory, false);
            if (mode.equals("closed")) pool.shutdown();
            CompletableFuture<Integer> future = CompletableFuture.supplyAsync(() -> {
                calls.incrementAndGet(); return 99;
            }, CompletableFuture.delayedExecutor(60, TimeUnit.MILLISECONDS, pool));
            require(Activation.queuedOwners() == 2 && Activation.resultOwners() == 1 && Activation.deferredOwners() == 1);
            if (mode.equals("queued-owner-denied")) Activation.denyNext = "QueuedWork";
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(3);
            while ((Activation.queuedOwners() != 0 || Activation.resultOwners() != 0 || Activation.deferredOwners() != 0)
                    && System.nanoTime() < deadline) Thread.sleep(1);
            require(Activation.queuedOwners() == 0 && Activation.resultOwners() == 0 && Activation.deferredOwners() == 0);
            require(!pool.hasPendingWork() && calls.get() == 0 && !future.isDone());
            require(Activation.denyNext == null);
            require(future.cancel(false) && future.isCancelled());
            pool.shutdown();
            require(pool.awaitTermination(3, TimeUnit.SECONDS));
            Activation.cleanup();
            require(Activation.owners() == 0 && Activation.executorOwners() == 0);
        }
        System.out.println("COMPLETABLE_DELAYED_MANAGED PASS observables=" + checks + ";witness=actual-owned-queue");
    }
}
