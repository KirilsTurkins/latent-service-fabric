import dev.latent.guest.runtime.util.Timer;
import dev.latent.guest.runtime.util.TimerTask;
import dev.latent.guest.runtime.Activation;
import dev.latent.generated.Bindings;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

public final class TimerInterruptedSettlementOwnerControl {
    @SuppressWarnings("unchecked") private static <E extends Throwable> void rethrow(Throwable error) throws E { throw (E)error; }
    private static void await(CountDownLatch latch, String label) throws Exception {
        if (!latch.await(5,TimeUnit.SECONDS)) throw new AssertionError(label);
    }
    public static void main(String[] args) throws Exception {
        String thrown=args[0], outcome=args[1];
        CountDownLatch entered=new CountDownLatch(1), proceed=new CountDownLatch(1), terminated=new CountDownLatch(1);
        AtomicReference<Throwable> failure=new AtomicReference<>();
        Thread.UncaughtExceptionHandler prior=Thread.getDefaultUncaughtExceptionHandler();
        Thread.setDefaultUncaughtExceptionHandler((thread,error)->{failure.set(error);terminated.countDown();});
        Timer timer=new Timer("settlement-"+thrown+"-"+outcome,true);
        try {
            timer.schedule(new TimerTask(){@Override public void run(){
                entered.countDown();
                try { if (!proceed.await(5,TimeUnit.SECONDS)) throw new AssertionError("proceed"); }
                catch (InterruptedException error) { throw new AssertionError(error); }
                if (thrown.equals("interrupt")) rethrow(new InterruptedException("guest-interrupt"));
                throw new IllegalArgumentException("guest-primary");
            }},0);
            await(entered,"entered");
            timer.schedule(new TimerTask(){@Override public void run(){throw new AssertionError("witness-ran");}},60_000);
            Activation.failQueuedSettlement=outcome;
            proceed.countDown(); await(terminated,"terminated");
            Thread worker=Activation.lastWorker; worker.join(5000);
            Throwable observed=failure.get();
            String expected=thrown.equals("interrupt") ? "source-queued-settlement-"+outcome : "guest-primary";
            if (worker.isAlive() || observed==null || !expected.equals(observed.getMessage())) throw new AssertionError("wrong-primary",observed);
            int queued=outcome.equals("lost") ? 0 : 1;
            if (!Activation.poisoned() || !Activation.retainedFailedQueued() || Activation.failedOwnerLinks()!=1
                || Activation.queued()!=queued || Activation.executors()!=1 || Activation.queuedAttempts()!=2
                || timer.isRetired() || !timer.hasPendingWork()) throw new AssertionError("owner-not-retained");
            boolean refused=false;
            try { Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork); }
            catch (IllegalStateException denied) { refused=true; }
            if (!refused) throw new AssertionError("poisoned-admission");
            System.out.println(thrown+":"+outcome+":primary="+observed.getMessage()+":poisoned=true:retained=true:queued="+queued+":executors=1:attempts=2");
        } finally { proceed.countDown(); Thread.setDefaultUncaughtExceptionHandler(prior); }
    }
}
