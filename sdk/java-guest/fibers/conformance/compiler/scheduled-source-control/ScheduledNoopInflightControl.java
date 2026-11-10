import dev.latent.guest.runtime.concurrent.ScheduledThreadPoolExecutor;
import dev.latent.guest.runtime.Activation;
import dev.latent.generated.Bindings;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

public final class ScheduledNoopInflightControl {
    private static String counts() {return Activation.count(Bindings.LatentRuntimeActivationOwnerKind.Executor)+":"
        +Activation.count(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork)+":"
        +Activation.count(Bindings.LatentRuntimeActivationOwnerKind.Result);}
    private static void await(CountDownLatch latch,String name) {
        try{if(!latch.await(5,TimeUnit.SECONDS))throw new AssertionError(name);}
        catch(InterruptedException error){throw new AssertionError(error);}
    }
    public static void main(String[] args) throws Exception {
        String mode=args[0];ScheduledThreadPoolExecutor executor=new ScheduledThreadPoolExecutor(1);
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1),secondReturned=new CountDownLatch(1);
        AtomicReference<String> held=new AtomicReference<>();AtomicReference<Throwable> firstError=new AtomicReference<>();
        AtomicReference<Boolean> firstResult=new AtomicReference<>(),secondResult=new AtomicReference<>();Thread first=null,second=null;
        try {
            ScheduledFuture<?> task=executor.schedule(()->{},60,TimeUnit.SECONDS);
            Activation.closeObservationKind="QueuedWork";
            Activation.closeObservation=()->{held.set(counts());entered.countDown();await(release,"settlement-release");};
            if(mode.equals("refused"))Activation.denyCloseNext="QueuedWork";
            if(mode.equals("lost"))Activation.loseCloseAckNext="QueuedWork";
            first=new Thread(()->{try{firstResult.set(task.cancel(false));}catch(Throwable error){firstError.set(error);}},"first-cancel");first.start();await(entered,"settlement-entry");
            second=new Thread(()->{secondResult.set(task.cancel(false));secondReturned.countDown();},"second-cancel");second.start();
            boolean early=secondReturned.await(500,TimeUnit.MILLISECONDS);release.countDown();first.join(5000);second.join(5000);
            if(!early)throw new AssertionError("inflight-noop-blocked");
            if(first.isAlive() || second.isAlive() || !Boolean.FALSE.equals(secondResult.get()) || !"1:1:0".equals(held.get())
                || Activation.closeAttempts(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork)!=1)throw new AssertionError("inflight-check");
            if(mode.equals("success")) {
                if(!Boolean.TRUE.equals(firstResult.get()) || firstError.get()!=null || !counts().equals("1:0:0") || Activation.poisoned)
                    throw new AssertionError("inflight-success");
                executor.shutdown();if(!executor.awaitTermination(5,TimeUnit.SECONDS))throw new AssertionError("termination");Activation.idle();
            } else {
                int queued=mode.equals("refused")?1:0;
                if(!(firstError.get() instanceof IllegalStateException) || !Activation.poisoned || !Activation.retainsFailedQueued()
                    || Activation.failedLeaseAttempts()!=1 || !executor.hasPendingWork() || !counts().equals("1:"+queued+":0"))
                    throw new AssertionError("inflight-uncertainty");
            }
            System.out.println(mode+":secondReturnedWhileSettlementPending="+early+":held="+held.get()
                +":settlementAttempts=1:poisoned="+Activation.poisoned+":remaining="+counts());
        } finally {release.countDown();if(first!=null)first.join(5000);if(second!=null)second.join(5000);executor.shutdownNow();}
    }
}
