package dev.latent.app;

import dev.latent.generated.Bindings;
import dev.latent.guest.Unsigned64;

public final class Capsule implements Bindings.Exports {
    public Unsigned64 run(Long which, String text, Unsigned64 handle) {
        return new Unsigned64(OutsideStandardLogging.run(which.intValue()));
    }
}

/** Ordinary standard output use; no LSF imports, custom logger or cleanup. */
final class OutsideStandardLogging {
    private static int calls;
    static int run(int mode) {
        if (++calls != 1 || System.out.checkError() || System.err.checkError())
            throw new AssertionError("standard-log-state-leaked");
        if (System.out != System.out || System.err != System.err || System.out == System.err)
            throw new AssertionError("standard-stream-identity");
        if (mode == 0) System.out.print("plain caf\u00e9 \ud83c\udf0d");
        else if (mode == 1) System.err.println("failure");
        else if (mode == 2) { System.out.print(42); System.out.append(':').append("ok"); }
        else if (mode == 3) System.out.write(new byte[]{(byte)0xc0,(byte)0x80}, 0, 2);
        else if (mode == 4 || mode == 5) System.out.print("refused");
        else if (mode == 6) {
            byte[] bytes = new byte[256]; java.util.Arrays.fill(bytes, (byte)65);
            System.out.write(bytes, 0, bytes.length);
        } else if (mode == 7) {
            byte[] bytes = new byte[257]; java.util.Arrays.fill(bytes, (byte)65);
            System.out.write(bytes, 0, bytes.length);
        } else throw new IllegalArgumentException("unknown-log-mode");
        System.out.flush(); System.err.flush();
        boolean failure = mode == 3 || mode == 4 || mode == 5 || mode == 7;
        if (System.out.checkError() != failure || System.err.checkError())
            throw new AssertionError("standard-log-error-policy");
        return 42;
    }
}
