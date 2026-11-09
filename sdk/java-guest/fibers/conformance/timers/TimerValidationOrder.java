import java.util.Date;
import java.util.Timer;
import java.util.TimerTask;
public final class TimerValidationOrder {
    static final class Marker extends RuntimeException { }
    static final class ProbeDate extends Date {
        int calls;
        ProbeDate() { super(0); }
        @Override public long getTime() { calls++; throw new Marker(); }
    }
    static Timer live, closed;
    static final StringBuilder observed = new StringBuilder();
    static void record(String value) { observed.append(value).append('\n'); }
    static TimerTask task() { return new TimerTask() { @Override public void run() { } }; }
    static void run(String label, Runnable action) {
        try { action.run(); record(label + "=none"); }
        catch (Throwable error) { record(label + "=" + error.getClass().getSimpleName()); }
    }
    public static void check() {
        observed.setLength(0);
        if (System.currentTimeMillis() <= 0) throw new AssertionError("positive epoch required");
        live = new Timer(true); closed = new Timer(true); closed.cancel();
        try {
            run("delay-null-negative", () -> live.schedule((TimerTask)null, -1));
            run("delay-null-overflow", () -> live.schedule((TimerTask)null, Long.MAX_VALUE));
            run("delay-null-valid", () -> live.schedule((TimerTask)null, 0));
            run("delay-closed-null-valid", () -> closed.schedule((TimerTask)null, 0));
            run("delay-closed-null-negative", () -> closed.schedule((TimerTask)null, -1));
            run("date-null-task-negative", () -> live.schedule((TimerTask)null, new Date(-1)));
            run("date-null-task-valid", () -> live.schedule((TimerTask)null, new Date(0)));
            run("date-null-date", () -> live.schedule(task(), (Date)null));
            run("date-closed-null-date", () -> closed.schedule(task(), (Date)null));
            run("date-closed-null-task-valid", () -> closed.schedule((TimerTask)null, new Date(0)));
            run("date-closed-null-task-negative", () -> closed.schedule((TimerTask)null, new Date(-1)));
            run("delay-period-nulltask-negdelay", () -> live.schedule((TimerTask)null, -1, 0));
            run("delay-period-nulltask-overflow", () -> live.schedule((TimerTask)null, Long.MAX_VALUE, 1));
            run("delay-period-nulltask-zero", () -> live.schedule((TimerTask)null, 0, 0));
            run("delay-period-closed-nulltask", () -> closed.schedule((TimerTask)null, 0, 1));
            run("delay-rate-nulltask-negative", () -> live.scheduleAtFixedRate((TimerTask)null, -1, 0));
            run("delay-rate-nulltask-overflow", () -> live.scheduleAtFixedRate((TimerTask)null, Long.MAX_VALUE, 1));
            run("delay-rate-nulltask-zero", () -> live.scheduleAtFixedRate((TimerTask)null, 0, 0));
            run("delay-rate-closed-nulltask", () -> closed.scheduleAtFixedRate((TimerTask)null, 0, 1));
            run("date-period-null-date-zero", () -> live.schedule(task(), (Date)null, 0));
            run("date-rate-null-date-zero", () -> live.scheduleAtFixedRate(task(), (Date)null, 0));
            run("date-period-null-date-valid", () -> live.schedule(task(), (Date)null, 1));
            run("date-rate-null-date-valid", () -> live.scheduleAtFixedRate(task(), (Date)null, 1));
            run("date-period-nulltask-negative", () -> live.schedule((TimerTask)null, new Date(-1), 1));
            run("date-rate-nulltask-negative", () -> live.scheduleAtFixedRate((TimerTask)null, new Date(-1), 1));
            run("date-period-closed-nulltask", () -> closed.schedule((TimerTask)null, new Date(0), 1));
            run("date-rate-closed-nulltask", () -> closed.scheduleAtFixedRate((TimerTask)null, new Date(0), 1));
            ProbeDate a = new ProbeDate(); run("date-period-throw-zero", () -> live.schedule(task(), a, 0)); record("date-period-throw-zero-calls=" + a.calls);
            ProbeDate b = new ProbeDate(); run("date-rate-throw-zero", () -> live.scheduleAtFixedRate(task(), b, 0)); record("date-rate-throw-zero-calls=" + b.calls);
            ProbeDate c = new ProbeDate(); run("date-period-throw-valid", () -> closed.schedule(task(), c, 1)); record("date-period-throw-valid-calls=" + c.calls);
            ProbeDate d = new ProbeDate(); run("date-rate-throw-valid", () -> closed.scheduleAtFixedRate(task(), d, 1)); record("date-rate-throw-valid-calls=" + d.calls);
        } finally { live.cancel(); closed.cancel(); }
        String expected = String.join("\n",
            "delay-null-negative=IllegalArgumentException",
            "delay-null-overflow=IllegalArgumentException",
            "delay-null-valid=NullPointerException",
            "delay-closed-null-valid=IllegalStateException",
            "delay-closed-null-negative=IllegalArgumentException",
            "date-null-task-negative=IllegalArgumentException",
            "date-null-task-valid=NullPointerException",
            "date-null-date=NullPointerException",
            "date-closed-null-date=NullPointerException",
            "date-closed-null-task-valid=IllegalStateException",
            "date-closed-null-task-negative=IllegalArgumentException",
            "delay-period-nulltask-negdelay=IllegalArgumentException",
            "delay-period-nulltask-overflow=IllegalArgumentException",
            "delay-period-nulltask-zero=IllegalArgumentException",
            "delay-period-closed-nulltask=IllegalStateException",
            "delay-rate-nulltask-negative=IllegalArgumentException",
            "delay-rate-nulltask-overflow=IllegalArgumentException",
            "delay-rate-nulltask-zero=IllegalArgumentException",
            "delay-rate-closed-nulltask=IllegalStateException",
            "date-period-null-date-zero=IllegalArgumentException",
            "date-rate-null-date-zero=IllegalArgumentException",
            "date-period-null-date-valid=NullPointerException",
            "date-rate-null-date-valid=NullPointerException",
            "date-period-nulltask-negative=IllegalArgumentException",
            "date-rate-nulltask-negative=IllegalArgumentException",
            "date-period-closed-nulltask=IllegalStateException",
            "date-rate-closed-nulltask=IllegalStateException",
            "date-period-throw-zero=IllegalArgumentException",
            "date-period-throw-zero-calls=0",
            "date-rate-throw-zero=IllegalArgumentException",
            "date-rate-throw-zero-calls=0",
            "date-period-throw-valid=Marker",
            "date-period-throw-valid-calls=1",
            "date-rate-throw-valid=Marker",
            "date-rate-throw-valid-calls=1") + "\n";
        if (!observed.toString().equals(expected)) throw new AssertionError("timer-validation-order: " + observed);
    }
}
