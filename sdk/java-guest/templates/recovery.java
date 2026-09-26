package dev.latent.app;
import dev.latent.generated.Bindings;
import java.util.ArrayList;

public final class Capsule implements Bindings.Exports {
    private static long calls;
    private static volatile long spin;
    public Long run(Long which) {
        if (which == 1) throw new IllegalStateException("deliberate guest exception");
        if (which == 2) {
            // Keep objects live: this is actual TeaVM managed-heap exhaustion,
            // not a native fixture pretending to execute Java allocation.
            var retained = new ArrayList<byte[]>();
            for (;;) { retained.add(new byte[65536]); spin = retained.size(); }
        }
        if (which == 3) for (;;) spin++;
        return ++calls;
    }
}
