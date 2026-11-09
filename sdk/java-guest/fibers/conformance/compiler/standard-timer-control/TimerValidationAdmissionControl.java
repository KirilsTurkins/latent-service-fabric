import java.util.Date;
import dev.latent.guest.runtime.Activation;
import dev.latent.guest.runtime.util.Timer;
import dev.latent.guest.runtime.util.TimerTask;
public final class TimerValidationAdmissionControl {
    private static void require(boolean condition) { if (!condition) throw new AssertionError("owner-admission-order"); }
    private static void refused(Class<? extends Throwable> expected, Runnable action) {
        int before = Activation.queued();
        Activation.denyNext = "QueuedWork";
        try { action.run(); throw new AssertionError("missing exception"); }
        catch (Throwable error) { if (!expected.isInstance(error)) throw new AssertionError(error); }
        require(Activation.queued() == before && "QueuedWork".equals(Activation.denyNext));
        Activation.denyNext = null;
    }
    public static void check() throws Exception {
        Timer live = new Timer(true), closed = new Timer(true); closed.cancel();
        try {
            refused(IllegalArgumentException.class, () -> live.schedule((TimerTask)null, new Date(-1)));
            refused(IllegalStateException.class, () -> closed.schedule((TimerTask)null, 0));
            refused(IllegalArgumentException.class, () -> live.schedule(new TimerTask(){ public void run(){} }, (Date)null, 0));
            refused(IllegalArgumentException.class, () -> live.scheduleAtFixedRate(new TimerTask(){ public void run(){} }, (Date)null, 0));
            refused(IllegalArgumentException.class, () -> live.schedule((TimerTask)null, Long.MAX_VALUE));
            refused(NullPointerException.class, () -> live.schedule((TimerTask)null, 0));
            TimerTask retry = new TimerTask(){ public void run(){} };
            Activation.denyNext = "QueuedWork";
            try { live.schedule(retry, 60_000); throw new AssertionError("admission not attempted"); }
            catch (IllegalStateException expected) { require(Activation.denyNext == null && Activation.queued() == 0); }
            live.schedule(retry, 60_000); require(Activation.queued() == 1);
            live.cancel(); require(Activation.queued() == 0);
        } finally { Activation.denyNext = null; live.cancel(); closed.cancel(); Activation.joinWorkers(); }
        require(Activation.owners() == 0);
    }
}
