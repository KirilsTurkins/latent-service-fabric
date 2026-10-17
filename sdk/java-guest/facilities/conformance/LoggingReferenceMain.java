package dev.latent.app;

import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;

public final class LoggingReferenceMain {
    public static void main(String[] args) throws Exception {
        int mode = Integer.parseInt(args[0]);
        var originalOut = System.out;
        var originalErr = System.err;
        var capturedOut = new ByteArrayOutputStream();
        var capturedErr = new ByteArrayOutputStream();
        try {
            System.setOut(new PrintStream(capturedOut, false, StandardCharsets.UTF_8));
            System.setErr(new PrintStream(capturedErr, false, StandardCharsets.UTF_8));
            long result = new Capsule().run((long)mode, "", dev.latent.guest.Unsigned64.ZERO).bits();
            String expected = switch (mode) {
                case 0 -> "plain caf\u00e9 \ud83c\udf0d";
                case 1 -> "failure" + System.lineSeparator();
                case 2 -> "42:ok";
                case 6 -> "A".repeat(256);
                default -> throw new AssertionError("unsupported-reference-mode");
            };
            String actual = (mode == 1 ? capturedErr : capturedOut).toString(StandardCharsets.UTF_8);
            if (result != 42 || !actual.equals(expected)
                    || (mode == 1 ? capturedOut : capturedErr).size() != 0)
                throw new AssertionError("ordinary-jdk-console-observable");
        } finally { System.setOut(originalOut); System.setErr(originalErr); }
        System.out.println("LOGGING_REFERENCE PASS mode=" + mode);
    }
}
