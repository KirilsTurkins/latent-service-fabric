public final class Main {
    public static void main(String[] args) throws Exception {
        try {
            for (long mode = 0; mode < 4; mode++) {
                long value = new dev.latent.app.Capsule().run(mode);
                if (value != 42) throw new AssertionError(value);
            }
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
