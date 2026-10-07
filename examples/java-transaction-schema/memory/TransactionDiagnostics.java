package dev.latent.app;

/** Opt-in failure controls after the original state write and captured intent. */
public final class TransactionDiagnostics {
    public static final long TRAP_DELTA = 0xffff_fffdL;
    public static final long LOOP_DELTA = 0xffff_fffeL;
    public static final long MEMORY_DELTA = 0xffff_fffcL;
    private static int invocations;
    private static volatile long iterations;
    private static volatile byte[] allocated;

    private TransactionDiagnostics() {}

    public static void enter() {
        if (++invocations != 1) throw new IllegalStateException("diagnostic-instance-reused");
    }

    public static long businessDelta(long requested) {
        return requested == TRAP_DELTA || requested == LOOP_DELTA || requested == MEMORY_DELTA ? 1L : requested;
    }

    public static void afterStage(long requested) {
        if (requested == TRAP_DELTA) throw new IllegalStateException("diagnostic-trap-after-stage");
        if (requested == LOOP_DELTA) {
            while (true) iterations++;
        }
        if (requested == MEMORY_DELTA) {
            // The existing 64 MiB guest ceiling is unchanged. Retaining and
            // touching the allocation prevents dead-code elimination; only
            // an actual signed runtime attempt can qualify the failure.
            allocated = new byte[80 * 1024 * 1024];
            allocated[allocated.length - 1] = 1;
        }
    }
}
