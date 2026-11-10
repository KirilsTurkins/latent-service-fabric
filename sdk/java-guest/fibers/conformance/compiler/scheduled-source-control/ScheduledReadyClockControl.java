import dev.latent.guest.runtime.concurrent.ScheduledThreadPoolExecutor;
import dev.latent.guest.runtime.concurrent.ScheduledReadyFakeClock;
import dev.latent.guest.runtime.Activation;
import dev.latent.generated.Bindings;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

public final class ScheduledReadyClockControl {
    private static String counts() {
        return Activation.count(Bindings.LatentRuntimeActivationOwnerKind.Executor)+":"
            +Activation.count(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork)+":"
            +Activation.count(Bindings.LatentRuntimeActivationOwnerKind.Result);
    }
    private static void await(CountDownLatch latch,String label) throws Exception {
        if (!latch.await(4,TimeUnit.SECONDS)) throw new AssertionError(label);
    }
    private static void boundary(long now) throws Exception {
        ScheduledReadyFakeClock.now=0; ScheduledThreadPoolExecutor executor=new ScheduledThreadPoolExecutor(1);
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1),ready=new CountDownLatch(1),finish=new CountDownLatch(1);
        try {
            executor.execute(()->{entered.countDown();try { if(!release.await(4,TimeUnit.SECONDS)) throw new AssertionError("release"); }catch(InterruptedException e){throw new AssertionError(e);}});
            await(entered,"entered");
            ScheduledFuture<?> task=executor.schedule(()->{ready.countDown();try {if(!finish.await(4,TimeUnit.SECONDS)) throw new AssertionError("finish");}catch(InterruptedException e){throw new AssertionError(e);}},50,TimeUnit.NANOSECONDS);
            ScheduledReadyFakeClock.now=now; executor.setExecuteExistingDelayedTasksAfterShutdownPolicy(false); executor.shutdown();
            boolean cancelled=task.isCancelled(); String held=counts();
            if(cancelled!=(now<50)) throw new AssertionError("wrong-deadline-eligibility");
            release.countDown(); String active="none";
            if(!cancelled) {await(ready,"ready"); active=counts();}
            finish.countDown();
            if(!executor.awaitTermination(4,TimeUnit.SECONDS)) throw new AssertionError("termination");
            Activation.idle();
            System.out.println("boundary="+now+":cancelled="+cancelled+":held="+held+":active="+active+":final="+counts());
        } finally {release.countDown();finish.countDown();executor.shutdownNow();}
    }
    private static void clockFailure() throws Exception {
        ScheduledReadyFakeClock.now=0; AtomicReference<Thread> worker=new AtomicReference<>();
        ScheduledThreadPoolExecutor executor=new ScheduledThreadPoolExecutor(1,action->{Thread t=new Thread(action,"clock-worker");worker.set(t);return t;});
        try {
            ScheduledFuture<?> task=executor.schedule(()->{throw new AssertionError("future-ran");},60,TimeUnit.SECONDS);
            long end=System.nanoTime()+4_000_000_000L;
            while(worker.get()==null || worker.get().getState()!=Thread.State.TIMED_WAITING) {
                if(System.nanoTime()-end>=0) throw new AssertionError("worker-not-waiting");Thread.sleep(1);
            }
            executor.setExecuteExistingDelayedTasksAfterShutdownPolicy(false);
            boolean threw=false; String held;
            synchronized(executor) {
                ScheduledReadyFakeClock.failNext=true;
                try {executor.shutdown();} catch(IllegalStateException expected) {threw=expected.getMessage().equals("synthetic-clock-failure");}
                held=counts();
                if(!threw || task.isCancelled() || !executor.hasPendingWork() || !held.equals("1:1:1")) throw new AssertionError("clock-failure-lost-owner");
            }
            if(!executor.awaitTermination(4,TimeUnit.SECONDS)) throw new AssertionError("clock-failure-no-wakeup");
            if(!task.isCancelled()) throw new AssertionError("future-not-cancelled");
            Activation.idle();
            System.out.println("clock-failure=propagated:held="+held+":laterCancelled=true:final="+counts());
        } finally {ScheduledReadyFakeClock.failNext=false;executor.shutdownNow();}
    }
    public static void main(String[] args) throws Exception {
        if(args.length==1 && args[0].equals("failure")) {clockFailure();return;}
        for(long now:new long[]{49,50,51}) boundary(now);
    }
}
