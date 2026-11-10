import java.util.concurrent.ScheduledThreadPoolExecutor;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

public final class ScheduledNoopCancelReferenceControl {
    private static boolean sourcePort;
    private static void await(CountDownLatch latch,String name){
        try{if(!latch.await(5,TimeUnit.SECONDS))throw new AssertionError(name);}
        catch(InterruptedException error){throw new AssertionError(error);}
    }
    private static void idle() throws Exception {
        if(sourcePort)Class.forName("dev.latent.guest.runtime.Activation").getMethod("idle").invoke(null);
    }
    private static void test(boolean cancelled) throws Exception {
        ScheduledThreadPoolExecutor executor=new ScheduledThreadPoolExecutor(1);
        CountDownLatch markerEntered=new CountDownLatch(1),markerRelease=new CountDownLatch(1),returned=new CountDownLatch(1);
        AtomicReference<Boolean> result=new AtomicReference<>();Thread caller=null;ScheduledFuture<?> marker=null;
        try {
            ScheduledFuture<?> target=executor.schedule(()->{},cancelled?60:0,TimeUnit.SECONDS);
            if(cancelled) {if(!target.cancel(false))throw new AssertionError("first-cancel");}
            else {
                target.get(5,TimeUnit.SECONDS);
                marker=executor.schedule(()->{markerEntered.countDown();await(markerRelease,"marker-release");},0,TimeUnit.NANOSECONDS);
                await(markerEntered,"marker-enter");
            }
            boolean early;
            synchronized(executor) {
                caller=new Thread(()->{result.set(target.cancel(false));returned.countDown();},"cancel-caller");caller.start();
                early=returned.await(500,TimeUnit.MILLISECONDS);
            }
            caller.join(5000);if(caller.isAlive() || !early || !Boolean.FALSE.equals(result.get()) || !target.isDone())
                throw new AssertionError("no-op-cancel-blocked");
            markerRelease.countDown();if(marker!=null)marker.get(5,TimeUnit.SECONDS);
        } finally {markerRelease.countDown();if(caller!=null)caller.join(5000);executor.shutdownNow();
                   if(!executor.awaitTermination(5,TimeUnit.SECONDS))throw new AssertionError("termination");}
        idle();
    }
    public static void main(String[] args) throws Exception {
        sourcePort=args.length==1 && args[0].equals("source");test(false);test(true);
        System.out.println("SCHEDULED_NOOP_CANCEL_REFERENCE PASS completed;cancelled;public-monitor");
    }
}
