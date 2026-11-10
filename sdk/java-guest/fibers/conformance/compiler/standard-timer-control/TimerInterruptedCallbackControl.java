import java.util.Timer;
import java.util.TimerTask;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

public final class TimerInterruptedCallbackControl {
    private static boolean sourcePort;
    private static Class<?> ledger() throws ClassNotFoundException { return Class.forName("dev.latent.guest.runtime.Activation"); }
    private static int count(String name) {
        if (!sourcePort) return -1;
        try { return (Integer)ledger().getMethod(name).invoke(null); }
        catch (ReflectiveOperationException error) { throw new AssertionError(error); }
    }
    private static void retire() throws Exception {
        if (!sourcePort) return;
        ledger().getMethod("joinWorkers").invoke(null);
        if (count("owners") != 0) throw new AssertionError("unretired-ledger");
    }
    private static final class DerivedInterrupt extends InterruptedException { }
    @SuppressWarnings("unchecked") private static <E extends Throwable> void rethrow(Throwable error) throws E { throw (E)error; }
    private static void await(CountDownLatch latch, String label) {
        try { if (!latch.await(5,TimeUnit.SECONDS)) throw new AssertionError(label); }
        catch (InterruptedException error) { throw new AssertionError(error); }
    }
    private static int queued() { return count("queued"); }
    private static void test(String mode) throws Exception {
        CountDownLatch firstEntered=new CountDownLatch(1), firstRelease=new CountDownLatch(1);
        CountDownLatch boundary=new CountDownLatch(1), witnessRelease=new CountDownLatch(1);
        AtomicReference<Throwable> error=new AtomicReference<>(); AtomicInteger calls=new AtomicInteger();
        AtomicReference<Boolean> witnessFlag=new AtomicReference<>();
        Thread.UncaughtExceptionHandler prior=Thread.getDefaultUncaughtExceptionHandler();
        Thread.setDefaultUncaughtExceptionHandler((thread,failure)->{ error.set(failure); boundary.countDown(); });
        Timer timer=new Timer("interrupt-"+mode,true);
        try {
            TimerTask task=new TimerTask() { @Override public void run() {
                int n=calls.incrementAndGet();
                if (n==1) {
                    firstEntered.countDown(); await(firstRelease,"first-release");
                    if (mode.equals("runtime")) rethrow(new IllegalStateException("expected-runtime"));
                    if (mode.equals("error")) rethrow(new AssertionError("expected-error"));
                    if (mode.endsWith("-sleep")) {
                        Thread.currentThread().interrupt();
                        try { Thread.sleep(0); throw new AssertionError("sleep-did-not-interrupt"); }
                        catch (InterruptedException interrupted) { rethrow(interrupted); }
                    }
                    if (mode.endsWith("-flag")) Thread.currentThread().interrupt();
                    if (mode.endsWith("-subclass")) rethrow(new DerivedInterrupt());
                    rethrow(new InterruptedException("expected-interrupt"));
                }
                witnessFlag.set(Thread.interrupted()); boundary.countDown(); await(witnessRelease,"periodic-release");
            }};
            if (mode.startsWith("periodic")) timer.scheduleAtFixedRate(task,0,10);
            else timer.schedule(task,0);
            await(firstEntered,"first-entry");
            if (!mode.startsWith("periodic")) timer.schedule(new TimerTask() { @Override public void run() {
                witnessFlag.set(Thread.interrupted()); boundary.countDown(); await(witnessRelease,"witness-release");
            }},0);
            int before=queued(); firstRelease.countDown(); await(boundary,"boundary");
            boolean survived=error.get()==null;
            int atBoundary=queued();
            boolean accepted;
            try { timer.schedule(new TimerTask() { @Override public void run() { throw new AssertionError("late-execution"); } },60_000); accepted=true; }
            catch (IllegalStateException stopped) { accepted=false; }
            timer.cancel(); int afterCancel=queued(); witnessRelease.countDown();
            retire();
            System.out.println(mode+":survived="+survived+":accepted="+accepted+":calls="+calls.get()
                +":error="+(error.get()==null?"none":error.get().getClass().getSimpleName())
                +":flag="+(witnessFlag.get()==null?"none":witnessFlag.get())+":queued="+before+","+atBoundary+","+afterCancel+":owners="+count("owners"));
        } finally { firstRelease.countDown(); timer.cancel(); witnessRelease.countDown(); Thread.setDefaultUncaughtExceptionHandler(prior); }
    }
    public static void main(String[] args) throws Exception {
        sourcePort = args.length == 1 && args[0].equals("source");
        for (String mode:new String[]{"once-direct","periodic-direct","once-sleep","periodic-sleep","once-flag","once-subclass","runtime","error"}) test(mode);
    }
}
