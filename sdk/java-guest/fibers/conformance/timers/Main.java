public final class Main {
    public static void main(String[] args) throws Exception {
        TimerValidationOrder.check();
        try {
            for (long mode = 0; mode < 4; mode++) {
                if (mode == 3) {
                    // The guest runs every mode in a fresh activation. Drain
                    // earlier reference-process timers before comparing owners.
                    long until = System.nanoTime() + 5_000_000_000L;
                    while (!dev.latent.app.Capsule.lateCallback) {
                        if (System.nanoTime() - until > 0) throw new AssertionError("reference-late-timer");
                        Thread.sleep(1);
                    }
                    for (var timer : dev.latent.app.Capsule.referenceTimers) timer.cancel();
                    dev.latent.generated.Bindings.awaitReferenceQuiescence();
                }
                long value = new dev.latent.app.Capsule().run(mode);
                if (value != 42) throw new AssertionError(value);
            }
            dev.latent.generated.Bindings.verifyReference();
            long began = System.nanoTime();
            while (!dev.latent.app.Capsule.lateCallback || !dev.latent.app.Capsule.cancelledCallbackFinished) {
                if (System.nanoTime() - began > 5_000_000_000L) throw new AssertionError("accepted-timer-not-drained");
                Thread.sleep(1);
            }
            System.out.println("42 42 42 42");
        } finally {
            for (var timer : dev.latent.app.Capsule.referenceTimers) timer.cancel();
        }
    }
}
