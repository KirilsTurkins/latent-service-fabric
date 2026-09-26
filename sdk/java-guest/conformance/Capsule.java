package dev.latent.app;

import dev.latent.generated.Bindings;
import dev.latent.guest.Result;
import dev.latent.guest.Unsigned64;
import dev.latent.guest.Wire;

/** Executed source, not a hand-written Wasm substitute. */
public final class Capsule implements Bindings.Exports {
    private static long calls;
    @Override public java.util.List<Bindings.TestsJavaFeasibilityProbeItem> records(
        java.util.List<Bindings.TestsJavaFeasibilityProbeItem> values) { return values; }
    @Override public Long identity(Long value) { return value; }
    @Override public Unsigned64 unsigned(Unsigned64 value) { return value; }
    @Override public String text(String value) { return value; }
    @Override public Result<Long, String> declared(Boolean fail) {
        return fail ? Result.err("declared Java error") : Result.ok(42L);
    }
    @Override public Long next() { return ++calls; }
    @Override public Long smoke() {
        if (!text("Gr\u00fc\u00dfe \ud83c\udf0d\u0000Java").equals("Gr\u00fc\u00dfe \ud83c\udf0d\u0000Java"))
            throw new AssertionError("UTF-8 changed");
        boolean caught = false;
        try { throw new IllegalArgumentException("Java exception, not a WIT result"); }
        catch (IllegalArgumentException expected) { caught = true; }
        if (!caught) throw new AssertionError("Java exception disappeared");
        long total = 0;
        for (int i = 0; i < 8192; i++) { byte[] bytes = new byte[1024]; bytes[0] = (byte)i; total += bytes[0]; }
        if (total != -4096) throw new AssertionError("Java GC changed values");
        var bytes = Bindings.LatentRandomRandom.bytes(32L);
        if (bytes.isError() || bytes.value().length != 32) throw new AssertionError("async random result changed");
        java.util.Arrays.fill(bytes.value(), (byte)0);
        return 4L;
    }
}
