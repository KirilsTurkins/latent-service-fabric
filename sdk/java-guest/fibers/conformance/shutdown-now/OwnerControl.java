package dev.latent.app;

import dev.latent.generated.Bindings;
import dev.latent.guest.runtime.Activation;

/** Actual SDK pool/future bodies with the existing private source ledger only. */
public final class OwnerControl {
    private static int checks;
    private static void require(boolean condition) {
        if (!condition) throw new AssertionError("shutdown-now-source-ownership");
        checks++;
    }
    private static void owners(int queued, int results) {
        require(Activation.count(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork) == queued);
        require(Activation.count(Bindings.LatentRuntimeActivationOwnerKind.Result) == results);
    }
    public static void main(String[] arguments) throws Exception {
        for (long mode = 0; mode < 4; mode++) {
            require(new Capsule().run(mode) == 42);
            Activation.idle();
            owners(0, 0);
        }
        try (Capsule.Scenario selected = new Capsule.Scenario()) {
            owners(0, 0);
            for (String kind : new String[]{"QueuedWork", "Result"}) {
                Activation.denyNext = kind;
                try { selected.returned.get(0).run(); throw new AssertionError("readmission-was-not-denied"); }
                catch (IllegalStateException denied) {
                    require(denied.getMessage().equals("source-owner-admission-denied"));
                }
                require(!selected.supplied.isDone() && selected.callbacks == 0);
                owners(0, 0);
            }
            selected.returned.get(0).run();
            selected.returned.get(0).run();
            require(selected.supplied.join() == 42 && selected.callbacks == 1);
            owners(0, 0);
            selected.returned.get(1).run();
            require(selected.dependent.join() == 42 && selected.callbacks == 2);
            owners(0, 0);
        }
        Activation.idle();
        try (Capsule.RunningScenario selected = new Capsule.RunningScenario()) {
            // Logical cancellation and queue removal do not refund a supplier
            // which already entered and still holds its real running frame.
            owners(1, 1);
            selected.retireRunning();
            owners(0, 0);
            selected.replayPending();
            owners(1, 1);
            selected.retireReplay();
            require(selected.queued.join() == 42 && selected.callbacks == 1);
            owners(0, 0);
        }
        Activation.idle();
        try (Capsule.Scenario selected = new Capsule.Scenario()) {
            try (Capsule.CopiesScenario copies = new Capsule.CopiesScenario(selected)) {
                owners(3, 3);
                copies.withdrawOne(); owners(2, 2);
                copies.withdrawLast(); owners(0, 0);
            }
            for (Runnable task : selected.returned) { task.run(); task.run(); }
            require(selected.supplied.join() == 42 && selected.dependent.join() == 42 && selected.callbacks == 2);
            owners(0, 0);
        }
        Activation.idle();
        try (Capsule.OpaqueScenario opaque = new Capsule.OpaqueScenario()) {
            owners(2, 2);
            opaque.withdraw(); owners(1, 1);
            opaque.replay(); owners(0, 0);
            require(opaque.result.join() == 42 && opaque.callbacks == 1);
        }
        Activation.idle();
        System.out.println("SHUTDOWN_NOW_SOURCE_OWNER PASS observables=" + checks);
    }
}
