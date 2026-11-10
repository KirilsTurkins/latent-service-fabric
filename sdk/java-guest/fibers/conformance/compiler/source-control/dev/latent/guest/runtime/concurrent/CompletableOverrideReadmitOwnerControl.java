package dev.latent.guest.runtime.concurrent;

import dev.latent.guest.runtime.Activation;
import java.lang.reflect.Field;
import java.util.concurrent.Executor;

/** Source-only simulation of the existing managed queue-copy protocol. */
public final class CompletableOverrideReadmitOwnerControl {
    private static final class Misleading<T> extends CompletableFuture<T> {
        final boolean reported;
        Misleading(boolean reported) { this.reported = reported; }
        @Override public boolean isDone() { return reported; }
    }
    private static final class Maker<T> extends CompletableFuture<T> {
        final boolean reported;
        Maker(boolean reported) { this.reported = reported; }
        @Override public <U> CompletableFuture<U> newIncompleteFuture() { return new Misleading<U>(reported); }
    }
    private static final class Held implements Executor {
        Runnable action;
        @Override public void execute(Runnable next) {
            if (action != null || !CompletableFuture.acceptedByQueue(next)) throw new AssertionError("first-acceptance");
            action = next;
        }
    }
    private static void require(boolean value, String message) { if (!value) throw new AssertionError(message); }
    private static void counts(int queued, int results) {
        require(Activation.queuedOwners() == queued && Activation.resultOwners() == results, "original-ledger");
    }
    private static void run(boolean reported, boolean completeBeforeReadmit) throws Exception {
        Maker<Integer> source = new Maker<>(reported);
        Executor facade = source.defaultExecutor();
        Field pool = facade.getClass().getDeclaredField("pool");
        pool.setAccessible(true);
        Held held = new Held(); pool.set(facade, held);
        int[] calls = {0};
        CompletableFuture<Integer> child = source.thenApplyAsync(v -> { calls[0]++; return v + 1; }, facade);
        source.complete(41);
        Runnable command = held.action;
        require(command != null, "not-enqueued");
        counts(1, 1);
        CompletableFuture.removedFromQueue(command, true, true);
        counts(0, 0);
        if (completeBeforeReadmit) {
            child.complete(99);
            Activation.denyNext = "QueuedWork";
        }
        boolean accepted;
        try { accepted = CompletableFuture.acceptedByQueue(command); }
        finally { Activation.denyNext = null; }
        require(accepted == !completeBeforeReadmit, "readmission-decision");
        if (accepted) {
            counts(1, 1);
            command.run();
            CompletableFuture.removedFromQueue(command, true, false);
        }
        counts(0, 0);
        require(child.getNow(null) == (completeBeforeReadmit ? 99 : 42)
            && calls[0] == (completeBeforeReadmit ? 0 : 1), "readmission-result");
        Activation.cleanup();
    }
    public static void main(String[] args) throws Exception {
        run(true, false); run(false, true);
        System.out.println("COMPLETABLE_OVERRIDE_READMIT_OWNER PASS simulated-queue-copies=2;original-ledger");
    }
}
