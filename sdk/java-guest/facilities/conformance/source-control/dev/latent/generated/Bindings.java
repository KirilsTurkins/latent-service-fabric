package dev.latent.generated;

/** Host source-control provider only; never copied into the guest. */
public final class Bindings {
    public static int calls;
    public static int error = -1;
    public static boolean wrongLength;
    public static byte[] last;
    public record Error(int tag) { }
    public record Result(byte[] value, Error error) {
        public boolean isError() { return error != null; }
    }
    public static final class LatentRandomRandom {
        public static Result bytes(long count) {
            calls++;
            if (error >= 0) return new Result(null, new Error(error));
            last = new byte[(int)count + (wrongLength ? 1 : 0)];
            java.util.Arrays.fill(last, (byte)0xa7);
            return new Result(last, null);
        }
    }
}
