package dev.latent.guest.facilities;

import java.security.NoSuchAlgorithmException;
import java.util.Random;

/** Method template installed on the pinned standard SecureRandom identity. */
public class EntropyRandom extends Random {
    public EntropyRandom() { super(0L); }
    public EntropyRandom(byte[] seed) {
        super(0L);
        java.util.Objects.requireNonNull(seed);
        throw new UnsupportedOperationException("bounded-entropy-caller-seeding-unsupported");
    }
    public static EntropyRandom getInstance(String algorithm) throws NoSuchAlgorithmException {
        java.util.Objects.requireNonNull(algorithm);
        if (!algorithm.equals("LSF-BoundedEntropy")) throw new NoSuchAlgorithmException(algorithm);
        return new EntropyRandom();
    }
    public String getAlgorithm() { return "LSF-BoundedEntropy"; }
    public void setSeed(byte[] seed) {
        java.util.Objects.requireNonNull(seed);
        throw new UnsupportedOperationException("bounded-entropy-caller-seeding-unsupported");
    }
    @Override public void setSeed(long seed) {
        // Random's constructor calls this virtual method with zero. SecureRandom
        // also specifies that a long seed of zero has no effect.
        if (seed != 0) throw new UnsupportedOperationException("bounded-entropy-caller-seeding-unsupported");
    }
    public void reseed() {
        throw new UnsupportedOperationException("bounded-entropy-reseeding-unsupported");
    }
    @Override protected final int next(int bits) {
        if (bits < 0 || bits > 32) throw new IllegalArgumentException("random-bit-count");
        if (bits == 0) return 0;
        byte[] bytes = new byte[(bits + 7) / 8];
        nextBytes(bytes);
        int value = 0;
        for (byte item : bytes) value = (value << 8) | (item & 255);
        java.util.Arrays.fill(bytes, (byte)0);
        return value >>> (bytes.length * 8 - bits);
    }
    @Override public void nextBytes(byte[] bytes) { Entropy.fill(bytes); }
    @Override public int nextInt() { return next(32); }
    @Override public double nextDouble() {
        return (((long)next(26) << 27) + next(27)) / 9007199254740992.0;
    }
    public static byte[] getSeed(int count) { return new EntropyRandom().generateSeed(count); }
    public byte[] generateSeed(int count) {
        if (count < 0) throw new IllegalArgumentException("negative-entropy-length");
        if (count > 4096) throw new java.security.ProviderException("bounded-entropy-length-limit");
        byte[] bytes = new byte[count];
        nextBytes(bytes);
        return bytes;
    }
}
