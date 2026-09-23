package dev.latent.probe;

import org.teavm.interop.Export;
import org.teavm.jso.JSExport;

/** Actual Java source; not a handwritten C replacement or a guest SDK claim. */
public final class Probe {
    private Probe() { }

    @Export(name = "java_probe")
    @JSExport
    public static long exercise(long seed) {
        long[] owned = new long[] {seed, Long.MIN_VALUE, Long.MAX_VALUE};
        String text = new String(new char[] {'\u03bb', '\uD83D', '\uDE80', '\u0000'});
        if (text.codePointCount(0, text.length()) != 3) {
            throw new IllegalStateException("Unicode changed");
        }
        try {
            if (seed < 0) {
                throw new IllegalArgumentException("declared Java exception probe");
            }
            return owned[0] ^ owned[1] ^ owned[2];
        } catch (IllegalArgumentException expected) {
            return seed;
        }
    }

    public static void main(String[] args) {
        if (exercise(Long.MAX_VALUE) != Long.MIN_VALUE
                || exercise(Long.MIN_VALUE) != Long.MIN_VALUE
                || exercise(0) != -1L) {
            throw new AssertionError("Java semantic probe failed");
        }
    }
}
