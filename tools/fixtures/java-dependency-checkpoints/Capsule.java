package dev.latent.app;

import dev.latent.guest.Result;
import org.apache.commons.lang3.concurrent.AtomicSafeInitializer;
import org.apache.commons.lang3.concurrent.ConcurrentException;

/** Ordinary callers; the contended spin loop is inside the unchanged Maven JAR. */
public final class Capsule {
    private static int invocation;
    private static final ThreadLocal<String> local = new ThreadLocal<>();
    private static volatile boolean started;
    private static volatile boolean readerReady;
    private static volatile boolean childReturned;
    private static volatile boolean childGuarded;
    private static volatile Throwable childFailure;
    private static int initializations;
    private static int rootPhase;
    private static volatile int childPhase;

    private static final class Held {
        final int[] values;
        final Throwable error;
        Held(int[] values, Throwable error) { this.values = values; this.error = error; }
    }

    private static void require(boolean value) {
        if (!value) throw new IllegalStateException("dependency-checkpoint-observable");
    }

    private static String errorKind(Throwable error) {
        if (error == null) return "none";
        if (error instanceof IllegalMonitorStateException) return "monitor-state";
        if (error instanceof IllegalStateException)
            return "dependency-checkpoint-observable".equals(error.getMessage()) ? "fixture-assertion" : "state";
        if (error instanceof NullPointerException) return "null";
        if (error instanceof ConcurrentException) return "initializer";
        return "other";
    }

    public Result<String, String> greet(String mode) {
        try { return checked(mode); }
        catch (Throwable error) {
            // A diagnostic remains a failing Result; the signed controller still
            // requires each unchanged exact ok value and original budgets.
            return Result.err("checkpoint-failure|root=" + rootPhase + "|error=" + errorKind(error)
                + "|child=" + childPhase + "|child-error=" + errorKind(childFailure));
        }
    }

    private Result<String, String> checked(String mode) {
        rootPhase = 1;
        require(++invocation == 1 && !started && !readerReady && local.get() == null);
        if (mode.equals("fresh")) return Result.ok("checkpoint|fresh=1");
        require(mode.equals("dependency") || mode.equals("monitor"));
        Object rendezvous = new Object();
        Object guard = new Object();
        int[] retained = {19, 23};
        local.set("root");
        AtomicSafeInitializer<Held> initializer = new AtomicSafeInitializer<>() {
            @Override protected Held initialize() {
                childPhase = 2;
                require(local.get() == null);
                local.set("child");
                initializations++;
                Throwable retainedError;
                try { throw new IllegalArgumentException("retained-child-error"); }
                catch (IllegalArgumentException error) { retainedError = error; }
                int[] values = {20, 22};
                childPhase = 3;
                synchronized (rendezvous) { started = true; rendezvous.notifyAll(); }
                // This application loop lets the original root enter get().
                // The root then needs a checkpoint INSIDE the dependency loop.
                childPhase = 4;
                while (!readerReady) { }
                childPhase = 5;
                require(local.get().equals("child") && values[0] + values[1] == 42);
                return new Held(values, retainedError);
            }
        };
        Thread child = new Thread(() -> {
            try {
                childPhase = 1;
                Held value = initializer.get();
                childPhase = 6;
                require(value.values[0] + value.values[1] == 42 && local.get().equals("child"));
                childReturned = true;
                childPhase = 7;
                synchronized (guard) { childGuarded = true; }
                childPhase = 8;
            } catch (Throwable error) { childFailure = error; }
        });
        require(!child.isAlive());
        rootPhase = 2;
        child.start();
        try {
            rootPhase = 3;
            synchronized (rendezvous) { while (!started) rendezvous.wait(); }
            rootPhase = 4;
            Held value;
            if (mode.equals("monitor")) {
                synchronized (guard) {
                    rootPhase = 5;
                    readerReady = true;
                    value = initializer.get();
                    rootPhase = 6;
                    while (!childReturned) { }
                    rootPhase = 7;
                    require(!childGuarded);
                    // The dependency checkpoint must preserve this monitor,
                    // including its reentrant ownership and later release.
                    rootPhase = 8;
                    synchronized (guard) { guard.notifyAll(); }
                    rootPhase = 9;
                }
            } else {
                readerReady = true;
                value = initializer.get();
            }
            rootPhase = 10;
            child.join();
            rootPhase = 11;
            require(!child.isAlive() && childReturned && childGuarded && childFailure == null);
            rootPhase = 12;
            require(initializations == 1 && value == initializer.get());
            require(value.values[0] + value.values[1] == 42 && retained[0] + retained[1] == 42);
            rootPhase = 13;
            require(value.error instanceof IllegalArgumentException
                && value.error.getMessage().equals("retained-child-error") && local.get().equals("root"));
            return Result.ok("checkpoint|" + mode + "=42|initializations=1|locals=root:child|error=retained|fresh=1");
        } catch (InterruptedException | ConcurrentException error) { throw new IllegalStateException(error); }
    }
}
