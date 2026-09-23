package dev.latent.guest;

import java.nio.charset.StandardCharsets;
import org.teavm.interop.Export;

/** Compiler probe, not a guest SDK or a deployment qualification. */
public final class Probe {
    private Probe() { }

    @Export(name = "lsf_java_identity")
    public static long identity(long value) {
        return value;
    }

    @Export(name = "lsf_java_smoke")
    public static int smoke() {
        if (identity(Long.MIN_VALUE) != Long.MIN_VALUE
                || identity(Long.MAX_VALUE) != Long.MAX_VALUE) {
            throw new AssertionError("full-width integer changed");
        }
        String text = "Grüße 🌍\u0000Java";
        if (!text.equals(new String(text.getBytes(StandardCharsets.UTF_8), StandardCharsets.UTF_8))) {
            throw new AssertionError("UTF-8 round trip changed");
        }
        boolean caught = false;
        try {
            throw new IllegalArgumentException("Java exception is not a declared WIT error");
        } catch (IllegalArgumentException expected) {
            caught = true;
        }
        if (!caught) throw new AssertionError("exception was lost");
        long total = 0;
        // More allocations than the configured guest heap: exercise collection,
        // rather than accidentally testing an allocation-free trivial program.
        for (int i = 0; i < 8192; ++i) {
            byte[] data = new byte[1024];
            data[0] = (byte) i;
            total += data[0];
        }
        if (total != -4096) throw new AssertionError("allocation result changed");
        return 4;
    }

    public static void main(String[] args) {
        if (smoke() != 4) throw new AssertionError("compiler smoke failed");
    }
}
