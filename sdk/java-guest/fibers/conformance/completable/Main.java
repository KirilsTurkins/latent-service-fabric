public final class Main {
    public static void main(String[] args) {
        for (long mode = 0; mode < 4; mode++) {
            long value = new dev.latent.app.Capsule().run(mode);
            if (value != 42) throw new AssertionError(value);
        }
        long deadline = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(5);
        while (!dev.latent.app.Capsule.lateFlush) {
            if (System.nanoTime() >= deadline) throw new AssertionError("accepted CompletableFuture did not complete");
            Thread.onSpinWait();
        }
        System.out.println("42 42 42 42");
    }
}
