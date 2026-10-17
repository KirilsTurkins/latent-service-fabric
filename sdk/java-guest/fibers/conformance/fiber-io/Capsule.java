package dev.latent.app;

import dev.latent.generated.Bindings;
import dev.latent.guest.Option;
import dev.latent.guest.Unsigned64;
import java.util.ArrayList;

/** ABI conformance, separately from ordinary default HTTP client qualification. */
public final class Capsule {
    private static final Object gate = new Object();
    private static final ThreadLocal<String> local = new ThreadLocal<>();
    private static final ArrayList<Thread> referenceThreads = new ArrayList<>();
    private static volatile int started, progress, done;
    private static volatile Throwable failure;
    public static volatile boolean late;
    private static void require(boolean value) {
        if (!value) throw new IllegalStateException("fiber-host-io-observable");
    }
    private static void hostWait(long millis) {
        var waited = Bindings.LatentRuntimeActivation.waitFor(new Unsigned64(millis * 1_000_000), Option.none());
        require(!waited.isError());
    }
    private static Thread worker(Runnable action) {
        Thread thread = new Thread(() -> {
            try { action.run(); }
            catch (Throwable error) { failure = error; throw error; }
            finally { synchronized (gate) { gate.notifyAll(); } }
        });
        referenceThreads.add(thread);
        thread.start();
        return thread;
    }
    private static void started(int expected) {
        while (started != expected) {
            if (failure != null) throw new IllegalStateException("host-worker-failed", failure);
            Thread.yield();
        }
    }
    private static void completed(int expected) {
        synchronized (gate) {
            while (done != expected && failure == null) {
                try { gate.wait(); } catch (InterruptedException error) { throw new IllegalStateException(error); }
            }
        }
        if (failure != null) throw new IllegalStateException("host-worker-failed", failure);
    }
    public Long run(Long mode) {
        started = progress = done = 0;
        failure = null;
        if (mode == 0) {
            local.set("root");
            worker(() -> {
                require(local.get() == null); local.set("child");
                started = 1; hostWait(250);
                require(progress > 0 && "child".equals(local.get()));
                done = 1;
            });
            started(1);
            require(done == 0);
            progress = 42;
            completed(1);
            require("root".equals(local.get()));
        } else if (mode == 1) {
            worker(() -> { synchronized (gate) { started++; } hostWait(100); synchronized (gate) { done++; } });
            worker(() -> { synchronized (gate) { started++; } hostWait(200); synchronized (gate) { done++; } });
            completed(2);
        } else if (mode == 2) {
            worker(() -> { started = 1; hostWait(100); late = true; done = 1; });
            started(1);
            return 42L;
        } else if (mode == 3) {
            Thread root = Thread.currentThread();
            worker(() -> { started = 1; hostWait(100); root.interrupt(); done = 1; });
            started(1);
            boolean interrupted = false;
            try { Thread.sleep(500); } catch (InterruptedException expected) { interrupted = true; }
            require(interrupted);
            completed(1);
        } else throw new IllegalArgumentException();
        return 42L;
    }
    public static void referenceCleanup() throws InterruptedException {
        for (Thread thread : referenceThreads) {
            thread.join(5000);
            require(!thread.isAlive());
        }
        referenceThreads.clear();
    }
}
