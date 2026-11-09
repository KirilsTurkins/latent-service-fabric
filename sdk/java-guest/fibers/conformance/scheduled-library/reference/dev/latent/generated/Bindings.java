package dev.latent.generated;

/** Compile-only JDK reference declarations; the reference never runs modes 8 and 9. */
public final class Bindings {
    public static final class LatentRuntimeActivation {
        public static ObservationResult observe() { throw new AssertionError("guest-only timer probe"); }
    }
    public static final class ObservationResult {
        public boolean isError() { throw new AssertionError("guest-only timer probe"); }
        public Observation value() { throw new AssertionError("guest-only timer probe"); }
    }
    public static final class Observation {
        public Long timers() { throw new AssertionError("guest-only timer probe"); }
        public Long waits() { throw new AssertionError("guest-only timer probe"); }
        public Count admissionFailures() { throw new AssertionError("guest-only timer probe"); }
    }
    public static final class Count {
        public long bits() { throw new AssertionError("guest-only timer probe"); }
    }
}
