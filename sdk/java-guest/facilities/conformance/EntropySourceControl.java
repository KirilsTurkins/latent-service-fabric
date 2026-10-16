import dev.latent.generated.Bindings;
import dev.latent.guest.facilities.EntropyRandom;

public final class EntropySourceControl {
    private static int checks;
    private static void require(boolean condition) { checks++; if (!condition) throw new AssertionError(checks); }
    public static void main(String[] args) throws Exception {
        var random = new EntropyRandom();
        require(Bindings.calls == 0);
        random.nextBytes(new byte[0]);
        require(Bindings.calls == 0);
        byte[] output = new byte[32];
        random.nextBytes(output);
        require(Bindings.calls == 1);
        for (byte value : output) require(value == (byte)0xa7);
        for (byte value : Bindings.last) require(value == 0);
        for (int tag = 0; tag < 3; tag++) {
            Bindings.error = tag;
            java.util.Arrays.fill(output, (byte)73);
            try { random.nextBytes(output); throw new AssertionError("provider-error"); }
            catch (java.security.ProviderException expected) {
                require(expected.getMessage().equals(new String[]{"bounded-entropy-invalid-length",
                    "bounded-entropy-budget-exhausted", "bounded-entropy-unavailable"}[tag]));
            }
            for (byte value : output) require(value == 73);
        }
        Bindings.error = -1; Bindings.wrongLength = true;
        try { random.nextBytes(output); throw new AssertionError("wrong-length"); }
        catch (java.security.ProviderException expected) { require(expected.getMessage().equals("bounded-entropy-invalid-provider-output")); }
        for (byte value : output) require(value == 73);
        for (byte value : Bindings.last) require(value == 0);
        Bindings.wrongLength = false;
        int calls = Bindings.calls;
        try { random.nextBytes(null); throw new AssertionError("null"); } catch (NullPointerException expected) { checks++; }
        try { random.generateSeed(-1); throw new AssertionError("negative"); } catch (IllegalArgumentException expected) { checks++; }
        try { random.generateSeed(4097); throw new AssertionError("limit"); } catch (java.security.ProviderException expected) { checks++; }
        try { random.setSeed(1L); throw new AssertionError("seed"); } catch (UnsupportedOperationException expected) { checks++; }
        try { random.setSeed(new byte[]{1}); throw new AssertionError("seed"); } catch (UnsupportedOperationException expected) { checks++; }
        try { new EntropyRandom(new byte[]{1}); throw new AssertionError("constructor"); } catch (UnsupportedOperationException expected) { checks++; }
        try { random.reseed(); throw new AssertionError("reseed"); } catch (UnsupportedOperationException expected) { checks++; }
        try { EntropyRandom.getInstance("NativePRNG"); throw new AssertionError("algorithm"); }
        catch (java.security.NoSuchAlgorithmException expected) { checks++; }
        require(Bindings.calls == calls);
        require(EntropyRandom.getInstance("LSF-BoundedEntropy").getAlgorithm().equals("LSF-BoundedEntropy"));
        require(random.nextInt() == 0xa7a7a7a7);
        float small = random.nextFloat(); double large = random.nextDouble();
        require(small >= 0 && small < 1 && large >= 0 && large < 1);
        require(random.generateSeed(32).length == 32);
        System.out.println("ENTROPY_SOURCE_CONTROL PASS checks=" + checks);
    }
}
