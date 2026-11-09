package dev.latent.generated;

/** Source-control types only; the actual guest uses generated WIT bindings. */
public final class Bindings {
    public enum LatentRuntimeActivationOwnerKind { Executor, QueuedWork }
    // Private source-model snapshot; the real component uses generated WIT.
    private static int observed;
    public static final class LatentRuntimeActivation {
        public static synchronized ObservationResult observe() { observed++; return new ObservationResult(); }
    }
    public static void awaitReferenceQuiescence() throws InterruptedException {
        long until = System.nanoTime() + 5_000_000_000L;
        while (dev.latent.guest.runtime.Activation.queued() != 0
                || dev.latent.guest.runtime.Activation.executors() != 0) {
            if (System.nanoTime() - until > 0) throw new AssertionError("source-owners-not-drained");
            Thread.sleep(1);
        }
    }
    public static synchronized void verifyReference() {
        if (observed != 6) throw new AssertionError("missing-source-observation");
    }
    public static final class ObservationResult {
        public boolean isError() { return false; }
        public Observation value() { return new Observation(); }
    }
    public static final class Observation {
        public Long queuedWork() { return (long)dev.latent.guest.runtime.Activation.queued(); }
        public Long executors() { return (long)dev.latent.guest.runtime.Activation.executors(); }
    }
}
