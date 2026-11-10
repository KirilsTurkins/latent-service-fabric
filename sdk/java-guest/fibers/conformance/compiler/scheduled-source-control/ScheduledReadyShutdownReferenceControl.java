import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

public final class ScheduledReadyShutdownReferenceControl {
    private static boolean sourcePort;
    private static Class<?> ledger() throws ClassNotFoundException { return Class.forName("dev.latent.guest.runtime.Activation"); }
    private static int owner(String name) {
        if (!sourcePort) return -1;
        try {
            Class<?> kind=Class.forName("dev.latent.generated.Bindings$LatentRuntimeActivationOwnerKind");
            Object selected=null;
            for (Object value:kind.getEnumConstants()) if (((Enum<?>)value).name().equals(name)) selected=value;
            if (selected==null) throw new AssertionError("missing-owner-kind");
            return (Integer)ledger().getMethod("count",kind).invoke(null,selected);
        } catch (ReflectiveOperationException error) { throw new AssertionError(error); }
    }
    private static void idle() throws Exception { if (sourcePort) ledger().getMethod("idle").invoke(null); }
    private static void await(CountDownLatch latch,String label) {
        try { if (!latch.await(5,TimeUnit.SECONDS)) throw new AssertionError(label); }
        catch (InterruptedException error) { throw new AssertionError(error); }
    }
    private static String counts() { return sourcePort ? owner("Executor")+":"+owner("QueuedWork")+":"+owner("Result") : "-1"; }
    private static void test(String mode) throws Exception {
        ScheduledThreadPoolExecutor executor=new ScheduledThreadPoolExecutor(1);
        CountDownLatch running=new CountDownLatch(1), release=new CountDownLatch(1);
        CountDownLatch ready=new CountDownLatch(1), readyRelease=new CountDownLatch(1);
        AtomicInteger calls=new AtomicInteger();
        try {
            Future<?> first=executor.submit(()->{running.countDown();await(release,"running-release");}); await(running,"running");
            Runnable action=()->{calls.incrementAndGet();ready.countDown();await(readyRelease,"ready-release");};
            ScheduledFuture<?> immediate=mode.equals("periodic")
                ? executor.scheduleAtFixedRate(action,0,60,TimeUnit.SECONDS)
                : executor.schedule(action,mode.equals("elapsed")?20:0,TimeUnit.MILLISECONDS);
            ScheduledFuture<?> future=executor.schedule(()->{throw new AssertionError("future-ran");},60,TimeUnit.SECONDS);
            long deadline=System.nanoTime()+5_000_000_000L;
            while (immediate.getDelay(TimeUnit.NANOSECONDS)>0) {
                if (System.nanoTime()-deadline>=0) throw new AssertionError("delay-not-elapsed");
                Thread.sleep(1);
            }
            if (mode.equals("disabled") || mode.equals("elapsed") || mode.equals("periodic")) executor.setExecuteExistingDelayedTasksAfterShutdownPolicy(false);
            executor.shutdown();
            if (mode.equals("changed")) executor.setExecuteExistingDelayedTasksAfterShutdownPolicy(false);
            boolean immediateCancelled=immediate.isCancelled(), futureCancelled=future.isCancelled();
            String held=counts(); release.countDown();
            String runningCounts="none";
            if (!immediateCancelled) { await(ready,"eligible-not-run"); runningCounts=counts(); }
            future.cancel(false); readyRelease.countDown();
            first.get(5,TimeUnit.SECONDS);
            if (!immediateCancelled) immediate.get(5,TimeUnit.SECONDS);
            if (mode.equals("default")) executor.shutdownNow();
            if (!executor.awaitTermination(5,TimeUnit.SECONDS)) throw new AssertionError("not-terminated");
            idle();
            boolean periodic=mode.equals("periodic"), defaults=mode.equals("default");
            if (immediateCancelled!=periodic || futureCancelled==defaults || calls.get()!=(periodic?0:1))
                throw new AssertionError("shutdown-observable-"+mode);
            String expectedHeld=periodic?"1:1:1":defaults?"1:3:3":"1:2:2";
            String expectedRunning=periodic?"none":defaults?"1:2:2":"1:1:1";
            if (sourcePort && (!held.equals(expectedHeld) || !runningCounts.equals(expectedRunning) || !counts().equals("0:0:0")))
                throw new AssertionError("shutdown-owner-"+mode+":"+held+":"+runningCounts+":"+counts());
        } finally {release.countDown();readyRelease.countDown();executor.shutdownNow();}
    }
    public static void main(String[] args) throws Exception {
        sourcePort=args.length==1 && args[0].equals("source");
        for (String mode:new String[]{"disabled","changed","elapsed","default","periodic"}) test(mode);
        System.out.println("SCHEDULED_READY_SHUTDOWN PASS disabled;changed;elapsed;default;periodic;owners");
    }
}
