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
    private static String attempts() {
        return Activation.closeAttempts(Bindings.LatentRuntimeActivationOwnerKind.Executor)+":"
            +Activation.closeAttempts(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork)+":"
            +Activation.closeAttempts(Bindings.LatentRuntimeActivationOwnerKind.Result);
    }
    private static void postDequeue(boolean manual) throws Exception {
        ScheduledReadyFakeClock.now=0; ScheduledReadyFakeClock.failNext=false;
        AtomicReference<Thread> worker=new AtomicReference<>(); AtomicReference<Throwable> failure=new AtomicReference<>();
        Thread.UncaughtExceptionHandler previous=Thread.getDefaultUncaughtExceptionHandler();
        Thread.setDefaultUncaughtExceptionHandler((thread,error)->failure.set(error));
        ScheduledThreadPoolExecutor executor=new ScheduledThreadPoolExecutor(1,action->{
            Thread thread=new Thread(action,"post-dequeue-worker");worker.set(thread);return thread;
        });
        CountDownLatch entered=new CountDownLatch(1), release=new CountDownLatch(1);Thread caller=null;
        try {
            ScheduledFuture<?> task=executor.schedule(()->{
                entered.countDown();
                try {if(!release.await(4,TimeUnit.SECONDS)) throw new AssertionError("post-release");}
                catch(InterruptedException error) {throw new AssertionError(error);}
                if(!manual) ScheduledReadyFakeClock.failNext=true;
            },manual?50_000_000_000L:0,TimeUnit.NANOSECONDS);
            if(manual) {caller=new Thread(()->((Runnable)task).run(),"manual-caller");caller.start();}
            await(entered,"post-entry");
            if(!counts().equals("1:1:1")) throw new AssertionError("post-active-owners");
            if(manual) ScheduledReadyFakeClock.now=50_000_000_000L;
            executor.setExecuteExistingDelayedTasksAfterShutdownPolicy(false);executor.shutdown();
            if(!manual) release.countDown();
            Thread thread=worker.get();if(thread==null) throw new AssertionError("post-worker-missing");thread.join(5000);
            if(thread.isAlive() || failure.get()!=null || !ScheduledReadyFakeClock.failNext || executor.hasPendingWork() || Activation.poisoned)
                throw new AssertionError("post-dequeue-failure",failure.get());
            if(manual) {
                if(task.isDone() || !counts().equals("0:0:1") || !attempts().equals("1:1:0"))
                    throw new AssertionError("manual-result-not-held");
                release.countDown();caller.join(5000);
                if(caller.isAlive() || !task.isDone()) throw new AssertionError("manual-caller-not-retired");
            } else if(!task.isDone()) throw new AssertionError("post-task-not-done");
            if(!counts().equals("0:0:0") || !attempts().equals("1:1:1")) throw new AssertionError("post-owner-settlement");
            Activation.idle();
            System.out.println(manual?"manual-post:result-held-until-caller-return;all-settled-once"
                                     :"normal-post:clock-unread;all-settled-once");
        } finally {
            release.countDown();if(caller!=null)caller.join(5000);ScheduledReadyFakeClock.failNext=false;
            executor.shutdownNow();Thread.setDefaultUncaughtExceptionHandler(previous);
        }
    }
    public static void main(String[] args) throws Exception {
        if(args.length==1 && args[0].equals("failure")) {clockFailure();return;}
        if(args.length==1 && args[0].equals("post")) {postDequeue(false);return;}
        if(args.length==1 && args[0].equals("manual")) {postDequeue(true);return;}
        for(long now:new long[]{49,50,51}) boundary(now);
    }
}
