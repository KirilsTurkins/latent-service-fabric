package dev.latent.app;

public final class EntropyReferenceMain {
    public static void main(String[] args) {
        int mode = Integer.parseInt(args[0]);
        long expected = mode == 6 ? 42 : 32;
        long result = OutsideEntropyOwner.run(mode);
        if (result != expected) throw new AssertionError("reference-entropy-observable");
        System.out.println("ENTROPY_REFERENCE PASS mode=" + mode + " result=" + result);
    }
}
