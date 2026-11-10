import dev.latent.guest.runtime.concurrent.ScheduledThreadPoolExecutor;
import dev.latent.guest.runtime.Activation;
import dev.latent.generated.Bindings;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

public final class ScheduledNoopCancelOwnerControl {
    private static int count(Bindings.LatentRuntimeActivationOwnerKind kind) {return Activation.count(kind);}
    private static int attempts(Bindings.LatentRuntimeActivationOwnerKind kind) {return Activation.closeAttempts(kind);}
    private static String counts() {return count(Bindings.LatentRuntimeActivationOwnerKind.Executor)+":"
        +count(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork)+":"+count(Bindings.LatentRuntimeActivationOwnerKind.Result);}
    private static void await(CountDownLatch latch,String name){try{if(!latch.await(5,TimeUnit.SECONDS))throw new AssertionError(name);}catch(InterruptedException e){throw new AssertionError(e);}}
    private static boolean secondCancelWhileHeld(ScheduledThreadPoolExecutor executor,ScheduledFuture<?> task) throws Exception {
        CountDownLatch returned=new CountDownLatch(1);AtomicReference<Boolean> result=new AtomicReference<>();Thread caller;
        boolean early;
        synchronized(executor) {
            caller=new Thread(()->{result.set(task.cancel(false));returned.countDown();},"second-cancel");caller.start();
            early=returned.await(500,TimeUnit.MILLISECONDS);
        }
        caller.join(5000);if(caller.isAlive() || !Boolean.FALSE.equals(result.get()))throw new AssertionError("second-cancel");
        return early;
    }
    private static void copied() throws Exception {
        ScheduledThreadPoolExecutor executor=new ScheduledThreadPoolExecutor(1);
        try {
            ScheduledFuture<?> task=executor.schedule(()->{},60,TimeUnit.SECONDS);((Runnable)task).run();
            if(!task.isDone() || !counts().equals("1:1:0") || !executor.hasPendingWork())throw new AssertionError("copy-precondition");
            if(task.cancel(false) || !counts().equals("1:0:0") || executor.hasPendingWork()
                || attempts(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork)!=1) throw new AssertionError("completed-copy-not-withdrawn");
            executor.shutdown();if(!executor.awaitTermination(5,TimeUnit.SECONDS))throw new AssertionError("copy-termination");
            Activation.idle();System.out.println("completed-copy:cancel=false:withdrawn=true:settled-once=true");
        } finally {executor.shutdownNow();}
    }
    private static void cancelled() throws Exception {
        ScheduledThreadPoolExecutor executor=new ScheduledThreadPoolExecutor(1);
        try {
            ScheduledFuture<?> task=executor.schedule(()->{},60,TimeUnit.SECONDS);
            if(!task.cancel(false) || !counts().equals("1:0:0"))throw new AssertionError("first-cancel");
            boolean early=secondCancelWhileHeld(executor,task);
            if(!early) throw new AssertionError("cancelled-noop-blocked");
            executor.shutdown();if(!executor.awaitTermination(5,TimeUnit.SECONDS))throw new AssertionError("cancel-termination");
            Activation.idle();System.out.println("cancelled:returnedWhileHeld="+early+":settled-once="
                +(attempts(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork)==1));
        } finally {executor.shutdownNow();}
    }
    private static void running() throws Exception {
        ScheduledThreadPoolExecutor executor=new ScheduledThreadPoolExecutor(1);CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        try {
            ScheduledFuture<?> task=executor.schedule(()->{entered.countDown();await(release,"running-release");},0,TimeUnit.NANOSECONDS);
            await(entered,"running-entry");if(!task.cancel(false))throw new AssertionError("running-cancel");
            if(!counts().equals("1:1:1") || !executor.hasPendingWork())throw new AssertionError("running-owners");
            boolean early=secondCancelWhileHeld(executor,task);
            if(early) throw new AssertionError("running-copy-skipped");
            if(!counts().equals("1:1:1") || !executor.hasPendingWork())throw new AssertionError("running-early-retirement");
            release.countDown();executor.shutdown();if(!executor.awaitTermination(5,TimeUnit.SECONDS))throw new AssertionError("running-termination");
            Activation.idle();System.out.println("running:returnedWhileHeld="+early+":original-owners-held=true:settled-once="
                +(attempts(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork)==1));
        } finally {release.countDown();executor.shutdownNow();}
    }
    private static void manual() throws Exception {
        ScheduledThreadPoolExecutor executor=new ScheduledThreadPoolExecutor(1);
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);Thread caller=null;
        try {
            ScheduledFuture<?> task;
            // The manual caller enters first; the pool worker can dequeue its
            // occurrence only after this monitor is released.
            synchronized(executor) {
                task=executor.schedule(()->{entered.countDown();await(release,"manual-release");},0,TimeUnit.NANOSECONDS);
                ScheduledFuture<?> selected=task;
                caller=new Thread(()->((Runnable)selected).run(),"manual-caller");caller.start();await(entered,"manual-entry");
            }
            long deadline=System.nanoTime()+5_000_000_000L;
            while(count(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork)!=0) {
                if(System.nanoTime()-deadline>=0)throw new AssertionError("manual-copy-not-retired");Thread.sleep(1);
            }
            if(!counts().equals("1:0:1") || task.isDone() || !task.cancel(false)) throw new AssertionError("manual-precondition");
            boolean early=secondCancelWhileHeld(executor,task);
            if(!early || !counts().equals("1:0:1"))throw new AssertionError("manual-result-not-held");
            release.countDown();caller.join(5000);if(caller.isAlive())throw new AssertionError("manual-not-retired");
            executor.shutdown();if(!executor.awaitTermination(5,TimeUnit.SECONDS))throw new AssertionError("manual-termination");
            Activation.idle();
            if(attempts(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork)!=1 || attempts(Bindings.LatentRuntimeActivationOwnerKind.Result)!=1)
                throw new AssertionError("manual-settlement-count");
            System.out.println("manual:returnedWhileHeld=true:result-held=true:settled-once=true");
        } finally {release.countDown();if(caller!=null)caller.join(5000);executor.shutdownNow();}
    }
    private static void uncertain(String mode) throws Exception {
        ScheduledThreadPoolExecutor executor=new ScheduledThreadPoolExecutor(1);
        try {
            ScheduledFuture<?> task=executor.schedule(()->{},60,TimeUnit.SECONDS);
            if(mode.equals("refused"))Activation.denyCloseNext="QueuedWork";else Activation.loseCloseAckNext="QueuedWork";
            boolean threw=false;try{task.cancel(false);}catch(IllegalStateException expected){threw=true;}
            int queued=mode.equals("refused")?1:0;
            if(!threw || !Activation.poisoned || !Activation.retainsFailedQueued() || Activation.failedLeaseAttempts()!=1
                || !counts().equals("1:"+queued+":0") || !executor.hasPendingWork())throw new AssertionError("uncertain-precondition");
            boolean early=secondCancelWhileHeld(executor,task);
            if(!early) throw new AssertionError("uncertain-noop-blocked");
            if(!Activation.poisoned || !Activation.retainsFailedQueued() || Activation.failedLeaseAttempts()!=1
                || !counts().equals("1:"+queued+":0") || !executor.hasPendingWork())throw new AssertionError("uncertain-owner-lost");
            System.out.println(mode+":returnedWhileHeld="+early+":poisoned=true:original-retained=true:attempts=1");
        } finally {executor.shutdownNow();}
    }
    public static void main(String[] args) throws Exception {
        switch(args[0]){case "copy" -> copied();case "cancelled" -> cancelled();case "running" -> running();case "manual" -> manual();default -> uncertain(args[0]);}
    }
}
