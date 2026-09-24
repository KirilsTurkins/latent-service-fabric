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
        throw new IllegalStateException("unexpected random result");
    }
}
