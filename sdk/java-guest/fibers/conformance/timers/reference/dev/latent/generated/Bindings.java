package dev.latent.generated;

/** JDK-only scripted observations; these are not host resource evidence. */
public final class Bindings {
    private static final long[][] SCRIPT = {{0, 0}, {2, 1}, {2, 1}, {1, 1}, {1, 1}, {0, 0}};
    private static int next;
    public static final class LatentRuntimeActivation {
        public static ObservationResult observe() {
            if (next >= SCRIPT.length) throw new AssertionError("extra-reference-observation");
            return new ObservationResult(next++);
        }
    }
    public static final class ObservationResult {
        private final int index;
        ObservationResult(int index) { this.index = index; }
        public boolean isError() { return false; }
        public Observation value() { return new Observation(index); }
    }
    public static final class Observation {
        private final int index;
        Observation(int index) { this.index = index; }
        public Long queuedWork() { return SCRIPT[index][0]; }
        public Long executors() { return SCRIPT[index][1]; }
    }
    public static void awaitReferenceQuiescence() { }
    public static void verifyReference() {
        if (next != SCRIPT.length) throw new AssertionError("missing-reference-observation");
    }
}
