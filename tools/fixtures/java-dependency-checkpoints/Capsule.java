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

    private static final class Held {
        final int[] values;
        final Throwable error;
        Held(int[] values, Throwable error) { this.values = values; this.error = error; }
    }

    private static void require(boolean value) {
        if (!value) throw new IllegalStateException("dependency-checkpoint-observable");
    }

    public Result<String, String> greet(String mode) {
        require(++invocation == 1 && !started && !readerReady && local.get() == null);
        if (mode.equals("fresh")) return Result.ok("checkpoint|fresh=1");
        require(mode.equals("dependency") || mode.equals("monitor"));
        Object rendezvous = new Object();
        Object guard = new Object();
        int[] retained = {19, 23};
        local.set("root");
        AtomicSafeInitializer<Held> initializer = new AtomicSafeInitializer<>() {
            @Override protected Held initialize() {
                require(local.get() == null);
                local.set("child");
                initializations++;
                Throwable retainedError;
                try { throw new IllegalArgumentException("retained-child-error"); }
                catch (IllegalArgumentException error) { retainedError = error; }
                int[] values = {20, 22};
                synchronized (rendezvous) { started = true; rendezvous.notifyAll(); }
                // This application loop lets the original root enter get().
                // The root then needs a checkpoint INSIDE the dependency loop.
                while (!readerReady) { }
                require(local.get().equals("child") && values[0] + values[1] == 42);
                return new Held(values, retainedError);
            }
        };
        Thread child = new Thread(() -> {
            try {
                Held value = initializer.get();
                require(value.values[0] + value.values[1] == 42 && local.get().equals("child"));
                childReturned = true;
                synchronized (guard) { childGuarded = true; }
            } catch (Throwable error) { childFailure = error; }
        });
        require(!child.isAlive());
        child.start();
        try {
            synchronized (rendezvous) { while (!started) rendezvous.wait(); }
            Held value;
            if (mode.equals("monitor")) {
                synchronized (guard) {
                    readerReady = true;
                    value = initializer.get();
                    while (!childReturned) { }
                    require(!childGuarded);
                    // The dependency checkpoint must preserve this monitor,
                    // including its reentrant ownership and later release.
                    synchronized (guard) { guard.notifyAll(); }
                }
            } else {
                readerReady = true;
                value = initializer.get();
            }
            child.join();
            require(!child.isAlive() && childReturned && childGuarded && childFailure == null);
            require(initializations == 1 && value == initializer.get());
            require(value.values[0] + value.values[1] == 42 && retained[0] + retained[1] == 42);
            require(value.error instanceof IllegalArgumentException
                && value.error.getMessage().equals("retained-child-error") && local.get().equals("root"));
            return Result.ok("checkpoint|" + mode + "=42|initializations=1|locals=root:child|error=retained|fresh=1");
        } catch (InterruptedException | ConcurrentException error) { throw new IllegalStateException(error); }
    }
}
