import dev.latent.generated.Bindings.LatentRuntimeActivationOwnerKind;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/** One intentionally unresolved settlement per private JVM process. */
public final class ScheduledPeriodicRollbackSettlementControl {
    private static void require(boolean value) { if (!value) throw new AssertionError("periodic-rollback-settlement"); }
    public static void main(String[] args) throws Exception {
        require(args.length == 1 && (args[0].equals("before") || args[0].equals("after")));
        boolean after = args[0].equals("after");
        var failure = new IllegalStateException("original-insertion-failure");
        var pool = new ScheduledThreadPoolExecutor(1);
        AtomicInteger calls = new AtomicInteger();
        var field = pool.getClass().getDeclaredField("queue"); field.setAccessible(true);
        synchronized (pool) {
            field.set(pool, new java.util.ArrayList<Object>() {
                @Override public boolean add(Object value) {
                    if (after) super.add(value);
                    throw failure;
                }
            });
        }
        Activation.denyCloseNext = "QueuedWork";
        try { pool.schedule(calls::incrementAndGet, 1, TimeUnit.DAYS); throw new AssertionError(); }
        catch (IllegalStateException expected) { require(expected == failure); }
        require(calls.get() == 0 && pool.hasPendingWork() && !pool.isTerminated());
        require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == 1);
        require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == 1);
        pool.shutdownNow();
        require(pool.hasPendingWork() && !pool.isTerminated());
        require(Activation.count(LatentRuntimeActivationOwnerKind.QueuedWork) == 1);
        require(Activation.count(LatentRuntimeActivationOwnerKind.Result) == 1);
        // The denied owner intentionally remains charged until this private
        // process exits; no clean retirement is asserted.
        System.out.println("SCHEDULED_PERIODIC_ROLLBACK_SETTLEMENT PASS " + args[0]);
    }
}
