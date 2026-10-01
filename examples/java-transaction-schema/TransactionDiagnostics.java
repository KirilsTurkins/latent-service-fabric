package dev.latent.app;

/** Controls confined to the explicit diagnostic capsule, after real staging. */
public final class TransactionDiagnostics {
    public static final long TRAP_DELTA = 0xffff_fffdL;
    public static final long LOOP_DELTA = 0xffff_fffeL;
    private static int invocations;
    private static volatile long iterations;

    private TransactionDiagnostics() {}

    public static void enter() {
        if (++invocations != 1) throw new IllegalStateException("diagnostic-instance-reused");
    }

    public static long businessDelta(long requested) {
        return requested == TRAP_DELTA || requested == LOOP_DELTA ? 1L : requested;
    }

    public static void afterStage(long requested) {
        if (requested == TRAP_DELTA) throw new IllegalStateException("diagnostic-trap-after-stage");
        if (requested == LOOP_DELTA) {
            while (true) iterations++;
        }
    }
}
