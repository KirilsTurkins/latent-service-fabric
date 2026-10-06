public final class Main {
    public static void main(String[] args) {
        for (long mode = 0; mode < 4; mode++) {
            long value = new dev.latent.app.Capsule().run(mode);
            if (value != 42) throw new AssertionError(value);
        }
        long deadline = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(5);
        while (!dev.latent.app.Capsule.lateFlush) {
            if (System.nanoTime() >= deadline) throw new AssertionError("accepted flush did not complete");
            Thread.onSpinWait();
        }
        // Reference harness owns process termination. Capsule source stays byte
        // identical and contains no activation-specific executor/shutdown glue.
        for (var pool : dev.latent.app.Capsule.referencePools) pool.close();
        System.out.println("42 42 42 42");
    }
}
