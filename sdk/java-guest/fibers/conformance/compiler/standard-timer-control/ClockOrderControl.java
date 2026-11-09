import dev.latent.guest.runtime.util.FakeClock;
import dev.latent.guest.runtime.util.Timer;
import dev.latent.guest.runtime.util.TimerTask;
public final class ClockOrderControl {
    private static void run(Class<? extends Throwable> expected, int calls, Runnable action) {
        FakeClock.reset();
        try { action.run(); throw new AssertionError("missing exception"); }
        catch (Throwable error) { if (!expected.isInstance(error)) throw new AssertionError(error); }
        if (FakeClock.calls() != calls) throw new AssertionError("clock calls: " + FakeClock.calls() + " expected " + calls);
    }
    public static void main(String[] args) {
        Timer live = new Timer(true), closed = new Timer(true); closed.cancel();
        try {
            run(IllegalArgumentException.class, 0, () -> live.schedule((TimerTask)null, Long.MAX_VALUE, 0));
            run(IllegalArgumentException.class, 0, () -> live.scheduleAtFixedRate((TimerTask)null, Long.MAX_VALUE, 0));
            run(IllegalArgumentException.class, 0, () -> live.schedule((TimerTask)null, -1, 0));
            run(IllegalArgumentException.class, 0, () -> live.scheduleAtFixedRate((TimerTask)null, -1, 0));
            run(IllegalArgumentException.class, 1, () -> live.schedule((TimerTask)null, Long.MAX_VALUE, 1));
            run(NullPointerException.class, 1, () -> live.schedule((TimerTask)null, 0, 1));
            run(IllegalStateException.class, 1, () -> closed.schedule((TimerTask)null, 0, 1));
            System.out.println("TIMER_CLOCK_ORDER PASS");
        } finally { live.cancel(); closed.cancel(); }
    }
}
