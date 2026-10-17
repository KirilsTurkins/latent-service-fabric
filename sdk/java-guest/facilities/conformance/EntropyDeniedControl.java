import dev.latent.guest.facilities.EntropyRandom;

public final class EntropyDeniedControl {
    public static void main(String[] args) {
        var random = new EntropyRandom();
        random.nextBytes(new byte[0]);
        byte[] output = {73};
        try { random.nextBytes(output); throw new AssertionError("undeclared-entropy-accepted"); }
        catch (java.security.ProviderException expected) {
            if (!expected.getMessage().equals("bounded-entropy-capability-not-declared") || output[0] != 73)
                throw new AssertionError("undeclared-entropy-outcome");
        }
        System.out.println("ENTROPY_DENIED_CONTROL PASS explicit-failure;empty-noop;unchanged-output;no-bindings");
    }
}
