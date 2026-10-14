package dev.latent.app;

import java.nio.ByteBuffer;
import java.util.ArrayList;

/** Controls confined to the explicit diagnostic capsule, after real staging. */
public final class TransactionDiagnostics {
    public static final long MEMORY_DELTA = 0xffff_fffcL;
    public static final long TRAP_DELTA = 0xffff_fffdL;
    public static final long LOOP_DELTA = 0xffff_fffeL;
    private static int invocations;
    private static volatile long iterations;
    private static volatile ArrayList<ByteBuffer> retainedMemory;

    private TransactionDiagnostics() {}

    public static void enter() {
        if (++invocations != 1) throw new IllegalStateException("diagnostic-instance-reused");
    }

    public static long businessDelta(long requested) {
        return requested == MEMORY_DELTA || requested == TRAP_DELTA || requested == LOOP_DELTA ? 1L : requested;
    }

    public static void afterStage(long requested) {
        if (requested == MEMORY_DELTA) {
            // Direct buffers use the pinned C backend's native allocator.
            // Retain their handles so the separate 4 MiB Java heap does not
            // become the tested limit or permit collection of earlier slabs.
            retainedMemory = new ArrayList<ByteBuffer>();
            for (int index = 0; index < 1025; index++) {
                var slab = ByteBuffer.allocateDirect(65536);
                slab.put(0, (byte) 1);
                retainedMemory.add(slab);
                iterations = retainedMemory.size();
            }
            throw new IllegalStateException("diagnostic-native-memory-refusal-missing");
        }
        if (requested == TRAP_DELTA) throw new IllegalStateException("diagnostic-trap-after-stage");
        if (requested == LOOP_DELTA) {
            while (true) iterations++;
        }
    }
}
