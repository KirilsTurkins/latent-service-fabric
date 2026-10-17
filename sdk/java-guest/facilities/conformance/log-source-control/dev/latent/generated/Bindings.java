package dev.latent.generated;

/** Host-only log fault provider; never included in application source staging. */
public final class Bindings {
    public static int calls;
    public static int error = -1;
    public static boolean accepted = true;
    public static String message;
    public static LatentLogLogLevel level;
    public enum LatentLogLogLevel { Trace, Debug, Info, Warn, Error }
    public record Error(int tag) { }
    public record Result(boolean value, Error error) {
        public boolean isError() { return error != null; }
    }
    public static final class LatentLogLog {
        public static Result write(LatentLogLogLevel selected, String text, java.util.List<?> fields) {
            if (!fields.isEmpty()) throw new AssertionError("unexpected-fields");
            calls++; level = selected; message = text;
            return new Result(accepted, error < 0 ? null : new Error(error));
        }
    }
}
