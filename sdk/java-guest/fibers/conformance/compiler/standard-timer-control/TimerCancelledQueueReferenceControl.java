import java.util.Timer;
import java.util.TimerTask;
import java.util.ArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

public final class TimerCancelledQueueReferenceControl {
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
    private static void cleanup() throws Exception { if (sourcePort) ledger().getMethod("cleanup").invoke(null); }
    private static int queued() { return count("queued"); }
    private static int registrations() { return count("queuedRegistrations"); }
    private static String displayRemoved(int removed, int maximum) {
        if (removed == -1 || sourcePort) return Integer.toString(removed);
        if (removed < 0 || removed > maximum) throw new AssertionError("invalid-purge-count");
        return "valid";
    }
    private static void await(CountDownLatch latch, String name) {
        try { if (!latch.await(5, TimeUnit.SECONDS)) throw new AssertionError(name); }
        catch (InterruptedException error) { throw new AssertionError(error); }
    }
    private static void capacity(boolean purge) throws Exception {
        Timer timer = new Timer("cancelled-capacity", true);
        CountDownLatch gateEntered = new CountDownLatch(1), gateRelease = new CountDownLatch(1);
        CountDownLatch witnessEntered = new CountDownLatch(1), witnessRelease = new CountDownLatch(1);
        AtomicInteger unexpected = new AtomicInteger();
        try {
            timer.schedule(new TimerTask() { @Override public void run() { gateEntered.countDown(); await(gateRelease,"gate-release"); } }, 0);
            await(gateEntered,"gate-enter");
            timer.scheduleAtFixedRate(new TimerTask() { @Override public void run() { unexpected.incrementAndGet(); } }, 60_000, 60_000);
            ArrayList<TimerTask> cancelled = new ArrayList<>();
            for (int i=0;i<5;i++) {
                TimerTask task = new TimerTask() { @Override public void run() { unexpected.incrementAndGet(); } };
                if ((i & 1) == 0) timer.schedule(task, 120_000, 60_000); else timer.schedule(task, 120_000);
                if (!task.cancel()) throw new AssertionError("cancel-failed");
                cancelled.add(task);
            }
            timer.schedule(new TimerTask() { @Override public void run() { witnessEntered.countDown(); await(witnessRelease,"witness-release"); } }, 0);
            int beforeRelease=queued(); gateRelease.countDown(); await(witnessEntered,"witness-enter");
            int atWitness=queued(), removed=purge ? timer.purge() : -1, afterPurge=queued();
            if (purge && timer.purge()!=0) throw new AssertionError("cancelled-tail-not-purged");
            int beforeReschedule=registrations();
            boolean rescheduleRefused=false;
            try { timer.schedule(cancelled.get(0), 180_000); } catch (IllegalStateException expected) { rescheduleRefused=true; }
            if (beforeReschedule!=registrations()) throw new AssertionError("reschedule-attempted-admission");
            int accepted=0;
            for (int i=0;i<2;i++) {
                try { timer.schedule(new TimerTask() { @Override public void run() { unexpected.incrementAndGet(); } }, 180_000); accepted++; }
                catch (IllegalStateException capacity) { break; }
            }
            timer.cancel(); int afterCancel=queued();
            if (!rescheduleRefused || unexpected.get()!=0) throw new AssertionError("cancelled-task-behavior");
            System.out.println("capacity:"+(purge?"purge":"automatic")+":before="+beforeRelease+":witness="+atWitness
                +":removed="+displayRemoved(removed,5)+":afterPurge="+afterPurge+":accepted="+accepted+":afterCancel="+afterCancel
                +":reschedule=refused:unexpected="+unexpected.get());
        } finally { gateRelease.countDown(); timer.cancel(); witnessRelease.countDown(); }
        retire();
    }
    private static void active(boolean purge) throws Exception {
        Timer timer = new Timer("active-cancel", true);
        CountDownLatch activeEntered=new CountDownLatch(1), activeRelease=new CountDownLatch(1);
        CountDownLatch witnessEntered=new CountDownLatch(1), witnessRelease=new CountDownLatch(1);
        AtomicInteger callbacks=new AtomicInteger();
        TimerTask recurring=new TimerTask() { @Override public void run() {
            callbacks.incrementAndGet(); activeEntered.countDown(); await(activeRelease,"active-release");
        }};
        try {
            timer.scheduleAtFixedRate(recurring,0,60_000);
            await(activeEntered,"active-enter");
            if (!recurring.cancel()) throw new AssertionError("active-cancel-refused");
            timer.schedule(new TimerTask() { @Override public void run() { witnessEntered.countDown(); await(witnessRelease,"witness-release"); } },0);
            int before=queued(), removed=purge ? timer.purge() : -1, afterPurge=queued();
            if (purge && timer.purge()!=0) throw new AssertionError("active-entry-not-purged");
            activeRelease.countDown(); await(witnessEntered,"active-witness-enter");
            int atWitness=queued();
            int beforeReschedule=registrations();
            boolean rescheduleRefused=false;
            try { timer.schedule(recurring,180_000); } catch (IllegalStateException expected) { rescheduleRefused=true; }
            if (beforeReschedule!=registrations()) throw new AssertionError("active-reschedule-attempted-admission");
            timer.cancel(); int afterCancel=queued();
            if (!rescheduleRefused || callbacks.get()!=1) throw new AssertionError("active-task-behavior");
            System.out.println("active:"+(purge?"purge":"automatic")+":before="+before+":removed="+displayRemoved(removed,1)
                +":afterPurge="+afterPurge+":witness="+atWitness+":afterCancel="+afterCancel
                +":reschedule=refused:callbacks="+callbacks.get());
        } finally { activeRelease.countDown(); timer.cancel(); witnessRelease.countDown(); }
        retire();
    }
    private static void selfCancel() throws Exception {
        Timer timer = new Timer("self-cancel-reentry", true) {
            @Override public int purge() { throw new AssertionError("public-purge-dispatched"); }
        };
        CountDownLatch activeEntered=new CountDownLatch(1), activeRelease=new CountDownLatch(1);
        CountDownLatch witnessEntered=new CountDownLatch(1), witnessRelease=new CountDownLatch(1);
        AtomicInteger callbacks=new AtomicInteger();
        AtomicInteger witnessCalls=new AtomicInteger();
        TimerTask recurring=new TimerTask() { @Override public void run() {
            callbacks.incrementAndGet();
            if (!cancel()) throw new AssertionError("self-cancel-refused");
            timer.schedule(new TimerTask() { @Override public void run() {
                witnessCalls.incrementAndGet(); witnessEntered.countDown(); await(witnessRelease,"self-witness-release");
            }},0);
            activeEntered.countDown(); await(activeRelease,"self-active-release");
        }};
        try {
            timer.scheduleAtFixedRate(recurring,0,60_000);
            await(activeEntered,"self-active-enter"); int before=queued();
            activeRelease.countDown(); await(witnessEntered,"self-witness-enter"); int atWitness=queued();
            int beforeReschedule=registrations();
            boolean refused=false;
            try { timer.schedule(recurring,180_000); } catch (IllegalStateException expected) { refused=true; }
            if (beforeReschedule!=registrations()) throw new AssertionError("self-reschedule-attempted-admission");
            timer.cancel(); int afterCancel=queued();
            if (!refused || callbacks.get()!=1 || witnessCalls.get()!=1) throw new AssertionError("self-cancel-result");
            System.out.println("self:before="+before+":witness="+atWitness+":afterCancel="+afterCancel
                +":reschedule=refused:callbacks="+callbacks.get()+":witnessCalls="+witnessCalls.get());
        } finally { activeRelease.countDown(); timer.cancel(); witnessRelease.countDown(); }
        retire();
    }
    public static void main(String[] args) throws Exception {
        sourcePort = args.length == 1 && args[0].equals("source");
        if (sourcePort) ledger().getMethod("setQueuedLimit", int.class).invoke(null, 8);
        capacity(false); capacity(true); active(false); active(true); selfCancel();
        cleanup();
    }
}
