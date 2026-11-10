import dev.latent.guest.runtime.util.Timer;
import dev.latent.guest.runtime.util.TimerTask;
import dev.latent.generated.Bindings;
import dev.latent.guest.runtime.Activation;
import java.lang.reflect.Field;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

public final class TimerCancelledSettlementOwnerControl {
    public static void main(String[] args) throws Exception {
        String mode=args[0];
        Timer timer=new Timer("cancelled-tail-settlement",true);
        Thread worker=Activation.lastWorker;
        AtomicReference<Throwable> failure=new AtomicReference<>();
        AtomicBoolean earlyRetirement=new AtomicBoolean();
        CountDownLatch witnessEntered=new CountDownLatch(1), witnessRelease=new CountDownLatch(1), boundary=new CountDownLatch(1);
        worker.setUncaughtExceptionHandler((thread,error) -> { failure.set(error); boundary.countDown(); });
        Field field=Timer.class.getDeclaredField("lock"); field.setAccessible(true); Object lock=field.get(timer);
        synchronized(lock) {
            timer.scheduleAtFixedRate(new TimerTask() { @Override public void run() { throw new AssertionError("head-ran"); } },60_000,60_000);
            TimerTask cancelled=new TimerTask() { @Override public void run() { throw new AssertionError("cancelled-ran"); } };
            timer.schedule(cancelled,120_000,60_000);
            if (!cancelled.cancel()) throw new AssertionError("cancel-failed");
            timer.schedule(new TimerTask() { @Override public void run() {
                witnessEntered.countDown();
                boundary.countDown();
                try { if (!witnessRelease.await(5,TimeUnit.SECONDS)) throw new AssertionError("witness-release"); }
                catch (InterruptedException error) { throw new AssertionError(error); }
            }},0);
            Activation.onQueuedSettlement=() -> { if (Activation.retireIfIdle(timer)) earlyRetirement.set(true); };
            Activation.failQueuedSettlement=mode;
        }
        if (!boundary.await(5,TimeUnit.SECONDS)) throw new AssertionError("settlement-boundary-timeout");
        boolean witness=witnessEntered.getCount()==0;
        if (witness) {
            // The old implementation reached the witness without attempting
            // the cancelled tail's settlement. Clear the synthetic fault only
            // after this negative observation, then retire normally.
            Activation.failQueuedSettlement=null;
            timer.cancel(); witnessRelease.countDown(); worker.join(5000);
            if (worker.isAlive() || Activation.owners()!=0 || earlyRetirement.get()) throw new AssertionError("old-cleanup");
            throw new AssertionError("cancelled-tail-settlement-not-attempted");
        } else {
            worker.join(5000);
            if (worker.isAlive() || failure.get()==null || !failure.get().getMessage().equals("source-queued-settlement-"+mode))
                throw new AssertionError("expected-settlement-failure",failure.get());
            int expectedQueued=mode.equals("lost") ? 0 : 1;
            if (!Activation.poisoned() || !Activation.retainedFailedQueued() || Activation.failedOwnerLinks()!=1
                    || Activation.queued()!=expectedQueued || Activation.executors()!=1 || timer.isRetired()
                    || !timer.hasPendingWork() || earlyRetirement.get() || Activation.queuedAttempts()!=3)
                throw new AssertionError("uncertain-custody-not-retained");
            boolean refused=false;
            try { Activation.owner(Bindings.LatentRuntimeActivationOwnerKind.QueuedWork); }
            catch (IllegalStateException expected) { refused=true; }
            if (!refused) throw new AssertionError("poisoned-admission-accepted");
            System.out.println(mode+":witness=false:poisoned=true:retained=true:queued="+Activation.queued()
                +":executors="+Activation.executors()+":attempts="+Activation.queuedAttempts()+":admission=refused");
        }
    }
}
