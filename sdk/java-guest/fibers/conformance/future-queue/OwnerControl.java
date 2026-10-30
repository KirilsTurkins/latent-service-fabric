package dev.latent.app;

import dev.latent.generated.Bindings;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.Executors;
import dev.latent.guest.runtime.concurrent.FutureTask;
import dev.latent.guest.runtime.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

/** Execute actual SDK bodies with the existing private host ledger only. */
public final class OwnerControl {
    private static int checks;
    private static void require(boolean value) { if (!value) throw new AssertionError("future-queue-ownership"); checks++; }
    private static void owners(int queued, int results) {
        require(Activation.count(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork) == queued);
        require(Activation.count(Bindings.LatentRuntimeActivationOwnerKind.Result) == results);
    }
    static final class Deferred extends FutureTask<Integer> {
        Deferred() { super(() -> 42); }
        @Override public void run() { }
        void complete() { set(42); }
    }
    public static void main(String[] args) throws Exception {
        try (Capsule.Pair selected = new Capsule.Pair()) {
            owners(2, 1);
            selected.withdrawFirst(); owners(1, 1);
            FutureTask<Integer> denied = new FutureTask<>(() -> 41);
            Activation.denyNext = "Result";
            try { selected.second.execute(denied); throw new AssertionError("missing-result-denial"); }
            catch (IllegalStateException expected) { require(expected.getMessage().equals("source-owner-admission-denied")); }
            require(!denied.isDone() && selected.calls == 0); owners(1, 1);
            selected.secondGate.release(); selected.second.shutdown();
            Capsule.require(selected.second.awaitTermination(5, TimeUnit.SECONDS));
            require(selected.target.get() == 42 && selected.calls == 1); owners(0, 0);
        }
        Activation.idle();
        try (Capsule.Pair selected = new Capsule.Pair()) {
            selected.withdrawFirst(); selected.withdrawLast(); owners(0, 0);
            Activation.denyNext = "Result";
            try { selected.target.run(); throw new AssertionError("missing-readmission-denial"); }
            catch (IllegalStateException expected) { require(expected.getMessage().equals("source-owner-admission-denied")); }
            require(!selected.target.isDone() && selected.calls == 0); owners(0, 0);
            selected.target.run(); selected.target.run();
            require(selected.target.get() == 42 && selected.calls == 1); owners(0, 0);
        }
        Activation.idle();
        try (Capsule.Running selected = new Capsule.Running()) {
            owners(0, 1); selected.finish(); owners(0, 0);
        }
        Activation.idle();
        try (Capsule.ScheduledCopy selected = new Capsule.ScheduledCopy()) {
            owners(1, 1); selected.withdrawLast(); owners(0, 0);
        }
        Activation.idle();
        Capsule.Gate gate = new Capsule.Gate();
        ScheduledThreadPoolExecutor timer = new ScheduledThreadPoolExecutor(1);
        int[] runs = {0};
        try {
            var periodic = timer.scheduleAtFixedRate(() -> { if (++runs[0] == 2) gate.work(); }, 0, 1, TimeUnit.MILLISECONDS);
            gate.entered(); owners(1, 1);
            require(periodic.cancel(false)); owners(1, 1);
            gate.release(); timer.shutdown(); require(timer.awaitTermination(5, TimeUnit.SECONDS)); owners(0, 0);
        } finally { gate.release(); timer.shutdownNow(); Capsule.require(timer.awaitTermination(5, TimeUnit.SECONDS)); }
        Activation.idle();
        var pool = Executors.newSingleThreadExecutor();
        Deferred deferred = new Deferred();
        try {
            pool.execute(deferred); pool.shutdown();
            require(pool.awaitTermination(5, TimeUnit.SECONDS) && !deferred.isDone()); owners(0, 1);
            var held = Executors.newSingleThreadExecutor();
            Capsule.Gate heldGate = new Capsule.Gate();
            try {
                held.execute(heldGate::work); heldGate.entered(); held.execute(deferred);
                var returned = held.shutdownNow();
                require(returned.size() == 1 && returned.get(0) == deferred); owners(0, 1);
                heldGate.release(); require(held.awaitTermination(5, TimeUnit.SECONDS)); owners(0, 1);
            } finally { heldGate.release(); held.shutdownNow(); Capsule.require(held.awaitTermination(5, TimeUnit.SECONDS)); }
            deferred.complete(); require(deferred.get() == 42); owners(0, 0);
        } finally { deferred.complete(); pool.shutdownNow(); Capsule.require(pool.awaitTermination(5, TimeUnit.SECONDS)); }
        Activation.idle();
        System.out.println("FUTURE_QUEUE_OWNER PASS checks=" + checks);
    }
}
