package dev.latent.guest;

import org.teavm.interop.Function;

/** Declare native roots using TeaVM's supported function-pointer mechanism.
 * Export supplies a C symbol name, not an optimizer reachability root. */
public final class NativeEntrypoints {
    private NativeEntrypoints() { }

    public abstract static class Identity extends Function {
        public abstract long apply(long value);
    }

    public abstract static class Smoke extends Function {
        public abstract int apply();
    }

    public static void main(String[] args) {
        Function.get(Identity.class, Probe.class, "identity");
        Function.get(Smoke.class, Probe.class, "smoke");
    }
}
