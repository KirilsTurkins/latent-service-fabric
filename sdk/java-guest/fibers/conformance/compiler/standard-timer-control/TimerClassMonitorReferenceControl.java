import java.util.Timer;
import java.util.TimerTask;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

public final class TimerClassMonitorReferenceControl {
    private static boolean sourcePort;
    private static void retire() throws Exception {
        if (!sourcePort) return;
        Class<?> ledger = Class.forName("dev.latent.guest.runtime.Activation");
        ledger.getMethod("joinWorkers").invoke(null);
        if ((Integer)ledger.getMethod("owners").invoke(null) != 0) throw new AssertionError("unretired-ledger");
    }
    private static void cleanup() throws Exception {
        if (sourcePort) Class.forName("dev.latent.guest.runtime.Activation").getMethod("cleanup").invoke(null);
    }
    private static void run(String mode) throws Exception {
        CountDownLatch entered = new CountDownLatch(1), callbacks = new CountDownLatch(3);
        CountDownLatch contenderStarted = new CountDownLatch(1), contenderEntered = new CountDownLatch(1);
        AtomicReference<Timer> timer = new AtomicReference<>();
        AtomicReference<Throwable> failure = new AtomicReference<>();
        AtomicInteger once = new AtomicInteger(), repeated = new AtomicInteger();
        Thread caller = new Thread(() -> {
            entered.countDown();
            try {
                Timer selected = mode.equals("default") ? new Timer() :
                    mode.equals("daemon") ? new Timer(true) : new Timer("named-control", true);
                timer.set(selected);
                selected.schedule(new TimerTask() {
                    @Override public void run() { once.incrementAndGet(); callbacks.countDown(); }
                }, 0);
                selected.schedule(new TimerTask() {
                    @Override public void run() {
                        int count = repeated.incrementAndGet();
                        if (count <= 2) callbacks.countDown();
                        if (count == 2) cancel();
                    }
                }, 0, 10);
            } catch (Throwable error) { failure.set(error); }
        });
        caller.setDaemon(true);
        Thread contender = new Thread(() -> {
            contenderStarted.countDown();
            synchronized (Timer.class) { contenderEntered.countDown(); }
        });
        contender.setDaemon(true);
        boolean completedWhileHeld;
        Thread.State observed;
        try {
            synchronized (Timer.class) {
                contender.start();
                if (!contenderStarted.await(5, TimeUnit.SECONDS)) throw new AssertionError("contender-not-started");
                caller.start();
                if (!entered.await(5, TimeUnit.SECONDS)) throw new AssertionError("caller-not-started");
                completedWhileHeld = callbacks.await(1500, TimeUnit.MILLISECONDS);
                observed = caller.getState();
                if (contenderEntered.getCount() == 0) throw new AssertionError("public-monitor-bypassed");
            }
            contender.join(5000);
            if (contender.isAlive() || contenderEntered.getCount() != 0) throw new AssertionError("public-monitor-not-released");
            caller.join(5000);
            if (caller.isAlive() || failure.get() != null) throw new AssertionError("construction-failed", failure.get());
            if (!callbacks.await(5, TimeUnit.SECONDS) || once.get() != 1 || repeated.get() != 2)
                throw new AssertionError("callback-not-complete");
        } finally {
            Timer selected = timer.get();
            if (selected != null) selected.cancel();
            caller.join(5000);
        }
        retire();
        System.out.println(mode + ":whileHeld=" + completedWhileHeld + ":blocked="
            + (observed == Thread.State.BLOCKED) + ":once=" + once.get() + ":recurring=" + repeated.get()
            + ":publicMonitor=preserved");
    }
    public static void main(String[] args) throws Exception {
        sourcePort = args.length == 1 && args[0].equals("source");
        Class.forName(Timer.class.getName());
        run("default"); run("daemon"); run("named");
        cleanup();
    }
}
