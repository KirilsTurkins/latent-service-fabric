import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.util.Timer;
import dev.latent.guest.runtime.util.TimerTask;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Failure/retirement observations supplement the unchanged JDK reference. */
public final class TimerModelMain {
    public static void main(String[] args) throws Exception {
        Main.main(args);
        Activation.denyNext = "Executor";
        try { new Timer("denied", true); throw new AssertionError("missing-executor-admission"); }
        catch (IllegalStateException expected) { }
        Timer timer = new Timer("source-owned", true);
        CountDownLatch completed = new CountDownLatch(1);
        TimerTask task = new TimerTask() { public void run() { completed.countDown(); } };
        Activation.denyNext = "QueuedWork";
        try { timer.schedule(task, 0); throw new AssertionError("missing-queue-admission"); }
        catch (IllegalStateException expected) { }
        timer.schedule(task, 0);
        if (!completed.await(5, TimeUnit.SECONDS)) throw new AssertionError("admission-failure-corrupted-task");
        timer.cancel();
        Timer cancelled = new Timer("cancelled-far-future", true);
        TimerTask future = new TimerTask() { public void run() { throw new AssertionError("cancelled-task-ran"); } };
        cancelled.schedule(future, 60_000);
        if (!future.cancel()) throw new AssertionError("cancel-result");
        // Cancellation is logical first. The real source worker must remove its
        // queued owner before the coordinator is allowed to retire idle pools.
        new Timer("idle-root-retirement", true);
        Activation.cleanup();
        if (Activation.owners() != 0) throw new AssertionError("unretired-source-owners");
        try { cancelled.schedule(new TimerTask() { public void run() { } }, 0); throw new AssertionError("root-closed-admission"); }
        catch (IllegalStateException expected) { }
        System.out.println("TIMER_SOURCE_CONTROL PASS reference-observables;queue-rollback;cancel-drain;idle-finally;no-live-owners");
    }
}
