package dev.latent.app;
import dev.latent.generated.Bindings;
import dev.latent.generated.Bindings.*;
import dev.latent.guest.*;

public final class Capsule implements Bindings.Exports {
    public Unsigned64 run(Long which, String text, Unsigned64 handle) {
        if (which == 0) {
            try (var entropy = new SensitiveBytes(LatentRandomRandom.bytes(32L).value())) { return new Unsigned64(entropy.borrow().length); }
        }
        if (which == 1) { LatentRandomRandom.u64Value().value(); return new Unsigned64(8); }
        if (which == 2) {
            var result = LatentRandomRandom.bytes(0xffff_ffffL);
            if (result.isError() && result.error().tag() == 0) return new Unsigned64(10);
        }
        if (which >= 3 && which <= 8) return new Unsigned64(OutsideEntropyOwner.run(which.intValue()));
        throw new IllegalStateException("unexpected random result");
    }
}

/** Ordinary application helper; no LSF imports or cleanup calls. */
final class OutsideEntropyOwner {
    private static int calls;
    static int run(int mode) {
        if (++calls != 1) throw new AssertionError("entropy-static-state-leaked");
        var random = new java.security.SecureRandom();
        if (mode == 3) {
            byte[] bytes = new byte[32];
            random.nextBytes(bytes);
            java.util.Arrays.fill(bytes, (byte)0);
            return 32;
        }
        if (mode == 4) {
            byte[] bytes = java.security.SecureRandom.getSeed(32);
            int length = bytes.length;
            java.util.Arrays.fill(bytes, (byte)0);
            return length;
        }
        if (mode == 5) {
            random.nextBytes(new byte[0]);
            if (random.generateSeed(0).length != 0) throw new AssertionError("entropy-empty");
            try { random.nextBytes(null); throw new AssertionError("entropy-null"); }
            catch (NullPointerException expected) { }
            try { random.generateSeed(-1); throw new AssertionError("entropy-negative"); }
            catch (IllegalArgumentException expected) { }
            try { random.generateSeed(4097); throw new AssertionError("entropy-size"); }
            catch (java.security.ProviderException expected) { }
            try { random.setSeed(new byte[]{1}); throw new AssertionError("entropy-seed"); }
            catch (UnsupportedOperationException expected) { }
            try { random.setSeed(1L); throw new AssertionError("entropy-long-seed"); }
            catch (UnsupportedOperationException expected) { }
            try { random.reseed(); throw new AssertionError("entropy-reseed"); }
            catch (UnsupportedOperationException expected) { }
            try { java.security.SecureRandom.getInstance("NativePRNG"); throw new AssertionError("entropy-provider"); }
            catch (java.security.NoSuchAlgorithmException expected) { }
            return 42;
        }
        if (mode == 6) {
            random.nextInt(); random.nextLong(); random.nextBoolean();
            float small = random.nextFloat(); double large = random.nextDouble();
            if (!(small >= 0 && small < 1) || !(large >= 0 && large < 1))
                throw new AssertionError("entropy-range");
            return 42;
        }
        byte[] bytes = new byte[mode == 7 ? 32 : 8];
        java.util.Arrays.fill(bytes, (byte)73);
        if (mode == 8) {
            byte[] first = random.generateSeed(8);
            java.util.Arrays.fill(first, (byte)0);
        }
        try { random.nextBytes(bytes); throw new AssertionError("entropy-provider-failure-ignored"); }
        catch (java.security.ProviderException expected) {
            String code = mode == 7 ? "bounded-entropy-invalid-length" : "bounded-entropy-budget-exhausted";
            if (!code.equals(expected.getMessage())) throw new AssertionError("entropy-error-mapping");
            for (byte value : bytes) if (value != 73) throw new AssertionError("entropy-failed-write");
        }
        return 42;
    }
}
